"""
Gifts collection flow — HQ Drone + Battlefield + Alliance Gifts + Alliance Techs.

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
from lastz.flows.ui_bands import (
    BAND_ALLIANCE_GRID,
    BAND_HUD_SHIELD,
    BAND_RARE_TAB,
    BAND_TECH_TREE,
    CLAIM_MAX_Y_FRAC,
)
from lastz.input import click, ensure_game_running, focus_game
from lastz.runlog import (
    dump_crash,
    log,
    log_click,
    log_gifts_modal_state,
    log_run_header,
    log_skip,
    log_step,
)
from lastz.screen import capture, capture_both, physical_to_logical
from lastz.vision import MatchWithBBox, click_template, find_all_templates, find_any, find_template

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


def _try_claim_all() -> str | None:
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
    time.sleep(2.0)
    # Exactly one outside click: closes the reward popup, leaves Gifts open.
    # A second outside click (e.g. before Rare) closes Gifts itself — do not add one.
    print("[Gifts] Dismissing reward popup (single outside click)...")
    dismiss_overlay(delay=1.2)
    return "Claimed All (Instant)"


def _claim_tab(tab_name: str) -> str:
    print(f"[Gifts] Claiming on {tab_name} tab...")
    claim_all_status = _try_claim_all()
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

    screen_modal = capture()
    claim_match = find_template(
        screen_modal,
        "universal_claim_all_button.png",
        cfg_threshold("claim_all"),
    )
    if claim_match is not None:
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


def _open_alliance_techs() -> bool:
    """Open Techs via microscope in grid band; label only as in-band fallback."""
    techs_thr = cfg_threshold("alliance_techs")
    print(f"[Techs] Looking for Alliance Techs in grid band (threshold={techs_thr})...")
    color, gray = capture_both()
    h, w = gray.shape[:2]

    # Prefer microscope icon
    icon_matches = find_all_templates(gray, "alliance_techs.png", techs_thr)
    icon_in = [m for m in icon_matches if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
    pick = None
    tag = ""
    if icon_in:
        icon_in.sort(key=lambda m: m.confidence, reverse=True)
        pick, tag = icon_in[0], "microscope"
    else:
        # Soften icon threshold slightly only inside band via lower thr search
        soft = find_all_templates(gray, "alliance_techs.png", max(0.55, techs_thr - 0.1))
        soft_in = [m for m in soft if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
        if soft_in:
            soft_in.sort(key=lambda m: m.confidence, reverse=True)
            pick, tag = soft_in[0], "microscope-soft"
        else:
            label_matches = find_all_templates(gray, "alliance_techs_label.png", techs_thr)
            label_in = [m for m in label_matches if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
            if label_in:
                label_in.sort(key=lambda m: m.confidence, reverse=True)
                pick, tag = label_in[0], "label"

    if pick is None:
        print("[Techs] FAIL: no Alliance Techs match in alliance grid band.")
        annotate_and_save(color, "techs_miss", [], subdir="flow")
        return False

    lx, ly = physical_to_logical(pick.phys_x, pick.phys_y)
    print(
        f"[Techs] Clicking Alliance Techs ({tag}) at logical ({lx:.1f}, {ly:.1f}) "
        f"[conf={pick.confidence:.4f}]"
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
    print("[Techs] Dismissing tech detail modal...")
    dismiss_overlay(delay=1.5)
    print("[Techs] Dismissing Alliance Techs screen...")
    dismiss_overlay(delay=1.5)
    return f"donated {donated}"


def run_alliance_gifts_flow(*, source: str = "menu") -> None:
    ensure_game_running()
    focus_game()

    try:
        # Capture once so run header can include capture size + scale.
        capture()
        log_run_header(source=source)

        print("Resetting game UI to main base screen...")
        reset_ui(clicks=3, delay=1.5)

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

        battlefield_status = _claim_battlefield_gifts()
        if battlefield_status == "skipped":
            log_skip("no_battlefield_chest")
            log_step("Battlefield", "skip", battlefield_status)
        else:
            log_step("Battlefield", "pass", battlefield_status)

        log_step("Alliance", "info", "opening")
        color, gray = capture_both()
        h, w = gray.shape[:2]
        shields = find_all_templates(
            gray, "alliance_shield_clean.png", cfg_threshold("alliance_shield")
        )
        hud = [m for m in shields if _band_ok(m, h, w, BAND_HUD_SHIELD)]
        if not hud:
            log_step("Alliance", "fail", "shield_not_found")
            raise RuntimeError("Alliance menu button not found (HUD shield band)")
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
        log_step("Alliance", "pass", "menu_open")

        log_step("AllianceGifts", "info", "opening")
        color, gray = capture_both()
        h, w = gray.shape[:2]
        gifts = find_all_templates(
            gray, "alliance_gifts_precise.png", cfg_threshold("alliance_gifts")
        )
        gifts_in = [m for m in gifts if _band_ok(m, h, w, BAND_ALLIANCE_GRID)]
        if not gifts_in:
            log_step("AllianceGifts", "fail", "tile_not_found")
            raise RuntimeError("Alliance Gifts button not found")
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

        log_step("Done", "pass", "gifts_collection_complete")
        print("Gifts collection flow complete!")

    except Exception as exc:
        dump_crash(exc, prefix="crash_gifts")
        raise
