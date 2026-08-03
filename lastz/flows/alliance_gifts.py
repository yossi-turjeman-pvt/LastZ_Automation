"""
Gifts collection flow — HQ Drone + Battlefield + Alliance Gifts + Alliance Techs + Trucks.

Navigation uses template matching so clicks stay accurate on any display size.
Spatial bands reject high-confidence false positives outside expected UI regions.
"""
import time

import cv2
import numpy as np

from lastz.config import load_config, threshold as cfg_threshold
from lastz.debug_match import annotate_and_save, in_band
from lastz.flows.base import dismiss_overlay, ensure_wilderness, reset_ui
from lastz.flows.drone_gift import run_drone_gift_flow
from lastz.flows.loot_parse import parse_battle_rewards, read_congrats_popup
from lastz.flows.trucks import run_trucks_flow
from lastz.flows.ui_bands import (
    BAND_ALLIANCE_GRID,
    BAND_HUD_SHIELD,
    BAND_RARE_TAB,
    BAND_TECH_TREE,
    CLAIM_MAX_Y_FRAC,
)
from lastz.heli_priority import HeliInterrupt, check_heli_interrupt
from lastz.stats import (
    begin_run_stats,
    end_run_stats,
    record_claim,
    record_donations,
    record_loot,
)

_GIFTS_STEPS = ("drone", "battlefield", "alliance_gifts", "techs", "trucks")


def _step_reached(step: str, start_at: str | None) -> bool:
    """True if this step should run given an optional resume start_at."""
    if not start_at:
        return True
    if start_at not in _GIFTS_STEPS:
        return True
    return _GIFTS_STEPS.index(step) >= _GIFTS_STEPS.index(start_at)


def _heli_checkpoint(source: str, step: str) -> None:
    """Watcher only: yield to Helicopter if BR indication was spotted."""
    if source != "watcher":
        return
    from lastz.flows.helicopter import helicopter_cfg

    if not helicopter_cfg().get("enabled", True):
        return
    check_heli_interrupt(step)


def _guarded_step(step_label: str, block) -> None:
    """
    Run one top-level gifts step; a failure here logs and lets the flow
    continue to the next step instead of aborting drone/trucks/etc that
    haven't run yet. HeliInterrupt (priority yield) always propagates.
    """
    try:
        block()
    except HeliInterrupt:
        raise
    except Exception as exc:
        log(f"[Gifts] ERROR during {step_label}: {exc}")
        dump_crash(exc, prefix=f"crash_gifts_{step_label.lower()}")
        log_step(step_label, "fail", f"exception: {exc}"[:200])
        # A step can fail mid-modal (e.g. Gifts panel still open, covering the
        # HUD shield the next step needs). Best-effort clear so later steps
        # get a clean base instead of also failing/skipping in a cascade.
        try:
            reset_ui(clicks=2, delay=1.0)
        except Exception as reset_exc:
            log(f"[Gifts] WARN: reset_ui after {step_label} failure also failed: {reset_exc}")

from lastz.input import click, ensure_game_running, focus_game
from lastz.ocr import (
    read_ui_text,
    text_mentions_techs,
    text_mentions_wrong_alliance_tile,
    tesseract_available,
)
from lastz.runlog import (
    begin_run_logging,
    dump_crash,
    end_run_logging,
    log,
    log_click,
    log_gifts_modal_state,
    log_run_header,
    log_skip,
    log_step,
)
from lastz.screen import capture, capture_both, physical_to_logical
from lastz.vision import (
    MatchWithBBox,
    click_template,
    ensure_template_scale,
    find_all_templates,
    find_any,
    find_template,
)

_MAX_INDIVIDUAL_CLAIMS = 15
_CLAIM_MIN_GREEN_RATIO = 0.20
_DONATE_MIN_BLUE_RATIO = 0.15
_THUMBS_MIN_ORANGE_RATIO = 0.12
_THUMBS_NUDGE_X_FRAC = 0.35
_THUMBS_NUDGE_Y_FRAC = 0.45


def _green_ratio(bgr: np.ndarray) -> float:
    if bgr is None or bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (35, 50, 50), (95, 255, 255))
    return float(mask.mean()) / 255.0


def _blue_ratio(bgr: np.ndarray) -> float:
    if bgr is None or bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (95, 60, 50), (140, 255, 255))
    return float(mask.mean()) / 255.0


def _orange_ratio(bgr: np.ndarray) -> float:
    if bgr is None or bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (5, 80, 80), (30, 255, 255))
    return float(mask.mean()) / 255.0


def _match_roi(color: np.ndarray, match) -> np.ndarray:
    h, w = color.shape[:2]
    half_w = max(8, match.phys_w // 2)
    half_h = max(8, match.phys_h // 2)
    x1 = max(0, int(match.phys_x - half_w))
    y1 = max(0, int(match.phys_y - half_h))
    x2 = min(w, int(match.phys_x + half_w))
    y2 = min(h, int(match.phys_y + half_h))
    return color[y1:y2, x1:x2]


def _max_tech_donates() -> int:
    cfg = load_config().get("alliance_techs") or {}
    return int(cfg.get("max_donates", 20))


def _band_ok(match, h: int, w: int, band: tuple[float, float, float, float]) -> bool:
    y0, y1, x0, x1 = band
    return in_band(match.phys_x, match.phys_y, h, w, y0, y1, x0, x1)


def _find_list_claim_button(gray, color):
    """Best green Claim button in the gift list; None if none remain."""
    matches = find_all_templates(
        gray,
        "claim_button_clean.png",
        cfg_threshold("claim_button"),
    )
    if not matches:
        print("[Gifts] No claim_button matches above threshold.")
        return None

    max_y = gray.shape[0] * CLAIM_MAX_Y_FRAC
    list_matches = [m for m in matches if m.phys_y <= max_y]
    if not list_matches:
        best = matches[0]
        print(
            f"[Gifts] No list Claim buttons left "
            f"(best in footer/back y={best.phys_y:.0f}, conf={best.confidence:.4f}, "
            f"max_y={max_y:.0f}) — stopping"
        )
        return None

    green_matches = []
    for m in list_matches:
        ratio = _green_ratio(_match_roi(color, m))
        ok = ratio >= _CLAIM_MIN_GREEN_RATIO
        print(
            f"[Gifts] Claim candidate conf={m.confidence:.4f} y={m.phys_y:.0f} "
            f"green_ratio={ratio:.3f} (need>={_CLAIM_MIN_GREEN_RATIO}) "
            f"{'OK' if ok else 'REJECT'}"
        )
        if ok:
            green_matches.append(m)

    if not green_matches:
        print("[Gifts] No green Claim buttons left — stopping")
        return None
    # Top of list first (same screen slot as rows clear), matching the live step run.
    green_matches.sort(key=lambda m: m.phys_y)
    return green_matches[0]


def _try_claim_all(*, tab_name: str = "Common") -> str | None:
    screen = capture()
    m = find_any(
        screen,
        ["claim_all_button_clean.png", "universal_claim_all_button.png"],
        cfg_threshold("claim_all"),
    )
    if m is None:
        print("[Gifts] No Claim All button — will try individual Claims.")
        return None
    h = screen.shape[0]
    lx, ly = physical_to_logical(m.phys_x, m.phys_y)
    log_click(
        "claim_all",
        template="claim_all_button_clean.png",
        conf=m.confidence,
        logical_xy=(lx, ly),
        phys_xy=(m.phys_x, m.phys_y),
        y_frac=m.phys_y / h,
    )
    click(lx, ly)
    # Congrats popup is usually fully visible by ~1.25s, but under
    # background-thread contention (heli BR monitor) or plain game lag it
    # can render later — retry a couple more times before giving up.
    # Real incident: Alliance Gifts' Common tab leaves an always-on
    # boomer-spoils/activity-log panel in the exact same ROI when no real
    # popup is showing yet; OCR-ing that panel and reporting it as "loot"
    # produced a false "Claimed All (Instant)" success on every cycle,
    # every night, with nothing actually claimed server-side. Only trust
    # parsed items once read_congrats_popup() confirms the real
    # "Congratulations!" header was present.
    popup_confirmed = False
    loot: dict[str, float] = {}
    for attempt, wait in enumerate((1.25, 1.0, 1.5)):
        time.sleep(wait)
        color, _gray = capture_both()
        popup_confirmed, loot = read_congrats_popup(color)
        if popup_confirmed:
            break
        print(
            f"[Gifts] Claim-All reward popup not confirmed yet "
            f"(attempt {attempt + 1}/3) — retrying capture"
        )
    if not popup_confirmed:
        # Never trust items parsed without a confirmed popup — the parser
        # can "succeed" on unrelated background text (see module docstring
        # on read_congrats_popup), which is exactly the bug this guards.
        loot = {}
    if loot:
        record_loot("alliance_gifts", loot)
    claim_key = (
        "rare_claim_all" if tab_name.lower().startswith("rare") else "common_claim_all"
    )
    if popup_confirmed:
        record_claim(claim_key)
    # Exactly one outside click: closes the reward popup, leaves Gifts open.
    # A second outside click (e.g. before Rare) closes Gifts itself — do not add one.
    print("[Gifts] Dismissing reward popup (single outside click)...")
    dismiss_overlay(delay=1.2)
    if not popup_confirmed:
        print(
            "[Gifts] WARN: Claim All clicked but no reward popup confirmed — "
            "click registered (button matched) but loot is unverified."
        )
        return "Claimed All (unconfirmed — no reward popup captured)"
    if loot:
        bits = ", ".join(f"{k}={v:g}" for k, v in sorted(loot.items()))
        return f"Claimed All (Instant); loot: {bits}"
    return "Claimed All (Instant)"


def _claim_tab(tab_name: str) -> str:
    print(f"[Gifts] Claiming on {tab_name} tab...")
    claim_all_status = _try_claim_all(tab_name=tab_name)
    if claim_all_status is not None:
        return claim_all_status

    claimed = 0
    for _ in range(_MAX_INDIVIDUAL_CLAIMS):
        color, gray = capture_both()
        m = _find_list_claim_button(gray, color)
        if m is None:
            break
        lx, ly = physical_to_logical(m.phys_x, m.phys_y)
        log_click(
            f"claim_{tab_name.lower()}",
            template="claim_button_clean.png",
            conf=m.confidence,
            logical_xy=(lx, ly),
            phys_xy=(m.phys_x, m.phys_y),
            y_frac=m.phys_y / color.shape[0],
        )
        click(lx, ly)
        claimed += 1
        time.sleep(1.5)

    if claimed:
        claim_key = (
            "rare_individual"
            if tab_name.lower().startswith("rare")
            else "common_individual"
        )
        record_claim(claim_key, claimed)
    return f"Claimed {claimed} individual gifts"


def _switch_to_rare_tab() -> bool:
    """
    Switch Gifts → Rare.

    Rare = white "Rare" label on inactive tan/dark tab (under chest/Level bar).
    One outside dismiss after Common Claim All only — never dismiss here.
    """
    thr = cfg_threshold("rare_tab")
    print(f"[Gifts] Switching to Rare tab (thr={thr})...")

    for attempt in range(3):
        color, gray = capture_both()
        h, w = color.shape[:2]
        m = find_template(gray, "rare_tab.png", thr)
        if m is None:
            print(f"[Gifts] rare_tab not found (attempt {attempt + 1})")
            annotate_and_save(color, f"rare_miss_{attempt}", [], subdir="flow")
            continue
        yf = m.phys_y / h
        if not in_band(m.phys_x, m.phys_y, h, w, *BAND_RARE_TAB):
            print(
                f"[Gifts] rare_tab REJECT outside tab band "
                f"yf={yf:.2f} conf={m.confidence:.4f}"
            )
            annotate_and_save(
                color,
                f"rare_reject_{attempt}",
                [{"label": "rare_OUT", "phys_x": m.phys_x, "phys_y": m.phys_y,
                  "conf": m.confidence, "ok": False}],
                subdir="flow",
            )
            continue

        # BAND_RARE_TAB alone can't tell "real Rare tab" from "plain Alliance
        # grid" — a green checkmark icon in the Alliance description text
        # falls in the exact same band and scored 0.80 (real incident
        # 2026-08-02, thr=0.78). If the grid's own Gifts tile is still
        # visible, we're not actually inside the Gifts sub-panel at all.
        grid_gifts = find_all_templates(
            gray, "alliance_gifts_precise.png", cfg_threshold("alliance_gifts")
        )
        if any(_band_ok(gg, h, w, BAND_ALLIANCE_GRID) for gg in grid_gifts):
            print(
                f"[Gifts] rare_tab REJECT — Alliance grid still visible "
                f"(not inside Gifts panel) yf={yf:.2f} conf={m.confidence:.4f}"
            )
            annotate_and_save(
                color,
                f"rare_reject_grid_{attempt}",
                [{"label": "rare_FALSE_grid_visible", "phys_x": m.phys_x, "phys_y": m.phys_y,
                  "conf": m.confidence, "ok": False}],
                subdir="flow",
            )
            continue

        lx, ly = physical_to_logical(m.phys_x, m.phys_y)
        print(
            f"[Gifts] Clicking Rare at logical ({lx:.1f}, {ly:.1f}) "
            f"phys=({m.phys_x:.0f},{m.phys_y:.0f}) conf={m.confidence:.4f} "
            f"yf={yf:.2f} attempt={attempt + 1}"
        )
        log_click(
            "rare_tab",
            template="rare_tab.png",
            conf=m.confidence,
            logical_xy=(lx, ly),
            phys_xy=(m.phys_x, m.phys_y),
            y_frac=yf,
        )
        annotate_and_save(
            color,
            f"rare_click_{attempt}",
            [{"label": "rare", "phys_x": m.phys_x, "phys_y": m.phys_y,
              "conf": m.confidence, "ok": True}],
            subdir="flow",
        )
        click(lx, ly)
        time.sleep(1.8)

        color2, gray2 = capture_both()
        has_claim_all = find_any(
            gray2,
            ["claim_all_button_clean.png", "universal_claim_all_button.png"],
            cfg_threshold("claim_all"),
        ) is not None
        green = _find_list_claim_button(gray2, color2)
        if has_claim_all or green is not None:
            print("[Gifts] Rare switch verified (Claim All or list Claim visible).")
            return True
        # In-band click landed; Rare may be empty. Do not outside-click / re-open.
        print("[Gifts] Rare clicked (no claims visible — empty Rare possible).")
        return True

    print("[Gifts] WARN: Rare tab not clicked after retries.")
    return False


def _alliance_grid_visible() -> bool:
    """True if the plain Alliance main menu (Wars/Techs/Gifts/Shop/... tile
    grid) is actually on screen right now."""
    gray = capture()
    h, w = gray.shape[:2]
    m = find_template(gray, "alliance_gifts_precise.png", cfg_threshold("alliance_gifts"))
    return m is not None and _band_ok(m, h, w, BAND_ALLIANCE_GRID)


def _open_alliance_menu(attempts: int = 5, delay: float = 1.5) -> bool:
    """
    Click the HUD shield to open the Alliance menu; retries because the
    shield can be briefly hidden by an animation/toast right after a prior
    modal closes.

    Verifies the Alliance grid actually appeared before returning success --
    the same "click registered but panel never opened" failure mode hit the
    Alliance Gifts tile click one level down (real incident 2026-08-02); a
    live overnight run on this same date showed the identical shape one
    level up: the shield click was logged as succeeding, but 6 retries of
    the Alliance Gifts tile search all found nothing, and the eventual
    crash screenshot showed the plain wilderness map -- meaning the
    Alliance menu itself had never (or no longer) been open the whole time.
    """
    thr = cfg_threshold("alliance_shield")
    for attempt in range(attempts):
        color, gray = capture_both()
        h, w = gray.shape[:2]
        shields = find_all_templates(gray, "alliance_shield_clean.png", thr)
        hud = [m for m in shields if _band_ok(m, h, w, BAND_HUD_SHIELD)]
        if hud:
            hud.sort(key=lambda m: m.confidence, reverse=True)
            m = hud[0]
            lx, ly = physical_to_logical(m.phys_x, m.phys_y)
            log_click(
                "alliance_shield",
                template="alliance_shield_clean.png",
                conf=m.confidence,
                logical_xy=(lx, ly),
                phys_xy=(m.phys_x, m.phys_y),
                y_frac=m.phys_y / h,
            )
            click(lx, ly)
            time.sleep(2.0)

            if _alliance_grid_visible():
                return True
            print(
                f"[Gifts] Shield clicked but Alliance grid not confirmed "
                f"(attempt {attempt + 1}/{attempts}) — retrying"
            )
            if attempt < attempts - 1:
                time.sleep(delay)
            continue
        print(f"[Gifts] HUD shield not found (attempt {attempt + 1}/{attempts})")
        if attempt < attempts - 1:
            time.sleep(delay)
    return False


def _open_alliance_gifts_tile(attempts: int = 6, delay: float = 1.5) -> bool:
    """
    Click the Alliance Gifts tile inside the (already open) Alliance menu.

    Retries with a short poll instead of a single capture: the Alliance
    panel can still be animating in for ~1-2s after the shield click, and a
    one-shot capture right after a fixed sleep can miss a tile that becomes
    fully visible moments later (root cause of the 2026-07-30 "Alliance
    Gifts button not found" failures — offline replay of the failure frame
    matched the tile at 0.96 confidence).

    Every click is followed by a positive verification that the Gifts
    sub-panel (Common/Rare tabs) actually opened, not just assumed from the
    click succeeding. Real incident 2026-08-02: the tile click registered
    (high-confidence match, click fired) but the sub-panel never opened —
    the flow then silently ran Common/Rare claim searches against the plain
    Alliance grid for the rest of the step, finding nothing and logging it
    as "Claimed 0" (indistinguishable from a legitimately-empty tab). A
    `rare_tab.png` false-positive against a green checkmark icon in the
    Alliance description text (same on-screen band the real Rare tab uses)
    then let a bogus "Rare switched" report through too. Retrying the tile
    click when the panel isn't confirmed open closes that whole gap.
    """
    thr = cfg_threshold("alliance_gifts")
    for attempt in range(attempts):
        gray = capture()
        h, w = gray.shape[:2]
        gifts = find_all_templates(gray, "alliance_gifts_precise.png", thr)
        gifts_in = [m for m in gifts if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
        if gifts_in:
            gifts_in.sort(key=lambda m: m.confidence, reverse=True)
            g = gifts_in[0]
            lx, ly = physical_to_logical(g.phys_x, g.phys_y)
            log_click(
                "alliance_gifts",
                template="alliance_gifts_precise.png",
                conf=g.confidence,
                logical_xy=(lx, ly),
                phys_xy=(g.phys_x, g.phys_y),
                y_frac=g.phys_y / h,
            )
            click(lx, ly)
            time.sleep(2.0)

            state = log_gifts_modal_state("after_gifts_tile_click")
            # "claim_all_still_visible" (Claim All found, but rare_tab.png
            # didn't match this exact frame) only occurs when the grid tile
            # is also confirmed gone — still solid evidence the real panel
            # is open, just with a possibly-slow-to-render Rare tab.
            if state in ("gifts_modal_open", "claim_all_still_visible"):
                return True
            print(
                f"[Gifts] Alliance Gifts tile clicked but panel state={state} "
                f"(attempt {attempt + 1}/{attempts}) — retrying click"
            )
            if attempt < attempts - 1:
                time.sleep(delay)
            continue

        print(
            f"[Gifts] Alliance Gifts tile not found (attempt {attempt + 1}/{attempts}) "
            "— panel may still be opening"
        )
        if attempt < attempts - 1:
            time.sleep(delay)
    return False


def _claim_battlefield_gifts() -> str:
    print("Checking for Battlefield Gifts chest...")
    screen = capture()
    orange_match = find_template(
        screen,
        "orange_icon_no_badge.png",
        cfg_threshold("orange_icon"),
    )
    if orange_match is None:
        print("-> Battlefield Gifts chest not on screen — skipping.")
        return "skipped"

    lx, ly = physical_to_logical(orange_match.phys_x, orange_match.phys_y)
    print(f"-> Opening Battlefield Gifts at logical ({lx:.1f}, {ly:.1f}) [conf={orange_match.confidence:.4f}]")
    click(lx, ly)
    time.sleep(2.5)

    # Loot is visible in the Battle Rewards table BEFORE Claim All (no Congrats popup).
    color_modal, gray_modal = capture_both()
    bf_loot = parse_battle_rewards(color_modal)
    claim_match = find_template(
        gray_modal,
        "universal_claim_all_button.png",
        cfg_threshold("claim_all"),
    )
    if claim_match is not None:
        if bf_loot:
            record_loot("battlefield", bf_loot)
        record_claim("battlefield_claim_all")
        clx, cly = physical_to_logical(claim_match.phys_x, claim_match.phys_y)
        print(f"-> Clicking 'Claim All' at logical ({clx:.1f}, {cly:.1f})...")
        click(clx, cly)
        time.sleep(2.0)
        print("Dismissing Battlefield rewards overlay...")
        dismiss_overlay()
    else:
        print("-> No 'Claim All' button inside Battlefield Gifts modal.")

    print("Closing Battlefield Gifts modal...")
    dismiss_overlay()
    if bf_loot and claim_match is not None:
        bits = ", ".join(f"{k}={v:g}" for k, v in sorted(bf_loot.items()))
        return f"claimed; loot: {bits}"
    return "claimed"


def _pick_tech_target(gray, color) -> tuple[MatchWithBBox, str] | None:
    """Prefer orange thumbs-up in tech-tree band; else lit hex in same band."""
    h, w = gray.shape[:2]
    thumbs_thr = cfg_threshold("tech_thumbs_up")
    print(f"[Techs] Looking for thumbs-up (threshold={thumbs_thr})...")
    thumbs = find_all_templates(gray, "tech_thumbs_up.png", thumbs_thr)
    print(f"[Techs] thumbs raw matches={len(thumbs)}")
    survivors = []
    for m in thumbs:
        if not _band_ok(m, h, w, BAND_TECH_TREE):
            yf = m.phys_y / h
            print(f"[Techs] reject thumbs outside tree band y_frac={yf:.2f} conf={m.confidence:.4f}")
            continue
        orange = _orange_ratio(_match_roi(color, m))
        ok = orange >= _THUMBS_MIN_ORANGE_RATIO
        print(
            f"[Techs] thumbs conf={m.confidence:.4f} orange={orange:.3f} "
            f"{'OK' if ok else 'REJECT'}"
        )
        if ok:
            survivors.append(m)
    if survivors:
        survivors.sort(key=lambda m: m.confidence, reverse=True)
        best = survivors[0]
        print(
            f"[Techs] Thumbs-up picked: conf={best.confidence:.4f} "
            f"at phys=({best.phys_x:.0f},{best.phys_y:.0f}) "
            f"({len(survivors)}/{len(thumbs)} after filters)"
        )
        return best, "thumbs-up"

    print("[Techs] No in-band orange thumbs — falling back to active hex...")
    hex_thr = cfg_threshold("tech_hex_active")
    hexes = find_all_templates(gray, "tech_hex_active.png", hex_thr)
    upper = [m for m in hexes if _band_ok(m, h, w, BAND_TECH_TREE)]
    if not upper:
        print(f"[Techs] No tech_hex_active in tree band (raw={len(hexes)}).")
        return None
    upper.sort(key=lambda m: m.confidence, reverse=True)
    best = upper[0]
    print(
        f"[Techs] Active hex picked: conf={best.confidence:.4f} "
        f"at phys=({best.phys_x:.0f},{best.phys_y:.0f})"
    )
    return best, "active-hex"


def _click_tech_match(match, source: str) -> None:
    phys_x, phys_y = match.phys_x, match.phys_y
    nudged = False
    if source == "thumbs-up":
        phys_x += match.phys_w * _THUMBS_NUDGE_X_FRAC
        phys_y += match.phys_h * _THUMBS_NUDGE_Y_FRAC
        nudged = True
    lx, ly = physical_to_logical(phys_x, phys_y)
    nudge_note = (
        f" (nudged +{match.phys_w * _THUMBS_NUDGE_X_FRAC:.0f}x/"
        f"+{match.phys_h * _THUMBS_NUDGE_Y_FRAC:.0f}y phys)"
        if nudged
        else ""
    )
    print(
        f"[Techs] Opening tech via {source} at logical ({lx:.1f}, {ly:.1f}) "
        f"[conf={match.confidence:.4f}]{nudge_note}"
    )
    click(lx, ly)


def _find_blue_donate(gray, color):
    thr = cfg_threshold("donate_blue")
    matches = find_all_templates(gray, "donate_blue.png", thr)
    if not matches:
        print(f"[Techs] No donate_blue match (threshold={thr}).")
        return None
    blue = []
    for m in matches:
        ratio = _blue_ratio(_match_roi(color, m))
        is_blue = ratio >= _DONATE_MIN_BLUE_RATIO
        print(
            f"[Techs] Donate candidate conf={m.confidence:.4f} "
            f"blue_ratio={ratio:.3f} (need>={_DONATE_MIN_BLUE_RATIO}) "
            f"{'OK' if is_blue else 'REJECT'}"
        )
        if is_blue:
            blue.append(m)
    if not blue:
        print("[Techs] All Donate matches failed blue HSV filter — stop.")
        return None
    return blue[0]


def _best_in_band_template(
    gray,
    color,
    names: list[str],
    thr: float,
    band: tuple[float, float, float, float],
) -> MatchWithBBox | None:
    h, w = gray.shape[:2]
    best: MatchWithBBox | None = None
    for name in names:
        matches = find_all_templates(gray, name, thr)
        for m in matches:
            if not _band_ok(m, h, w, band):
                yf = m.phys_y / h
                print(f"[Techs] reject {name} outside band y_frac={yf:.2f} conf={m.confidence:.4f}")
                continue
            if best is None or m.confidence > best.confidence:
                best = m
                best = MatchWithBBox(m.phys_x, m.phys_y, m.phys_w, m.phys_h, m.confidence)
                # stash name via print
                print(f"[Techs] candidate {name} conf={m.confidence:.4f} in band")
    return best


def _techs_label_ocr_ok(color: np.ndarray, m: MatchWithBBox, h: int, w: int) -> bool:
    """OCR a tight crop on the tile title; fuzzy-match Alliance Techs."""
    if not tesseract_available():
        print("[Techs] OCR unavailable — cannot confirm label text")
        return False
    # Tight title band under the icon (avoid neighboring tiles / Shop)
    pad_x = max(int(m.phys_w * 0.55), int(0.055 * w))
    pad_y = max(int(m.phys_h * 0.45), int(0.028 * h))
    cx, cy = int(m.phys_x), int(m.phys_y)
    x0 = max(0, cx - pad_x)
    y0 = max(0, cy - pad_y // 5)
    text = read_ui_text(color, x0, y0, pad_x * 2, pad_y)
    if text_mentions_wrong_alliance_tile(text):
        print(f"[Techs] OCR wrong tile text={text!r}")
        return False
    ok = text_mentions_techs(text)
    print(f"[Techs] OCR confirm tech={ok} text={text!r}")
    return ok


def _techs_via_gifts_neighbor(
    color: np.ndarray, gray: np.ndarray, h: int, w: int
) -> MatchWithBBox | None:
    """
    Alliance Techs is the left neighbor of Alliance Gifts (same row).

    Prefer OCR confirm; if OCR is empty/noisy (not clearly Shop/Gifts),
    still click the spatial neighbor — Gifts match is high-confidence.
    """
    gifts_thr = cfg_threshold("alliance_gifts")
    gifts = find_all_templates(gray, "alliance_gifts_precise.png", gifts_thr)
    gifts_in = [m for m in gifts if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
    if not gifts_in:
        print("[Techs] Gifts neighbor: no Alliance Gifts in grid band")
        return None
    gifts_in.sort(key=lambda m: m.confidence, reverse=True)
    g = gifts_in[0]
    # Horizontal pitch ≈ one tile width (Gifts bbox is a reliable scale cue)
    pitch = max(float(g.phys_w) * 1.15, 0.09 * w)
    cx = g.phys_x - pitch
    cy = g.phys_y
    if not (BAND_ALLIANCE_GRID[2] * w <= cx <= BAND_ALLIANCE_GRID[3] * w):
        print(f"[Techs] Gifts neighbor: estimated Techs x out of band ({cx:.0f})")
        return None
    if not (BAND_ALLIANCE_GRID[0] * h <= cy <= BAND_ALLIANCE_GRID[1] * h):
        print(f"[Techs] Gifts neighbor: estimated Techs y out of band ({cy:.0f})")
        return None

    tw = max(int(g.phys_w), int(0.08 * w))
    th = max(int(g.phys_h), int(0.06 * h))
    cand = MatchWithBBox(cx, cy, tw, th, g.confidence)

    print(
        f"[Techs] Gifts neighbor: gifts=({g.phys_x:.0f},{g.phys_y:.0f}) "
        f"-> techs=({cx:.0f},{cy:.0f}) pitch={pitch:.0f}"
    )

    if not tesseract_available():
        print("[Techs] Gifts neighbor: OCR unavailable — spatial click")
        return cand

    # Tight title strip under estimated tile center (not a huge multi-tile crop)
    label_w = int(0.11 * w)
    label_h = int(0.040 * h)
    lx0 = int(cx - label_w / 2)
    ly0 = int(cy + 0.018 * h)
    text = read_ui_text(color, lx0, ly0, label_w, label_h)

    if text_mentions_wrong_alliance_tile(text):
        print(f"[Techs] Gifts neighbor: OCR says wrong tile — abort text={text!r}")
        return None
    if text_mentions_techs(text):
        print(f"[Techs] Gifts neighbor: OCR confirmed Techs text={text!r}")
        return cand

    # Noisy / empty OCR — trust same-row left-of-Gifts geometry
    print(
        f"[Techs] Gifts neighbor: OCR inconclusive text={text!r} — "
        f"using spatial click (gifts conf={g.confidence:.4f})"
    )
    return cand


def _open_alliance_techs() -> bool:
    """
    Open Techs: microscope in band → soft microscope → Gifts left-neighbor
    (OCR-confirmed) → label template only if OCR says tech.
    """
    techs_thr = cfg_threshold("alliance_techs")
    print(f"[Techs] Looking for Alliance Techs in grid band (threshold={techs_thr})...")
    color, gray = capture_both()
    h, w = gray.shape[:2]

    pick: MatchWithBBox | None = None
    tag = ""

    # 1) Microscope icon
    icon_matches = find_all_templates(gray, "alliance_techs.png", techs_thr)
    icon_in = [m for m in icon_matches if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
    if icon_in:
        icon_in.sort(key=lambda m: m.confidence, reverse=True)
        pick, tag = icon_in[0], "microscope"
    else:
        soft = find_all_templates(gray, "alliance_techs.png", max(0.50, techs_thr - 0.15))
        soft_in = [m for m in soft if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
        if soft_in:
            soft_in.sort(key=lambda m: m.confidence, reverse=True)
            pick, tag = soft_in[0], "microscope-soft"

    # 2) Spatial: left of Alliance Gifts + OCR
    if pick is None:
        pick = _techs_via_gifts_neighbor(color, gray, h, w)
        if pick is not None:
            tag = "gifts-neighbor"

    # 3) Label template only with OCR confirm (never click Shop on text FP)
    if pick is None:
        label_matches = find_all_templates(gray, "alliance_techs_label.png", techs_thr)
        label_in = [m for m in label_matches if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
        label_in.sort(key=lambda m: m.confidence, reverse=True)
        for m in label_in:
            if _techs_label_ocr_ok(color, m, h, w):
                pick, tag = m, "label+ocr"
                break
            print(
                f"[Techs] reject label conf={m.confidence:.4f} at "
                f"({m.phys_x:.0f},{m.phys_y:.0f}) — OCR not techs"
            )

    if pick is None:
        print("[Techs] FAIL: no Alliance Techs match in alliance grid band.")
        annotate_and_save(color, "techs_miss", [], subdir="flow")
        return False

    lx, ly = physical_to_logical(pick.phys_x, pick.phys_y)
    print(
        f"[Techs] Clicking Alliance Techs ({tag}) at logical ({lx:.1f}, {ly:.1f}) "
        f"[conf={pick.confidence:.4f}]"
    )
    log_click(
        "alliance_techs",
        template=tag,
        conf=pick.confidence,
        logical_xy=(lx, ly),
        phys_xy=(pick.phys_x, pick.phys_y),
        y_frac=pick.phys_y / h,
    )
    annotate_and_save(
        color,
        "techs_click",
        [{"label": tag, "phys_x": pick.phys_x, "phys_y": pick.phys_y,
          "conf": pick.confidence, "phys_w": pick.phys_w, "phys_h": pick.phys_h, "ok": True}],
        subdir="flow",
    )
    click(lx, ly)
    return True


def _ensure_alliance_open_for_techs() -> None:
    """If Alliance grid tiles missing, re-open via HUD shield in right-stack band only."""
    color, gray = capture_both()
    h, w = gray.shape[:2]
    grid = _best_in_band_template(
        gray,
        color,
        ["alliance_techs.png", "alliance_gifts_precise.png"],
        min(cfg_threshold("alliance_techs"), cfg_threshold("alliance_gifts")),
        BAND_ALLIANCE_GRID,
    )
    # Also accept gifts at slightly lower thr for presence
    if grid is None:
        gifts = find_all_templates(gray, "alliance_gifts_precise.png", cfg_threshold("alliance_gifts"))
        gifts_in = [m for m in gifts if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
        if gifts_in:
            grid = gifts_in[0]

    if grid is not None:
        print("[Techs] Alliance grid still open — proceeding to Techs.")
        return

    print("[Techs] Alliance grid not visible — looking for HUD shield in right stack...")
    shields = find_all_templates(gray, "alliance_shield_clean.png", cfg_threshold("alliance_shield"))
    hud = [m for m in shields if _band_ok(m, h, w, BAND_HUD_SHIELD)]
    if not hud:
        print("[Techs] WARN: no HUD shield in right-stack band — Techs may fail.")
        return
    hud.sort(key=lambda m: m.confidence, reverse=True)
    m = hud[0]
    lx, ly = physical_to_logical(m.phys_x, m.phys_y)
    print(
        f"[Techs] Re-opening Alliance via HUD shield at logical ({lx:.1f}, {ly:.1f}) "
        f"[conf={m.confidence:.4f}]"
    )
    click(lx, ly)
    time.sleep(2.0)


def _donate_alliance_techs() -> str:
    print("[Techs] === Alliance Techs donations ===")
    if not _open_alliance_techs():
        return "skipped: techs button"

    print("[Techs] Waiting for tech tree to settle...")
    time.sleep(2.0)

    color, gray = capture_both()
    picked = _pick_tech_target(gray, color)
    if picked is None:
        print("[Techs] FAIL: no thumbs-up and no active hex — dismissing Techs.")
        # This used to be a silent skip with no way to tell "genuinely
        # nothing to donate to" from "detector missed a real tech" after
        # the fact. Save what the tree actually looked like so a real
        # miss is visible in logs/debug/flow instead of just trusting the
        # skip.
        annotate_and_save(color, "techs_no_target", [], subdir="flow")
        dismiss_overlay(delay=1.5)
        return "skipped: no tech"

    match, source = picked
    _click_tech_match(match, source)
    time.sleep(1.5)

    max_clicks = _max_tech_donates()
    print(f"[Techs] Blue Donate loop (max {max_clicks} clicks)...")
    donated = 0
    stop_reason = "max_clicks"
    for i in range(max_clicks):
        color, gray = capture_both()
        donate = _find_blue_donate(gray, color)
        if donate is None:
            stop_reason = "no_blue_donate"
            print(f"[Techs] Donate loop stop after {donated} click(s): {stop_reason}")
            break
        lx, ly = physical_to_logical(donate.phys_x, donate.phys_y)
        print(
            f"[Techs] Donate click {i + 1}/{max_clicks} at logical ({lx:.1f}, {ly:.1f}) "
            f"[conf={donate.confidence:.4f}]"
        )
        click(lx, ly)
        donated += 1
        time.sleep(1.2)
    else:
        print(f"[Techs] Donate loop hit max_clicks={max_clicks}")

    print(f"[Techs] Done: donated={donated} stop={stop_reason}")
    if donated:
        record_donations(donated)
    print("[Techs] Dismissing tech detail modal...")
    dismiss_overlay(delay=1.5)
    print("[Techs] Dismissing Alliance Techs screen...")
    dismiss_overlay(delay=1.5)
    return f"donated {donated}"


def run_alliance_gifts_flow(
    *,
    source: str = "menu",
    start_at: str | None = None,
) -> None:
    """
    Full gifts collection. Optional start_at resumes after a HeliInterrupt
    (one of: drone, battlefield, alliance_gifts, techs, trucks).
    """
    begin_run_logging()
    begin_run_stats()
    try:
        ensure_game_running()
        log("[Timing] focus_game start")
        focus_game()
        log("[Timing] focus_game done")

        # Capture once so run header can include capture size + scale.
        log("[Timing] first capture start")
        screen = capture()
        log("[Timing] first capture done")
        log("[Timing] scale calibrate start")
        ensure_template_scale(screen)
        log("[Timing] scale calibrate done")
        log_run_header(source=source)
        if start_at:
            log(f"[Heli] resuming gifts flow at step={start_at}")

        log("[Timing] reset_ui start")
        reset_ui(clicks=3, delay=1.0)
        log("[Timing] reset_ui done")

        if _step_reached("drone", start_at):
            def _do_drone():
                _heli_checkpoint(source, "drone")
                log_step("Drone", "info", "start")
                drone_status = run_drone_gift_flow(skip_reset=True)
                log(f"[Drone] result: {drone_status}")
                if drone_status.startswith("Collected"):
                    log_step("Drone", "pass", drone_status)
                elif drone_status.startswith("Not ready") or "cooldown" in drone_status.lower() or "OCR" in drone_status:
                    log_step("Drone", "skip", drone_status)
                else:
                    log_step("Drone", "fail", drone_status)

                map_status = ensure_wilderness()
                log_step("Wilderness", "pass", map_status)

            _guarded_step("Drone", _do_drone)

        if _step_reached("battlefield", start_at):
            def _do_battlefield():
                _heli_checkpoint(source, "battlefield")
                battlefield_status = _claim_battlefield_gifts()
                if battlefield_status == "skipped":
                    log_skip("no_battlefield_chest")
                    log_step("Battlefield", "skip", battlefield_status)
                else:
                    log_step("Battlefield", "pass", battlefield_status)

            _guarded_step("Battlefield", _do_battlefield)

        if _step_reached("alliance_gifts", start_at):
            def _do_alliance_gifts():
                _heli_checkpoint(source, "alliance_gifts")
                log_step("Alliance", "info", "opening")
                if not _open_alliance_menu():
                    log_step("Alliance", "fail", "shield_not_found")
                    raise RuntimeError("Alliance menu button not found (HUD shield band)")
                log_step("Alliance", "pass", "menu_open")

                log_step("AllianceGifts", "info", "opening")
                if not _open_alliance_gifts_tile():
                    log_step("AllianceGifts", "fail", "tile_not_found")
                    raise RuntimeError("Alliance Gifts button not found")
                log_step("AllianceGifts", "pass", "modal_open")

                log_step("Common", "info", "claiming")
                common_status = _claim_tab("Common")
                log(f"[Gifts] Common tab complete: {common_status}.")
                if "Claimed All" in common_status:
                    gifts_state = log_gifts_modal_state("after_common_claim_all")
                    if gifts_state != "gifts_modal_open":
                        log(
                            f"[Gifts] WARN: after Common Claim All, expected gifts modal; "
                            f"got state={gifts_state}"
                        )
                        # The single dismiss click after Claim All sometimes
                        # closes the whole Gifts panel, not just the reward
                        # popup (real incident 2026-08-02: state came back
                        # alliance_grid_visible_gifts_likely_closed). Without
                        # this, the Rare tab switch that follows would run
                        # against the plain Alliance grid and silently miss
                        # every Rare gift for the rest of this run. Re-open
                        # from the grid we're confirmed to be looking at.
                        if gifts_state == "alliance_grid_visible_gifts_likely_closed":
                            log("[Gifts] Re-opening Gifts panel before Rare switch...")
                            if _open_alliance_gifts_tile():
                                log("[Gifts] Re-opened Gifts panel successfully.")
                            else:
                                log("[Gifts] WARN: failed to re-open Gifts panel — Rare may be skipped.")
                log_step("Common", "pass", common_status)

                log_step("Rare", "info", "switching")
                if not _switch_to_rare_tab():
                    log("[Gifts] WARN: continuing Rare claim anyway (switch unverified).")
                    log_step("Rare", "fail", "switch_unverified")
                else:
                    log_step("Rare", "pass", "switched")
                log_step("Rare", "info", "claiming")
                rare_status = _claim_tab("Rare")
                log(f"[Gifts] Rare tab complete: {rare_status}.")
                log_step("Rare", "pass", rare_status)

                print("Closing Alliance Gifts window (stay on Alliance)...")
                dismiss_overlay(delay=3.0)

            _guarded_step("AllianceGifts", _do_alliance_gifts)

        if _step_reached("techs", start_at):
            def _do_techs():
                _heli_checkpoint(source, "techs")
                _ensure_alliance_open_for_techs()

                log_step("Techs", "info", "donating")
                techs_status = _donate_alliance_techs()
                log(f"[Techs] Alliance Techs result: {techs_status}")
                if techs_status.startswith("skipped"):
                    log_step("Techs", "skip", techs_status)
                else:
                    log_step("Techs", "pass", techs_status)

                print("Closing Alliance Menu window...")
                dismiss_overlay(delay=3.0)

            _guarded_step("Techs", _do_techs)

        if _step_reached("trucks", start_at):
            def _do_trucks():
                _heli_checkpoint(source, "trucks")
                log_step("Trucks", "info", "start")
                trucks_status = run_trucks_flow()
                log(f"[Trucks] result: {trucks_status}")
                if trucks_status.startswith("skipped"):
                    log_step("Trucks", "skip", trucks_status)
                elif trucks_status.startswith("failed"):
                    log_step("Trucks", "fail", trucks_status)
                else:
                    log_step("Trucks", "pass", trucks_status)

            _guarded_step("Trucks", _do_trucks)

        log_step("Done", "pass", "gifts_collection_complete")
        log("Gifts collection flow complete!")

    except Exception as exc:
        if isinstance(exc, HeliInterrupt):
            log(f"[Heli] interrupting gifts at resume_step={exc.resume_step}")
            raise
        dump_crash(exc, prefix="crash_gifts")
        raise
    finally:
        end_run_stats(print_summary=True)
        end_run_logging()
