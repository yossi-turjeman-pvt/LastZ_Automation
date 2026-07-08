#!/usr/bin/env python3
"""Sanity check: display detection, auto template scale, and key template matches."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lastz.config import window_offset_click, threshold as cfg_threshold
from lastz.input import focus_game, is_game_running
from lastz.screen import (
    active_capture_display,
    active_display_bounds,
    capture,
    get_game_window_bounds,
    list_displays,
    physical_to_logical,
    pixel_ratio,
    resolve_capture_display,
)
from lastz.vision import find_template, template_scales


def main() -> int:
    print("=== LastZ dynamic display verification ===")
    print(f"Game running: {is_game_running()}")

    for disp in list_displays():
        print(
            f"  Display {disp['index']}: "
            f"logical ({disp['x']:.0f},{disp['y']:.0f}) "
            f"{disp['w']:.0f}x{disp['h']:.0f}"
        )

    display = resolve_capture_display()
    print(f"Resolved capture display: {display}")

    if is_game_running():
        focus_game()
        wx, wy, ww, wh = get_game_window_bounds()
        print(f"Game window: x={wx}, y={wy}, w={ww}, h={wh}")

    screen = capture()
    dx, dy, dw, dh = active_display_bounds()
    print(f"Active display bounds: ({dx:.0f},{dy:.0f}) {dw:.0f}x{dh:.0f}")
    print(f"Capture: {screen.shape[1]}x{screen.shape[0]} on display {active_capture_display()}")
    print(f"Pixel ratio: {pixel_ratio():.3f}")
    print(f"Template scales: {template_scales()}")

    checks = [
        ("wilderness_hq_button.png", "wilderness_hq_button"),
        ("hq_world_button.png", "hq_world_button"),
        ("orange_icon_no_badge.png", "orange_icon"),
    ]
    nav_ok = False
    failed = 0
    for tpl, key in checks:
        th = cfg_threshold(key)
        m = find_template(screen, tpl, th)
        if m is None:
            print(f"SKIP {tpl}: below threshold {th} (may be wrong game mode)")
            continue
        nav_ok = True
        lx, ly = physical_to_logical(m.phys_x, m.phys_y)
        print(
            f"OK   {tpl}: conf={m.confidence:.4f} "
            f"capture=({m.phys_x:.0f},{m.phys_y:.0f}) click=({lx:.0f},{ly:.0f})"
        )

    if not nav_ok:
        print("FAIL no HQ navigation template matched")
        failed += 1

    orange = find_template(screen, "orange_icon_no_badge.png", cfg_threshold("orange_icon"))
    if orange is None:
        print("SKIP orange_icon_no_badge.png: not visible (no battle rewards)")
    else:
        lx, ly = physical_to_logical(orange.phys_x, orange.phys_y)
        print(
            f"OK   orange_icon: conf={orange.confidence:.4f} "
            f"click=({lx:.0f},{ly:.0f})"
        )

    ax, ay = window_offset_click("dismiss_outside")
    shield = find_template(screen, "alliance_shield_clean.png", cfg_threshold("alliance_shield"))
    if shield:
        sx, sy = physical_to_logical(shield.phys_x, shield.phys_y)
        print(f"Alliance menu (template): click=({sx:.0f}, {sy:.0f})")
    print(f"Dismiss outside (offset): click=({ax:.0f}, {ay:.0f})")

    print("=== Done ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
