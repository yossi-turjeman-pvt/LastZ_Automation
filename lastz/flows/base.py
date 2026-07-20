"""
Shared helpers used by every flow.
"""
import time

from lastz.config import threshold as cfg_threshold
from lastz.config import window_offset_click
from lastz.debug_match import in_band
from lastz.input import click, press_escape
from lastz.screen import capture, physical_to_logical
from lastz.vision import (
    ensure_template_scale,
    find_template,
    find_template_local,
    template_scales,
)

# Quit Tips modal sits mid-screen; Cancel is the blue button (verified live).
_QUIT_CANCEL_BAND = (0.35, 0.85, 0.30, 0.75)  # y0,y1,x0,x1 fractions of capture
# Search only this ROI for tips/cancel (avoids full-frame multi-scale).
_QUIT_SEARCH_BAND = (0.25, 0.90, 0.20, 0.80)  # y0,y1,x0,x1


def dismiss_quit_tips_if_present() -> bool:
    """
    If Tips / 'Exit the game?' is on screen, click Cancel and return True.

    Never uses the small X. Extra Escape does not dismiss Quit (verified).
    Searches a mid-screen ROI at local scales only (no full-band refine).
    """
    screen = capture()
    ensure_template_scale(screen)
    h, w = screen.shape[:2]
    tips_thr = cfg_threshold("quit_tips")
    cancel_thr = cfg_threshold("quit_cancel")

    y0, y1 = int(_QUIT_SEARCH_BAND[0] * h), int(_QUIT_SEARCH_BAND[1] * h)
    x0, x1 = int(_QUIT_SEARCH_BAND[2] * w), int(_QUIT_SEARCH_BAND[3] * w)
    roi = screen[y0:y1, x0:x1]
    scales = template_scales()

    t0 = time.perf_counter()
    tips = find_template_local(
        roi,
        "quit_tips.png",
        tips_thr,
        scales=scales,
        origin_x=float(x0),
        origin_y=float(y0),
    )
    if tips is None:
        print(
            f"[UI] Quit Tips not in mid ROI "
            f"ms={(time.perf_counter() - t0) * 1000:.0f}"
        )
        return False

    cancel = find_template_local(
        roi,
        "quit_cancel.png",
        cancel_thr,
        scales=scales,
        origin_x=float(x0),
        origin_y=float(y0),
    )
    ms = (time.perf_counter() - t0) * 1000.0
    if cancel is None:
        print(
            f"[UI] Quit Tips seen (conf={tips.confidence:.3f}) but Cancel miss "
            f"ms={ms:.0f}"
        )
        return False

    if not in_band(cancel.phys_x, cancel.phys_y, h, w, *_QUIT_CANCEL_BAND):
        print(
            f"[UI] Quit Cancel outside modal band "
            f"(y_frac={cancel.phys_y / h:.2f}) — ignoring"
        )
        return False

    lx, ly = physical_to_logical(cancel.phys_x, cancel.phys_y)
    print(
        f"[UI] Quit Tips → Cancel at logical ({lx:.1f}, {ly:.1f}) "
        f"[tips={tips.confidence:.3f} cancel={cancel.confidence:.3f}] ms={ms:.0f}"
    )
    click(lx, ly)
    time.sleep(0.8)
    return True


def reset_ui(clicks: int = 3, delay: float = 1.0) -> None:
    """
    Clear overlays via Escape; if Quit Tips appears, dismiss with Cancel.

    `clicks` = max Escape presses (legacy name kept for call sites).
    Does not map-click HQ (that was opening buildings on dense bases).
    """
    max_escapes = max(1, int(clicks))
    print(f"[UI] reset_ui via Escape (max={max_escapes})...")
    for i in range(max_escapes):
        print(f"[UI] reset_ui Escape #{i + 1}/{max_escapes}")
        press_escape()
        time.sleep(delay)
        print(f"[UI] reset_ui tips/cancel check after Escape #{i + 1}")
        if dismiss_quit_tips_if_present():
            print(f"[UI] reset_ui done after Escape #{i + 1} + Cancel")
            return
    print("[UI] reset_ui finished (no Quit Tips — overlays cleared or none)")


def dismiss_overlay(delay: float = 1.0) -> None:
    """Click once outside to dismiss a reward popup or confirmation overlay."""
    x, y = window_offset_click("dismiss_outside")
    click(x, y)
    time.sleep(delay)


def ensure_wilderness() -> str:
    """
    Ensure the game is on the wilderness / World map (not HQ).

    Returns a short status string for logging:
      - "switched: HQ → Wilderness"
      - "already: Wilderness"
      - "unknown: neither World nor HQ button"
    """
    print("[Map] Checking HQ / Wilderness mode...")
    screen = capture()
    world_thr = cfg_threshold("hq_world_button")
    hq_thr = cfg_threshold("hq_world_button")  # same confidence bar for both switchers

    world_btn = find_template(screen, "hq_world_button.png", world_thr)
    if world_btn is not None:
        lx, ly = physical_to_logical(world_btn.phys_x, world_btn.phys_y)
        print(
            f"[Map] HQ → Wilderness: clicking World at logical ({lx:.1f}, {ly:.1f}) "
            f"[conf={world_btn.confidence:.4f}]"
        )
        click(lx, ly)
        time.sleep(3.0)
        return "switched: HQ → Wilderness"

    hq_btn = find_template(screen, "wilderness_hq_button.png", hq_thr)
    if hq_btn is not None:
        print(
            f"[Map] Already on Wilderness "
            f"(Headquarters button conf={hq_btn.confidence:.4f})"
        )
        return "already: Wilderness"

    print("[Map] WARN: map mode unknown (neither World nor HQ button matched)")
    return "unknown: neither World nor HQ button"
