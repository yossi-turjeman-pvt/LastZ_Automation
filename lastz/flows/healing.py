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
from lastz.input import click, rapid_click
from lastz.screen import (
    capture,
    capture_region,
    game_window_band_logical,
    game_window_band_phys,
    physical_to_logical,
)
from lastz.vision import ensure_template_scale, find_all_templates, find_template_local

# Comfortably above any batch_size we'd configure, so rapid-decrementing this
# many times always bottoms the stepper out at 0 regardless of leftover value.
_ZERO_OUT_CLICKS = 300


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

        log(f"[Healing] Zeroing batch quantity (conf minus={minus.confidence:.2f})...")
        rapid_click(mx, my, count=_ZERO_OUT_CLICKS, interval=0.02)
        time.sleep(0.3)

        log(f"[Healing] Setting batch quantity to {batch_size} (conf plus={plus.confidence:.2f})...")
        rapid_click(px, py, count=batch_size, interval=0.02)
        time.sleep(0.3)
        return True
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
        log("[Healing] WARN: Could not set batch size, using existing modal value")

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
