"""
Shared helpers used by every flow.
"""
import time

from lastz.config import window_offset_click
from lastz.input import click


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
