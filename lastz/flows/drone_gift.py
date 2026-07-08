"""
Flow 4 — HQ Drone Gift (Area Exploration Idle Reward).

Collects the idle reward that accumulates while the car drives down the
exploration road.  The reward is only worth collecting once the Exploration
Duration reaches 08:00:00 (configurable in config.yaml as drone_gift.min_duration).

Steps:
  0. Ensure game is running; focus window
  1. Confirm HQ mode by matching the World globe button (bottom-right corner)
  2. Template-match the golden gift chest badge on the HQ base
     → If not visible: chest is in cooldown (~15 min after collect) — skip
  3. OCR the timer below the chest badge
     → If timer < min_duration: not ready — skip
  4. Click the chest badge → Area Exploration screen opens
  5. Match green Claim button → click
  6. Idle Reward modal appears; OCR Exploration Duration as a safety check
     → If duration < min_duration despite step 3: do not collect
  7. Match green Collect button → click
  8. Dismiss back to HQ base

Returns a human-readable status string (used by watcher for logging):
  "Collected (08:02:15)"
  "Not ready (02:48:20)"
  "No chest visible (cooldown)"
  "Not in HQ mode"
  "OCR unavailable — skipping"
"""
import time

from lastz.config import load_config, threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.flows.hq_nav import is_hq_mode, navigate_to_hq, navigate_to_wilderness
from lastz.input import click, ensure_game_running, focus_game
from lastz.ocr import format_duration, parse_duration, read_duration_from_region
from lastz.screen import capture, capture_both, physical_to_logical, scale_capture_rect
from lastz.vision import find_template

_MIN_DURATION_SEC = 8 * 3600  # 28800 — default, overridden by config


def _min_duration() -> int:
    cfg = load_config().get("drone_gift", {})
    raw = cfg.get("min_duration", "08:00:00")
    parsed = parse_duration(raw)
    return parsed if parsed is not None else _MIN_DURATION_SEC


def _timer_crop_offset() -> list[int]:
    cfg = load_config().get("drone_gift", {})
    raw = cfg.get("timer_crop_offset", [-40, -15, 95, 22])
    return scale_capture_rect(raw)


def _modal_timer_region() -> list[int]:
    cfg = load_config().get("drone_gift", {})
    raw = cfg.get("modal_timer_region", [800, 262, 410, 44])
    return scale_capture_rect(raw)


def _find_chest(screen) -> "Match | None":
    """Find the gift chest badge, stepping down threshold if needed."""
    primary = cfg_threshold("drone_gift_chest")
    for thresh in (primary, max(0.48, primary - 0.08), 0.48):
        match = find_template(screen, "hq_drone_gift_chest.png", thresh)
        if match is not None:
            return match
    return None


def _find_button(
    screen,
    template_names: list[str],
    primary_threshold: float,
    *,
    floor: float = 0.50,
) -> "Match | None":
    """Match a UI button, trying several templates with stepped thresholds."""
    steps = (
        primary_threshold,
        max(floor, primary_threshold - 0.10),
        max(floor, primary_threshold - 0.18),
        floor,
    )
    seen: set[tuple[float, str]] = set()
    for name in template_names:
        for thresh in steps:
            key = (thresh, name)
            if key in seen:
                continue
            seen.add(key)
            match = find_template(screen, name, thresh)
            if match is not None:
                return match
    return None


def _wait_for_button(
    template_names: list[str],
    primary_threshold: float,
    *,
    timeout_sec: float = 8.0,
    poll_sec: float = 0.75,
    label: str = "button",
) -> "Match | None":
    """Poll until a button appears or timeout."""
    deadline = time.time() + timeout_sec
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        screen = capture()
        match = _find_button(screen, template_names, primary_threshold)
        if match is not None:
            print(f"-> Found {label} on attempt {attempt} (conf={match.confidence:.4f}).")
            return match
        print(f"-> {label.title()} not visible yet (attempt {attempt})...")
        time.sleep(poll_sec)
    return None


_CLAIM_TEMPLATES = ("drone_claim_btn.png", "claim_button_clean.png")
_COLLECT_TEMPLATES = ("drone_collect_btn.png",)


def _read_chest_timer(color, gray, offset: list[int]):
    """Return (seconds, chest_match) from one frame, or (None, None) if unavailable."""
    chest = _find_chest(gray)
    if chest is None:
        return None, None
    tx = int(chest.phys_x + offset[0])
    ty = int(chest.phys_y + offset[1])
    tw, th = int(offset[2]), int(offset[3])
    sec = read_duration_from_region(color, tx, ty, tw, th)
    return sec, chest


def _gate_timer_reads(min_sec: int, *, attempts: int = 3) -> tuple[bool, "Match | None", list[int], str]:
    """
    Take multiple timer readings across separate captures.

    Returns (ready, chest_match, good_readings, status_detail).
    Collect only when at least 2 readings are >= min_sec (guards flaky OCR).
    """
    offset = _timer_crop_offset()
    readings: list[int] = []
    chest_match = None

    for i in range(attempts):
        if i > 0:
            time.sleep(1.0)
        color, gray = capture_both()
        sec, chest = _read_chest_timer(color, gray, offset)
        if chest is not None:
            chest_match = chest
        if sec is None:
            print(f"-> Timer read {i + 1}/{attempts}: OCR failed")
            continue
        if sec > 8 * 3600:
            print(f"-> Timer read {i + 1}/{attempts}: {format_duration(sec)} (implausible, ignored)")
            continue
        readings.append(sec)
        print(f"-> Timer read {i + 1}/{attempts}: {format_duration(sec)}")

    if chest_match is None:
        return False, None, readings, "no chest visible"

    good = [s for s in readings if s >= min_sec]
    if len(good) >= 2:
        return True, chest_match, good, format_duration(good[-1])

    if readings and max(readings) < min_sec:
        return False, chest_match, readings, format_duration(max(readings))

    if len(good) == 1:
        return False, chest_match, readings, f"only 1/{attempts} reads >= threshold (best={format_duration(good[0])})"

    return False, chest_match, readings, "OCR unreadable"


# Keep internal aliases for backward compatibility (used in run_drone_gift_flow below)
_is_hq_mode = is_hq_mode
_navigate_to_hq = navigate_to_hq
_navigate_to_wilderness = navigate_to_wilderness


def run_drone_gift_flow() -> str:
    ensure_game_running()
    focus_game()
    reset_ui(clicks=2, delay=1.0)

    # Step 1 — confirm HQ mode; navigate there if in wilderness.
    screen_color, screen = capture_both()
    started_in_wilderness = not _is_hq_mode(screen)

    if started_in_wilderness:
        print("-> Not in HQ mode — attempting to navigate to Headquarters...")
        if not _navigate_to_hq(screen):
            return "Not in HQ mode — Headquarters button not found"
        screen_color, screen = capture_both()
        if not _is_hq_mode(screen):
            print("-> Still not in HQ mode after navigation attempt.")
            return "Navigation failed — still not HQ mode"
        print("-> Now in HQ mode.")

    try:
        min_sec = _min_duration()

        # Step 2+3 — find chest and gate on 2-of-3 OCR reads >= min_duration.
        ready, chest_match, _readings, detail = _gate_timer_reads(min_sec)
        if chest_match is None:
            print("-> Gift chest not visible on screen (cooldown or not available).")
            return "No chest visible (cooldown)"
        if not ready:
            if detail == "OCR unreadable":
                print("-> OCR could not read timer reliably. Skipping to avoid early collection.")
                return "OCR unavailable — skipping"
            print(f"-> Timer not confirmed >= {format_duration(min_sec)} ({detail}).")
            return f"Not ready ({detail})"

        duration_str = detail
        print(f"-> Confirmed {duration_str} >= {format_duration(min_sec)} — proceeding to collect.")

        # Re-find chest on a fresh frame before clicking (position may shift slightly).
        _, fresh_gray = capture_both()
        fresh_chest = _find_chest(fresh_gray)
        if fresh_chest is not None:
            chest_match = fresh_chest

        # Step 4 — click chest badge to open Area Exploration
        lx, ly = physical_to_logical(chest_match.phys_x, chest_match.phys_y)
        print(f"-> Clicking chest badge at logical ({lx:.1f}, {ly:.1f})...")
        click(lx, ly)
        time.sleep(2.0)

        # Step 5 — wait for Claim (Area Exploration) or Collect (modal opened directly)
        claim_thresh = cfg_threshold("drone_claim_btn")
        collect_thresh = cfg_threshold("drone_collect_btn")

        claim_match = _wait_for_button(
            list(_CLAIM_TEMPLATES), claim_thresh, timeout_sec=8.0, label="claim button"
        )
        if claim_match is not None:
            clx, cly = physical_to_logical(claim_match.phys_x, claim_match.phys_y)
            print(f"-> Clicking Claim at logical ({clx:.1f}, {cly:.1f})...")
            click(clx, cly)
            time.sleep(2.0)
        else:
            # Chest may open the Idle Reward modal directly — look for Collect.
            screen_check = capture()
            collect_direct = _find_button(
                screen_check, list(_COLLECT_TEMPLATES), collect_thresh
            )
            if collect_direct is None:
                print("-> Claim button not found in Area Exploration. Closing and skipping.")
                dismiss_overlay(delay=1.5)
                return "Claim button not found"
            print("-> Idle Reward modal opened directly (no Claim step).")

        # Step 6 — Idle Reward modal: OCR as optional confirmation only
        screen3 = capture()
        region = _modal_timer_region()
        modal_duration = read_duration_from_region(
            screen3, region[0], region[1], region[2], region[3]
        )

        if modal_duration is not None and modal_duration < min_sec:
            modal_str = format_duration(modal_duration)
            print(f"-> Modal timer {modal_str} is below threshold. Closing without collecting.")
            dismiss_overlay(delay=1.5)
            dismiss_overlay(delay=1.5)
            return f"Not ready — modal confirms ({modal_str})"

        # Step 7 — click Collect (poll — modal may animate in)
        collect_match = _wait_for_button(
            list(_COLLECT_TEMPLATES), collect_thresh, timeout_sec=6.0, label="collect button"
        )
        if collect_match is None:
            print("-> Collect button not found in Idle Reward modal. Closing.")
            dismiss_overlay(delay=1.5)
            dismiss_overlay(delay=1.5)
            return "Collect button not found"

        colx, coly = physical_to_logical(collect_match.phys_x, collect_match.phys_y)
        print(f"-> Clicking Collect at logical ({colx:.1f}, {coly:.1f})...")
        click(colx, coly)
        time.sleep(2.0)

        # Step 8 — dismiss any reward overlay and close back to HQ base
        dismiss_overlay(delay=1.5)   # dismiss reward animation
        dismiss_overlay(delay=1.5)   # close Area Exploration panel

        print(f"-> Drone Gift collected! Duration was {duration_str}.")
        return f"Collected ({duration_str})"

    finally:
        # Always restore wilderness mode if we navigated away from it.
        if started_in_wilderness:
            _navigate_to_wilderness()
