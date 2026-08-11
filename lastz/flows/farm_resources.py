"""
HQ Farm Resources Collection.

Collects the six HQ resource-farm building types (food, wood, exp,
electricity, enhancement alloy, zent).

CONFIRMED LIVE 2026-08-11 (precise before/after screenshot comparison, not
speculation): clicking **any single** farm badge — round (still
accumulating) or the teardrop/pin "full" marker, **any** resource type —
collects **every** farm building's production across the **whole base, all
six types at once**. Before: EXP badge "212.7K", 6 food badges, 7 zent
badges all visible with distinct values. ~2.5s after clicking one round EXP
badge (not full, not a pin): every EXP/food/zent badge in view vanished, and
the HUD's food/wood totals jumped (81.2K→251.8K food, 642→165.2K wood).

This means the flow needs to find and click **exactly one** farm badge of
**any** type/state per cycle — nothing more. It does not need to visit every
resource type, does not need to wait for a "full" state, and does not need
a claim loop. (An earlier version of this flow assumed each resource type
needed its own separate full-badge click; that assumption was wrong and has
been removed — see git history / the plan doc for how that was diagnosed.)

Detection still prefers already-validated templates (the three "full" pin
crops captured 2026-08-11, plus a round-state EXP crop that's reliably
visible almost every cycle since EXP produces fast) — more round-state
templates should be added for other types over time purely to raise the
odds of finding *something* to click quickly, not because the type matters.

Used right after Drone in the Alliance Gifts flow (menu 2 watcher) — not a
separate menu item. All pan/zoom points are fractions of the live game
window, never fixed pixels, so a base's layout (which varies per player)
doesn't need calibration.

Logging: every zoom/pan step and every scan result is written via
lastz.runlog.log() so a run's exact behavior is fully reconstructable from
logs/runs.log afterward — this flow is new and under active live
verification, so err on the side of over-logging rather than under-logging.
"""
import time

from lastz.config import farm_resources_cfg, threshold as cfg_threshold
from lastz.flows.base import reset_ui
from lastz.flows.hq_nav import is_hq_mode, navigate_to_hq, navigate_to_wilderness
from lastz.flows.ui_bands import BAND_HQ_MAP
from lastz.input import click, drag, ensure_game_running, focus_game, scroll_wheel
from lastz.runlog import log, log_click, log_skip
from lastz.screen import (
    capture_both,
    physical_to_logical,
    scale_ref_logical_delta,
    window_click,
)
from lastz.vision import MatchWithBBox, cluster_matches, find_all_templates

# label -> (template filename, threshold config key). Any one of these being
# found is sufficient to click and collect everything — more entries just
# raise the odds of finding *something* on a given capture, they are not
# separate things that all need collecting.
_DETECT_TEMPLATES: dict[str, tuple[str, str]] = {
    "exp_round": ("farm_exp_round.png", "farm_exp_round"),
    "exp_full": ("farm_exp_full.png", "farm_exp_full"),
    "food_full": ("farm_food_full.png", "farm_food_full"),
    "zent_full": ("farm_zent_full.png", "farm_zent_full"),
}


def _map_center() -> tuple[float, float]:
    cfg = farm_resources_cfg()
    fx, fy = cfg["map_drag_origin"]
    cx, cy = window_click(fx, fy)
    log(f"[Farm] map_center frac=({fx},{fy}) -> logical=({cx:.1f},{cy:.1f})")
    return cx, cy


def _zoom(steps: int, delta_per_step: float, *, step_delay: float, settle: float, label: str) -> None:
    if steps <= 0:
        log(f"[Farm] zoom({label}) skipped — steps<=0")
        return
    cx, cy = _map_center()
    total_delta = int(delta_per_step * steps)
    log(
        f"[Farm] zoom({label}) steps={steps} delta_per_step={delta_per_step} "
        f"total_delta={total_delta} at=({cx:.0f},{cy:.0f})"
    )
    scroll_wheel(cx, cy, total_delta, steps=steps, step_delay=step_delay)
    time.sleep(settle)
    log(f"[Farm] zoom({label}) done, settled {settle}s")


def _zoom_out(cfg: dict) -> None:
    _zoom(
        cfg["zoom_out_steps"],
        cfg["zoom_delta_per_step"],
        step_delay=cfg["zoom_step_delay_sec"],
        settle=cfg["zoom_settle_sec"],
        label="out",
    )


def _zoom_in(cfg: dict) -> None:
    _zoom(
        cfg["zoom_out_steps"],
        -cfg["zoom_delta_per_step"],
        step_delay=cfg["zoom_step_delay_sec"],
        settle=cfg["zoom_settle_sec"],
        label="in",
    )


def _pan_grid(cfg: dict) -> list[tuple[float, float]]:
    """Reference-resolution pan deltas scaled to the live game window."""
    grid = [scale_ref_logical_delta(dx, dy) for dx, dy in cfg["pan_swipes"]]
    log(f"[Farm] pan_grid (scaled to live window) = {[(round(x,1), round(y,1)) for x, y in grid]}")
    return grid


def _pan_step(x: float, y: float, dx: float, dy: float, settle: float) -> tuple[float, float]:
    nx, ny = x + dx, y + dy
    log(f"[Farm] pan drag ({x:.0f},{y:.0f}) -> ({nx:.0f},{ny:.0f}) delta=({dx:.0f},{dy:.0f})")
    drag(x, y, nx, ny)
    time.sleep(settle)
    return nx, ny


def _recenter(pos: tuple[float, float], walked: list[tuple[float, float]], settle: float) -> None:
    """Reverse only the pan steps actually walked, returning to the start position."""
    log(f"[Farm] recenter: reversing {len(walked)} walked pan step(s) from ({pos[0]:.0f},{pos[1]:.0f})")
    x, y = pos
    for dx, dy in reversed(walked):
        x, y = _pan_step(x, y, -dx, -dy, settle)
    log(f"[Farm] recenter done, back near ({x:.0f},{y:.0f})")


def _hud_exclude_regions(cfg: dict, h: int, w: int) -> list[tuple[int, int, int, int]]:
    """(x1, y1, x2, y2) physical-pixel HUD exclusion rectangles."""
    top = cfg["hud_top_frac"]
    bottom = cfg["hud_bottom_frac"]
    left = cfg["hud_left_frac"]
    right = cfg["hud_right_frac"]
    regions = [
        (0, 0, w, int(h * top)),
        (0, int(h * (1 - bottom)), w, h),
        (0, 0, int(w * left), h),
        (int(w * (1 - right)), 0, w, h),
    ]
    log(f"[Farm] hud_exclude_regions (capture {w}x{h}) = {regions}")
    return regions


def _in_hq_band(m: MatchWithBBox, h: int, w: int) -> bool:
    y0, y1, x0, x1 = BAND_HQ_MAP
    yf = m.phys_y / h
    xf = m.phys_x / w
    return y0 <= yf <= y1 and x0 <= xf <= x1


def _find_any_farm_badge(
    gray,
    excl: list[tuple[int, int, int, int]],
    dedupe_radius: float,
) -> tuple[str, MatchWithBBox] | None:
    """
    Best match across ALL known badge templates (any type, any state) —
    finding any ONE is enough, since clicking it collects everything.
    Returns (label, match) or None if nothing matched at this position.
    """
    h, w = gray.shape[:2]
    best_label: str | None = None
    best: MatchWithBBox | None = None

    for label, (tname, thr_key) in _DETECT_TEMPLATES.items():
        thresh = cfg_threshold(thr_key)
        matches = find_all_templates(gray, tname, thresh, exclude_regions=excl)
        if not matches:
            log(f"[Farm] scan {label}: 0 raw matches (template={tname} thresh={thresh})")
            continue

        raw_n = len(matches)
        in_band = [m for m in matches if _in_hq_band(m, h, w)]
        dropped = raw_n - len(in_band)
        if dropped:
            rejected = [m for m in matches if not _in_hq_band(m, h, w)]
            log(
                f"[Farm] scan {label}: {dropped}/{raw_n} raw match(es) rejected by "
                f"BAND_HQ_MAP — {[(round(m.phys_x),round(m.phys_y),round(m.confidence,3)) for m in rejected]}"
            )
        if not in_band:
            log(f"[Farm] scan {label}: no matches left after band filter")
            continue

        clustered = cluster_matches(in_band, radius_px=dedupe_radius)
        clustered.sort(key=lambda m: m.confidence, reverse=True)
        top = clustered[0]
        log(
            f"[Farm] scan {label}: {raw_n} raw -> {len(in_band)} in-band -> "
            f"{len(clustered)} clustered; best=({top.phys_x:.0f},{top.phys_y:.0f}) "
            f"conf={top.confidence:.4f}"
        )
        if best is None or top.confidence > best.confidence:
            best, best_label = top, label

    if best is None or best_label is None:
        return None
    return best_label, best


def _click_badge(label: str, match: MatchWithBBox, h: int) -> None:
    lx, ly = physical_to_logical(match.phys_x, match.phys_y)
    log(
        f"[Farm] CLICK {label} at logical=({lx:.0f},{ly:.0f}) "
        f"phys=({match.phys_x:.0f},{match.phys_y:.0f}) conf={match.confidence:.4f}"
    )
    log_click(
        f"farm_{label}",
        template=_DETECT_TEMPLATES[label][0],
        conf=match.confidence,
        logical_xy=(lx, ly),
        phys_xy=(match.phys_x, match.phys_y),
        y_frac=match.phys_y / h,
    )
    click(lx, ly)


def _click_and_verify(
    label: str,
    match: MatchWithBBox,
    h: int,
    excl: list[tuple[int, int, int, int]],
    cfg: dict,
    *,
    max_attempts: int = 3,
) -> bool:
    """
    Click the matched badge, then confirm it's actually gone before trusting
    the result.

    Live-verified 2026-08-11 that a synthetic click can silently fail to
    register in the game (no error, no exception — the badge just sits there
    unchanged) even when the coordinate is correct: a zent_full badge near
    the top HUD boundary (y_frac~0.10) was clicked repeatedly across several
    real runs and never actually collected, while clicking a *different*
    badge elsewhere on the same screen worked immediately and collected the
    stuck zent one too as a side effect (proving the mechanic itself — one
    click collects everything — is real; the earlier failure was purely a
    missed click). Retrying the same click a couple of times resolves this
    kind of transient miss; if it's still there after max_attempts, this
    match is abandoned for this cycle rather than falsely reported as a
    success.
    """
    tname, thr_key = _DETECT_TEMPLATES[label]
    thresh = cfg_threshold(thr_key)
    dedupe_radius = cfg["dedupe_radius_px"]

    for attempt in range(1, max_attempts + 1):
        _click_badge(label, match, h)
        time.sleep(cfg["post_click_settle_sec"])

        _, gray = capture_both()
        recheck = find_all_templates(gray, tname, thresh, exclude_regions=excl)
        still_there = any(
            abs(m.phys_x - match.phys_x) < dedupe_radius and abs(m.phys_y - match.phys_y) < dedupe_radius
            for m in recheck
        )
        if not still_there:
            log(f"[Farm] verified {label} click worked (attempt {attempt}/{max_attempts})")
            return True
        log(
            f"[Farm] {label} still present at ~same spot after click "
            f"(attempt {attempt}/{max_attempts}) — click may not have registered"
        )

    log(f"[Farm] {label} click did not verify after {max_attempts} attempts — abandoning this match")
    return False


def _find_and_collect() -> str | None:
    """
    Zoom out, walk a "plus" pan grid (center + cardinal directions) around
    the HQ map, and click the FIRST farm badge found (any type, any state).

    One click collects every building's production across the whole base —
    confirmed live, see module docstring — so the sweep stops at the first
    hit rather than visiting every position or every resource type. Always
    restores the camera to its starting position and zoom level.

    Returns the label of what was clicked (e.g. "exp_round"), or None if
    nothing was found anywhere in the sweep.
    """
    cfg = farm_resources_cfg()
    log(
        f"[Farm] sweep start: templates={list(_DETECT_TEMPLATES)} "
        f"zoom_out_steps={cfg['zoom_out_steps']} pan_swipes={cfg['pan_swipes']} "
        f"dedupe_radius_px={cfg['dedupe_radius_px']}"
    )

    start = _map_center()
    _zoom_out(cfg)

    pan_grid = _pan_grid(cfg)
    positions = [(0.0, 0.0)] + pan_grid  # center first, then each cardinal pan
    pos = start
    walked: list[tuple[float, float]] = []
    found_label: str | None = None

    try:
        for i, (dx, dy) in enumerate(positions):
            label = "center" if i == 0 else f"pan#{i}"
            if i > 0:
                pos = _pan_step(pos[0], pos[1], dx, dy, cfg["pan_settle_sec"])
                walked.append((dx, dy))
            log(f"[Farm] sweep position {label}: at=({pos[0]:.0f},{pos[1]:.0f})")

            _, gray = capture_both()
            h, w = gray.shape[:2]
            excl = _hud_exclude_regions(cfg, h, w)

            hit = _find_any_farm_badge(gray, excl, cfg["dedupe_radius_px"])
            if hit is None:
                continue

            candidate_label, match = hit
            ok = _click_and_verify(candidate_label, match, h, excl, cfg)
            if not ok:
                # Click didn't verify — don't report false success. Keep
                # scanning (this position or the next) rather than giving up
                # on the whole cycle over one bad click.
                continue
            found_label = candidate_label
            log(f"[Farm] collected via {found_label} at position {label} — stopping sweep")
            break
    finally:
        _recenter(pos, walked, cfg["pan_settle_sec"])
        _zoom_in(cfg)

    log(f"[Farm] sweep end: found_label={found_label}")
    return found_label


def run_farm_resources_flow(*, skip_reset: bool = False) -> str:
    """
    Scan the HQ base for any farm resource badge and collect it.

    One click collects every farm building's production across the whole
    base (confirmed live — see module docstring), so at most one click
    happens per cycle. Always leaves the game on wilderness when finished
    (or skipped after an HQ visit). Pass skip_reset=True when the parent
    flow already called reset_ui.
    """
    cfg = farm_resources_cfg()
    log(f"[Farm] run_farm_resources_flow start (skip_reset={skip_reset}) cfg={cfg}")
    if not cfg["enabled"]:
        log("[Farm] disabled in config — skipping")
        log_skip("farm_resources_disabled")
        return "Skipped (disabled in config)"

    ensure_game_running()
    focus_game()
    if not skip_reset:
        reset_ui(clicks=2, delay=1.0)

    _, screen = capture_both()
    started_in_wilderness = not is_hq_mode(screen)
    entered_hq = False
    log(f"[Farm] started_in_wilderness={started_in_wilderness}")

    try:
        if started_in_wilderness:
            log("[Farm] not in HQ mode — attempting to navigate to Headquarters")
            if not navigate_to_hq(screen):
                log("[Farm] navigate_to_hq FAILED — headquarters button not found")
                log_skip("hq_nav_failed", detail="headquarters_button_not_found")
                return "Skipped — Headquarters button not found"
            _, screen = capture_both()
            if not is_hq_mode(screen):
                log("[Farm] still not in HQ mode after navigation attempt")
                log_skip("hq_nav_failed", detail="still_not_hq")
                return "Skipped — navigation failed, still not HQ mode"
            log("[Farm] now in HQ mode")
        entered_hq = True

        found_label = _find_and_collect()
        log(f"[Farm] final: found_label={found_label}")

        if found_label:
            print(f"-> Collected farm resources (via {found_label}).")
            return f"Collected: {found_label}"

        print("-> No farm badges found this cycle.")
        log_skip("no_badges_found")
        return "Skipped — no farm badges found"

    finally:
        log(f"[Farm] finally: entered_hq={entered_hq} — restoring wilderness if needed")
        if entered_hq:
            navigate_to_wilderness()
        log("[Farm] run_farm_resources_flow end")
