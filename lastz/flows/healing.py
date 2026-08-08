"""
Healing flow — heal wounded troops in batches.

Runs in parallel with Help watcher (menu 4), prioritized.
Checks for healing icons in left-bottom HUD area, heals in configurable
batches (default 50 total troops), asks alliance help, and collects when done.
"""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from lastz.config import healing_cfg, logs_dir, templates_dir, threshold as cfg_threshold
from lastz.input import click, press_escape, rapid_click
from lastz.ocr import digit_templates_available, read_stepper_number
from lastz.screen import (
    capture,
    capture_region,
    game_window_band_logical,
    game_window_band_phys,
    physical_to_logical,
)
from lastz.vision import MatchWithBBox, ensure_template_scale, find_all_templates, find_template_local

# _zero_out_stepper: initial decrement burst covers the common case (observed
# leftover values sit close to batch_size, e.g. 50-51) without ever guessing;
# followed by up to _ZERO_VERIFY_ROUNDS OCR-verified top-up rounds.
_ZERO_MARGIN = 20
_ZERO_ROUND_CLICKS = 80
_ZERO_VERIFY_ROUNDS = 3
_SET_VERIFY_ROUNDS = 3


def _log_path() -> Path:
    p = logs_dir() / "healing.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(_log_path(), "a") as f:
        f.write(line + "\n")


def _find_healing_icon(icon_name: str, band: list[float], thr: float, debug: bool = False) -> tuple[float, float] | None:
    """
    Search for healing icon in the specified band.

    Returns (logical_x, logical_y) if found, None otherwise.
    Uses region capture with fallback to full capture + crop.
    """
    if debug:
        log(f"Searching for '{icon_name}' in band {band} (threshold={thr:.2f})")

    try:
        lx, ly, lw, lh = game_window_band_logical(band)
        region = capture_region(lx, ly, lw, lh)
        match = find_template_local(region, icon_name, thr)
        if match is not None:
            ih, iw = region.shape[:2]
            click_x = lx + (match.phys_x / max(iw, 1)) * lw
            click_y = ly + (match.phys_y / max(ih, 1)) * lh
            if debug:
                log(f"  Found '{icon_name}' conf={match.confidence:.4f} at ({click_x:.0f}, {click_y:.0f})")
            return (click_x, click_y)
        if debug:
            log(f"  '{icon_name}' not found (region capture)")
        return None
    except Exception as region_err:
        # Fallback: full capture + crop
        try:
            if debug:
                log(f"  Region capture failed: {region_err}, trying full+crop")
            screen = capture()
            ensure_template_scale(screen)
            ox, oy, rw, rh = game_window_band_phys(band)
            crop = screen[oy : oy + rh, ox : ox + rw]
            if crop.size == 0:
                if debug:
                    log(f"  Empty crop, aborting")
                return None
            match = find_template_local(
                crop, icon_name, thr, origin_x=ox, origin_y=oy
            )
            if match is None:
                if debug:
                    log(f"  '{icon_name}' not found (full+crop)")
                return None
            pos = physical_to_logical(match.phys_x, match.phys_y)
            if debug:
                log(f"  Found '{icon_name}' conf={match.confidence:.4f} at ({pos[0]:.0f}, {pos[1]:.0f})")
            return pos
        except Exception as full_err:
            if debug:
                log(f"  Full+crop also failed: {full_err}")
            return None


def _number_field_crop(plus: MatchWithBBox) -> tuple[int, int, int, int]:
    """
    The quantity number sits immediately right of the "+" button (modal
    layout, left to right: [-] [slider] [+] [number]). Expressed relative
    to the "+" match's own box (not fixed pixels) so it scales with
    whatever size the template matched at.
    """
    num_x = int(plus.phys_x + plus.phys_w / 2 + plus.phys_w * 0.15)
    num_w = int(plus.phys_w * 1.6)
    num_y = int(plus.phys_y - plus.phys_h / 2)
    num_h = int(plus.phys_h)
    return num_x, num_y, num_w, num_h


def _read_stepper_value(plus: MatchWithBBox) -> int | None:
    screen = capture()
    ensure_template_scale(screen)
    x, y, w, h = _number_field_crop(plus)
    value = read_stepper_number(screen, x, y, w, h)
    if value is None:
        _dump_stepper_crop(screen, x, y, w, h)
    return value


def _dump_stepper_crop(screen, x: int, y: int, w: int, h: int) -> None:
    """
    Save the exact crop OCR failed to read, for later inspection - a live
    run (2026-08-09) saw the final "set to batch_size" OCR read fail 3
    cycles in a row with no visual evidence saved to explain why (a banner/
    overlay over the modal? a count-up animation not yet settled?).
    """
    try:
        import cv2

        h_screen, w_screen = screen.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w_screen, x + w), min(h_screen, y + h)
        crop = screen[y0:y1, x0:x1]
        if crop.size == 0:
            return
        out_dir = logs_dir() / "debug"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        cv2.imwrite(str(out_dir / f"healing_stepper_ocr_fail_{ts}.png"), crop)
    except Exception as exc:
        log(f"[Healing] WARN: could not save stepper OCR-fail debug crop: {exc}")


def _zero_out_stepper(mx: float, my: float, plus: MatchWithBBox, batch_size: int) -> bool:
    """
    Decrement the "-" stepper to exactly 0, OCR-verifying rather than
    trusting a blind click count. A fixed click count can't guarantee 0 if
    the field's leftover value is larger than assumed (troop counts well
    into the hundreds are common) - silently healing more than batch_size.
    Returns False (caller must abort, never guess) if the digit templates
    are unavailable or the field never verifies at 0 within the retry budget.
    """
    if not digit_templates_available():
        log("[Healing] ERROR: digit templates unavailable — cannot verify batch size, aborting")
        return False

    # Initial burst: observed leftover values sit close to batch_size
    # (e.g. 50-51), so this covers the common case in one shot; the
    # verify-and-retry loop below handles anything larger.
    rapid_click(mx, my, count=batch_size + _ZERO_MARGIN, interval=0.02)
    time.sleep(0.3)

    for round_i in range(_ZERO_VERIFY_ROUNDS):
        value = _read_stepper_value(plus)
        if value == 0:
            log(f"[Healing] Verified batch quantity at 0 after round {round_i}")
            return True
        log(f"[Healing] Stepper read {value!r} after round {round_i}, retrying decrement")
        rapid_click(mx, my, count=_ZERO_ROUND_CLICKS, interval=0.02)
        time.sleep(0.3)

    log("[Healing] ERROR: Could not verify batch quantity reached 0, aborting")
    return False


def _set_to_target_verified(px: float, py: float, plus: MatchWithBBox, batch_size: int) -> bool:
    """
    Click "+" batch_size times, then OCR-verify the field actually landed on
    batch_size - rapid_click's fast burst can drop clicks under load (a real
    gap found live: an initial burst of exactly `batch_size` clicks landed
    on batch_size - 3, not batch_size). Tops up the shortfall and re-verifies
    rather than trusting the click count.

    The topmost row can have FEWER wounded troops than the configured
    batch_size (real incident, 2026-08-09: Destroyer row down to 12 wounded
    while Charge Knight/Mercenary below still had hundreds) - the game caps
    "+" at the row's own wounded count, so demanding exactly batch_size is
    an unreachable target and would loop here forever. If a top-up click
    burst doesn't move the read value at all, that's the row's real cap;
    accept it (heal what's actually available) rather than keep retrying
    an impossible number. Still aborts (never guesses) if it overshoots or
    the value can't be read at all within the retry budget.
    """
    rapid_click(px, py, count=batch_size, interval=0.02)
    time.sleep(0.3)

    prev_value: int | None = None
    for round_i in range(_SET_VERIFY_ROUNDS):
        value = _read_stepper_value(plus)
        if value == batch_size:
            log(f"[Healing] Verified batch quantity at {batch_size} after round {round_i}")
            return True
        if value is None:
            log(f"[Healing] WARN: could not OCR-read batch quantity (round {round_i}), retrying read")
            time.sleep(0.3)
            continue
        if value > batch_size:
            log(f"[Healing] ERROR: batch quantity {value} overshot target {batch_size}, aborting")
            return False
        if value == prev_value:
            log(
                f"[Healing] Row capped at {value} (< configured batch_size {batch_size}) "
                f"- healing {value} instead of looping on an unreachable target"
            )
            return True
        missing = batch_size - value
        log(f"[Healing] Batch quantity at {value}, topping up {missing} (round {round_i})")
        rapid_click(px, py, count=missing, interval=0.02)
        time.sleep(0.3)
        prev_value = value

    log(f"[Healing] ERROR: Could not verify batch quantity reached {batch_size}, aborting")
    return False


def _set_batch_size(batch_size: int) -> bool:
    """
    Set the quantity stepper on the topmost troop row in the open Hospital
    modal to exactly `batch_size`, using the +/- buttons (the field itself
    is not a native text input, so typing/paste doesn't work).
    """
    try:
        screen = capture()
        ensure_template_scale(screen)
        thr_minus = cfg_threshold("healing_minus_button")
        thr_plus = cfg_threshold("healing_plus_button")

        minus_matches = find_all_templates(screen, "healing_minus_button.png", thr_minus)
        plus_matches = find_all_templates(screen, "healing_plus_button.png", thr_plus)
        if not minus_matches or not plus_matches:
            log("[Healing] ERROR: Could not find +/- steppers in modal")
            return False

        # Topmost row = first troop type listed.
        minus = min(minus_matches, key=lambda m: m.phys_y)
        plus = min(plus_matches, key=lambda m: m.phys_y)

        mx, my = physical_to_logical(minus.phys_x, minus.phys_y)
        px, py = physical_to_logical(plus.phys_x, plus.phys_y)

        # The game retains the field's last value across modal opens (we've
        # repeatedly seen it reopen already showing the previous batch_size),
        # so zeroing-and-resetting unconditionally wastes a full click cycle
        # (~8s) in the common steady-state case. Skip straight to Heal if
        # it's already exactly right.
        current = _read_stepper_value(plus)
        if current == batch_size:
            log(f"[Healing] Batch quantity already at {batch_size} (conf plus={plus.confidence:.2f}), skipping +/-")
            return True

        log(f"[Healing] Zeroing batch quantity (conf minus={minus.confidence:.2f})...")
        if not _zero_out_stepper(mx, my, plus, batch_size):
            return False

        log(f"[Healing] Setting batch quantity to {batch_size} (conf plus={plus.confidence:.2f})...")
        return _set_to_target_verified(px, py, plus, batch_size)
    except Exception as e:
        log(f"[Healing] ERROR setting batch size: {e}")
        return False


def check_and_heal_once(band: list[float], batch_size: int, debug: bool = False) -> bool:
    """
    Check for wounded troops and perform one healing cycle if needed.

    Returns True if healing was started (and will continue in background).
    Returns False if no wounded troops or healing failed.
    """
    # Step 1: Check for wounded troops icon
    log(f"[Healing] Checking for wounded troops (batch_size={batch_size})...")
    thr_wounded = cfg_threshold("healing_wounded")
    pos = _find_healing_icon("healing_wounded.png", band, thr_wounded, debug=True)
    if pos is None:
        if debug:
            log("[Healing] No wounded troops detected")
        return False

    log(f"[Healing] ✓ Wounded troops detected at ({pos[0]:.0f}, {pos[1]:.0f})")

    # Step 2: Click to open healing modal
    log(f"[Healing] Opening healing modal...")
    click(pos[0], pos[1])
    time.sleep(1.5)

    # Step 3: Set batch size on the first (topmost) troop row.
    # The quantity field itself doesn't accept keyboard/paste input (it's a
    # game-rendered widget, not a native text field) - only the +/- steppers
    # work. Zero the stepper out (clamps at 0, so overshooting is safe) then
    # click "+" exactly batch_size times for a deterministic result.
    if not _set_batch_size(batch_size):
        log("[Healing] ABORT: Could not set batch size safely — closing modal, will retry next poll")
        press_escape()
        time.sleep(0.5)
        return False

    # Step 4: Find and click the "Heal" button
    # The Heal button should be visible in the modal (full screen search)
    log(f"[Healing] Searching for Heal button in modal...")
    thr_heal = cfg_threshold("healing_heal_button")
    try:
        screen = capture()
        ensure_template_scale(screen)
        # Search full screen for heal button (it's in a modal)
        from lastz.vision import find_template
        heal_match = find_template(screen, "healing_heal_button.png", thr_heal)
        if heal_match is None:
            log("[Healing] ERROR: Heal button not found in modal - template missing or threshold too high?")
            log("[Healing] Modal may be open - press Escape manually")
            return False

        hx, hy = physical_to_logical(heal_match.phys_x, heal_match.phys_y)
        log(f"[Healing] ✓ Heal button found (conf={heal_match.confidence:.4f}), clicking at ({hx:.0f}, {hy:.0f})")
        click(hx, hy)
        time.sleep(2.0)

    except Exception as e:
        log(f"[Healing] ERROR clicking Heal button: {e}")
        return False

    # Step 5: Modal should close, now check for "Ask Alliance Help" icon
    log(f"[Healing] Checking for Ask Alliance Help icon...")
    thr_ask = cfg_threshold("healing_ask_help")
    pos_ask = _find_healing_icon("healing_ask_help.png", band, thr_ask, debug=True)
    if pos_ask is not None:
        log(f"[Healing] ✓ Asking alliance help at ({pos_ask[0]:.0f}, {pos_ask[1]:.0f})")
        click(pos_ask[0], pos_ask[1])
        time.sleep(1.0)
        log("[Healing] SUCCESS: Healing started, will collect when done")
        return True
    else:
        # Check if healing failed (no resources?)
        # If the wounded icon is still there, healing likely failed
        log("[Healing] Ask help icon not found, checking if healing failed...")
        pos_still_wounded = _find_healing_icon("healing_wounded.png", band, thr_wounded, debug=True)
        if pos_still_wounded is not None:
            log("[Healing] ERROR: Healing failed - wounded icon still present (likely not enough resources)")
            return False
        else:
            # Icon changed but not to ask_help - maybe healing instant?
            log("[Healing] WARN: Icon changed but ask_help not found - healing may have started (or instant heal?)")
            return True


def _complete_icon_names() -> list[str]:
    """
    Each troop type shows its own portrait as the "healing done" HUD icon
    (same slot, different picture per type - e.g. healing_complete.png,
    healing_complete_2.png, healing_complete_3.png, ...). Check every
    captured variant rather than a single hardcoded name.
    """
    return sorted(p.name for p in templates_dir().glob("healing_complete*.png"))


def check_and_collect_healing(band: list[float], debug: bool = False) -> bool:
    """
    Check if healing is complete and collect healed troops.

    Returns True if healing was collected.
    """
    thr_complete = cfg_threshold("healing_complete")
    pos = None
    for icon_name in _complete_icon_names():
        pos = _find_healing_icon(icon_name, band, thr_complete, debug=debug)
        if pos is not None:
            break
    if pos is None:
        if debug:
            log("[Healing] No completed healing to collect")
        return False

    log(f"[Healing] ✓✓✓ Healing complete! Collecting at ({pos[0]:.0f}, {pos[1]:.0f})")
    click(pos[0], pos[1])
    time.sleep(1.5)
    log("[Healing] Troops collected, checking for more wounded...")
    return True
