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

from lastz.config import healing_cfg, logs_dir, threshold as cfg_threshold
from lastz.input import click
from lastz.screen import (
    capture,
    capture_region,
    game_window_band_logical,
    game_window_band_phys,
    physical_to_logical,
)
from lastz.vision import ensure_template_scale, find_template_local


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


def _find_healing_icon(icon_name: str, band: list[float], thr: float) -> tuple[float, float] | None:
    """
    Search for healing icon in the specified band.

    Returns (logical_x, logical_y) if found, None otherwise.
    Uses region capture with fallback to full capture + crop.
    """
    try:
        lx, ly, lw, lh = game_window_band_logical(band)
        region = capture_region(lx, ly, lw, lh)
        match = find_template_local(region, icon_name, thr)
        if match is not None:
            ih, iw = region.shape[:2]
            click_x = lx + (match.phys_x / max(iw, 1)) * lw
            click_y = ly + (match.phys_y / max(ih, 1)) * lh
            return (click_x, click_y)
        return None
    except Exception:
        # Fallback: full capture + crop
        try:
            screen = capture()
            ensure_template_scale(screen)
            ox, oy, rw, rh = game_window_band_phys(band)
            crop = screen[oy : oy + rh, ox : ox + rw]
            if crop.size == 0:
                return None
            match = find_template_local(
                crop, icon_name, thr, origin_x=ox, origin_y=oy
            )
            if match is None:
                return None
            return physical_to_logical(match.phys_x, match.phys_y)
        except Exception:
            return None


def check_and_heal_once(band: list[float], batch_size: int) -> bool:
    """
    Check for wounded troops and perform one healing cycle if needed.

    Returns True if healing was started (and will continue in background).
    Returns False if no wounded troops or healing failed.
    """
    # Step 1: Check for wounded troops icon
    thr_wounded = cfg_threshold("healing_wounded")
    pos = _find_healing_icon("healing_wounded.png", band, thr_wounded)
    if pos is None:
        return False

    log(f"Wounded troops detected at ({pos[0]:.0f}, {pos[1]:.0f})")

    # Step 2: Click to open healing modal
    click(pos[0], pos[1])
    time.sleep(1.5)

    # TODO: Step 3: Set batch size to configured value
    # This requires clicking on the number field and typing the value
    # For now, we'll assume the default/previous value is acceptable
    # Will implement number field clicking in next iteration

    # Step 4: Find and click the "Heal" button
    # The Heal button should be visible in the modal (full screen search)
    thr_heal = cfg_threshold("healing_heal_button")
    try:
        screen = capture()
        ensure_template_scale(screen)
        # Search full screen for heal button (it's in a modal)
        from lastz.vision import find_template
        heal_match = find_template(screen, "healing_heal_button.png", thr_heal)
        if heal_match is None:
            log("WARN: Heal button not found in modal")
            # TODO: Press Escape to close modal?
            return False

        hx, hy = physical_to_logical(heal_match.phys_x, heal_match.phys_y)
        log(f"Clicking Heal button at ({hx:.0f}, {hy:.0f})")
        click(hx, hy)
        time.sleep(2.0)

    except Exception as e:
        log(f"ERROR clicking Heal button: {e}")
        return False

    # Step 5: Modal should close, now check for "Ask Alliance Help" icon
    thr_ask = cfg_threshold("healing_ask_help")
    pos_ask = _find_healing_icon("healing_ask_help.png", band, thr_ask)
    if pos_ask is not None:
        log(f"Asking alliance help at ({pos_ask[0]:.0f}, {pos_ask[1]:.0f})")
        click(pos_ask[0], pos_ask[1])
        time.sleep(1.0)
        log("Healing started, will collect when done")
        return True
    else:
        # Check if healing failed (no resources?)
        # If the wounded icon is still there, healing likely failed
        pos_still_wounded = _find_healing_icon("healing_wounded.png", band, thr_wounded)
        if pos_still_wounded is not None:
            log("WARN: Healing failed (possibly not enough resources)")
            return False
        else:
            # Icon changed but not to ask_help - maybe healing instant?
            log("Healing may have started (no ask_help icon found)")
            return True


def check_and_collect_healing(band: list[float]) -> bool:
    """
    Check if healing is complete and collect healed troops.

    Returns True if healing was collected.
    """
    thr_complete = cfg_threshold("healing_complete")
    pos = _find_healing_icon("healing_complete.png", band, thr_complete)
    if pos is None:
        return False

    log(f"Healing complete! Collecting at ({pos[0]:.0f}, {pos[1]:.0f})")
    click(pos[0], pos[1])
    time.sleep(1.5)
    return True
