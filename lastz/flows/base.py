"""
Shared helpers used by every flow.
"""
import time

from lastz.config import threshold as cfg_threshold
from lastz.config import window_offset_click
from lastz.input import click
from lastz.screen import capture, physical_to_logical
from lastz.vision import find_template


def reset_ui(clicks: int = 3, delay: float = 1.5) -> None:
    """Click empty map area to close any open modals."""
    x, y = window_offset_click("dismiss_outside")
    for _ in range(clicks):
        click(x, y)
        time.sleep(delay)


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
