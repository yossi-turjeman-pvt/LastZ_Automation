"""
Shared HQ ↔ Wilderness navigation helpers.

The MODE SWITCHER button in the bottom-right corner is a single toggle:
  • In HQ base   → button says "World"        (hq_world_button.png)
  • In Wilderness → button says "Headquarters" (wilderness_hq_button.png)
"""
import time

from lastz.config import threshold as cfg_threshold
from lastz.input import click
from lastz.screen import capture_both, physical_to_logical
from lastz.vision import find_template


def is_hq_mode(screen) -> bool:
    """Return True if the World button is visible, confirming HQ mode."""
    m = find_template(screen, "hq_world_button.png", cfg_threshold("hq_world_button"))
    return m is not None


def navigate_to_hq(screen) -> bool:
    """
    Click the Headquarters switcher (visible in wilderness).

    Returns True if clicked. Caller should re-capture to confirm HQ mode.
    """
    hq_btn = find_template(
        screen, "wilderness_hq_button.png", cfg_threshold("wilderness_hq_button")
    )
    if hq_btn is None:
        print("-> Wilderness HQ button not found — cannot navigate to HQ.")
        return False
    lx, ly = physical_to_logical(hq_btn.phys_x, hq_btn.phys_y)
    print(f"-> Clicking Headquarters button at logical ({lx:.0f}, {ly:.0f})...")
    click(lx, ly)
    time.sleep(4.0)
    return True


def navigate_to_wilderness() -> None:
    """Click World switcher (visible in HQ) to return to wilderness."""
    _, screen = capture_both()
    world_btn = find_template(screen, "hq_world_button.png", cfg_threshold("hq_world_button"))
    if world_btn is None:
        print("-> World button not found — cannot navigate back to wilderness.")
        return
    lx, ly = physical_to_logical(world_btn.phys_x, world_btn.phys_y)
    print(f"-> Restoring wilderness mode — clicking World at logical ({lx:.0f}, {ly:.0f})...")
    click(lx, ly)
    time.sleep(3.0)
