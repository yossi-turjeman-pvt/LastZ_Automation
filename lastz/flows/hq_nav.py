"""
Shared HQ ↔ Wilderness navigation helpers.

Both the Drone Gift (Flow 4) and HQ Resources (Flow 5) flows operate in
HQ base mode.  This module centralises mode detection and navigation so
neither flow duplicates the logic.

The MODE SWITCHER button in the bottom-right corner is a single toggle:
  • In HQ base   → button says "World"        (hq_world_button.png)
                    clicking it returns to wilderness
  • In Wilderness → button says "Headquarters" (wilderness_hq_button.png)
                    clicking it opens HQ base

Public API
----------
is_hq_mode(screen)         → bool
navigate_to_hq(screen)     → bool   (returns False if button not found)
navigate_to_wilderness()   → None
run_in_hq()                → context manager (navigates to HQ, always restores)
"""
import contextlib
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
    Click the "Headquarters" switcher button (visible in wilderness mode).

    Returns True if the button was found and clicked.  After a successful
    click, the caller should sleep ~4s and re-capture to confirm HQ mode.
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
    """
    Click the "World" switcher button (visible in HQ mode) to return to wilderness.

    Called from a finally block after any HQ flow, so the game is left in the
    same mode it started in.  Safe to call even if already in wilderness.
    """
    _, screen = capture_both()
    world_btn = find_template(screen, "hq_world_button.png", cfg_threshold("hq_world_button"))
    if world_btn is None:
        print("-> World button not found — cannot navigate back to wilderness.")
        return
    lx, ly = physical_to_logical(world_btn.phys_x, world_btn.phys_y)
    print(f"-> Restoring wilderness mode — clicking World at logical ({lx:.0f}, {ly:.0f})...")
    click(lx, ly)
    time.sleep(3.0)


@contextlib.contextmanager
def run_in_hq(*, restore_wilderness: bool):
    """
    Context manager: enter HQ base mode, always restore state on exit.

    Usage::

        with run_in_hq(restore_wilderness=started_in_wilderness):
            # game is now in HQ mode
            ...
        # game is back in wilderness if restore_wilderness=True

    The caller is responsible for determining the initial mode
    before entering the context.  Pass ``restore_wilderness=True``
    when the game was in wilderness before the flow started.
    """
    try:
        yield
    finally:
        if restore_wilderness:
            navigate_to_wilderness()
