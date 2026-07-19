"""
HQ Drone Gift (Area Exploration Idle Reward).

Collects the idle reward only when Exploration Duration reaches
drone_gift.min_duration (default 08:00:00).

Used at the start of the Alliance Gifts flow (menu 1 / watcher) — not a
separate menu item. Clicks use template centers; timer crops use
scale_capture_rect for screen-size independence.
"""
import time

from lastz.config import load_config, threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.flows.hq_nav import is_hq_mode, navigate_to_hq, navigate_to_wilderness
from lastz.input import click, ensure_game_running, focus_game
from lastz.ocr import format_duration, parse_duration, read_duration_from_region
from lastz.screen import capture, capture_both, physical_to_logical, scale_capture_rect
from lastz.vision import Match, find_template

_MIN_DURATION_SEC = 8 * 3600
_CLAIM_TEMPLATES = ("drone_claim_btn.png", "claim_button_clean.png")
_COLLECT_TEMPLATES = ("drone_collect_btn.png",)


def _min_duration() -> int:
    cfg = load_config().get("drone_gift") or {}
    raw = cfg.get("min_duration", "08:00:00")
    parsed = parse_duration(str(raw))
    return parsed if parsed is not None else _MIN_DURATION_SEC


def _timer_crop_offset() -> list[int]:
    cfg = load_config().get("drone_gift") or {}
    raw = cfg.get("timer_crop_offset", [-77, 8, 150, 28])
    return scale_capture_rect(list(raw))


def _modal_timer_region() -> list[int]:
    cfg = load_config().get("drone_gift") or {}
    raw = cfg.get("modal_timer_region", [1200, 730, 1200, 130])
    return scale_capture_rect(list(raw))


def _find_chest(screen) -> Match | None:
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
) -> Match | None:
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
) -> Match | None:
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


def _read_chest_timer(color, gray, offset: list[int]):
    chest = _find_chest(gray)
    if chest is None:
        return None, None
    tx = int(chest.phys_x + offset[0])
    ty = int(chest.phys_y + offset[1])
    tw, th = int(offset[2]), int(offset[3])
    sec = read_duration_from_region(color, tx, ty, tw, th)
    return sec, chest


def _gate_timer_reads(
    min_sec: int, *, attempts: int = 3
) -> tuple[bool, Match | None, list[int], str]:
    """
    Multiple timer reads across captures.

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
            print(
                f"-> Timer read {i + 1}/{attempts}: {format_duration(sec)} "
                "(implausible, ignored)"
            )
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
        return (
            False,
            chest_match,
            readings,
            f"only 1/{attempts} reads >= threshold (best={format_duration(good[0])})",
        )

    return False, chest_match, readings, "OCR unreadable"


def run_drone_gift_flow(*, skip_reset: bool = False) -> str:
    """
    Collect HQ drone gift if timer >= min_duration.

    Always leaves the game on wilderness when finished (or skipped after HQ visit).
    Pass skip_reset=True when the parent flow already called reset_ui.
    """
    ensure_game_running()
    focus_game()
    if not skip_reset:
        reset_ui(clicks=2, delay=1.0)

    _, screen = capture_both()
    started_in_wilderness = not is_hq_mode(screen)
    entered_hq = False

    try:
        if started_in_wilderness:
            print("-> Not in HQ mode — attempting to navigate to Headquarters...")
            if not navigate_to_hq(screen):
                return "Not in HQ mode — Headquarters button not found"
            _, screen = capture_both()
            if not is_hq_mode(screen):
                print("-> Still not in HQ mode after navigation attempt.")
                return "Navigation failed — still not HQ mode"
            print("-> Now in HQ mode.")
        entered_hq = True

        min_sec = _min_duration()

        ready, chest_match, _readings, detail = _gate_timer_reads(min_sec)
        if chest_match is None:
            print("-> Gift chest not visible on screen (cooldown or not available).")
            return "No chest visible (cooldown)"
        if not ready:
            if detail == "OCR unreadable":
                print(
                    "-> OCR could not read timer reliably. Skipping to avoid early collection."
                )
                return "OCR unavailable — skipping"
            print(f"-> Timer not confirmed >= {format_duration(min_sec)} ({detail}).")
            return f"Not ready ({detail})"

        duration_str = detail
        print(
            f"-> Confirmed {duration_str} >= {format_duration(min_sec)} — proceeding to collect."
        )

        _, fresh_gray = capture_both()
        fresh_chest = _find_chest(fresh_gray)
        if fresh_chest is not None:
            chest_match = fresh_chest

        lx, ly = physical_to_logical(chest_match.phys_x, chest_match.phys_y)
        print(f"-> Clicking chest badge at logical ({lx:.1f}, {ly:.1f})...")
        click(lx, ly)
        time.sleep(2.0)

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
            screen_check = capture()
            collect_direct = _find_button(
                screen_check, list(_COLLECT_TEMPLATES), collect_thresh
            )
            if collect_direct is None:
                print("-> Claim button not found in Area Exploration. Closing and skipping.")
                dismiss_overlay(delay=1.5)
                return "Claim button not found"
            print("-> Idle Reward modal opened directly (no Claim step).")

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

        dismiss_overlay(delay=1.5)
        dismiss_overlay(delay=1.5)

        print(f"-> Drone Gift collected! Duration was {duration_str}.")
        return f"Collected ({duration_str})"

    finally:
        if entered_hq:
            navigate_to_wilderness()
