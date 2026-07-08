"""World map zoom and pan navigation for scouting."""
from __future__ import annotations

import time

from lastz.config import scouting_cfg
from lastz.input import drag, scroll_wheel
from lastz.screen import scale_ref_logical_delta, window_click


def _cfg() -> dict:
    return scouting_cfg()


def _zoom_cfg() -> dict:
    return _cfg().get("zoom", {})


def _travel_cfg() -> dict:
    return _cfg().get("travel", {})


def _scan_cfg() -> dict:
    return _cfg().get("scan", {})


def map_center() -> tuple[float, float]:
    z = _zoom_cfg()
    origin = z.get("origin") or _cfg().get("map_drag_origin", [0.5, 0.45])
    return window_click(float(origin[0]), float(origin[1]))


def zoom_out(*, steps: int | None = None) -> None:
    z = _zoom_cfg()
    n = int(steps if steps is not None else z.get("out_steps", 8))
    delta = int(z.get("out_delta_per_step", -3))
    delay = float(z.get("step_delay_sec", 0.25))
    settle = float(z.get("settle_sec", 1.5))
    cx, cy = map_center()
    print(f"-> Zooming OUT ({n} steps) at map center...")
    scroll_wheel(cx, cy, delta * n, steps=max(1, n), step_delay=delay)
    time.sleep(settle)


def zoom_in(*, steps: int | None = None) -> None:
    z = _zoom_cfg()
    n = int(steps if steps is not None else z.get("in_steps", 5))
    delta = int(z.get("in_delta_per_step", 3))
    delay = float(z.get("step_delay_sec", 0.25))
    settle = float(z.get("settle_sec", 1.5))
    cx, cy = map_center()
    print(f"-> Zooming IN ({n} steps) at map center...")
    scroll_wheel(cx, cy, delta * n, steps=max(1, n), step_delay=delay)
    time.sleep(settle)


def pan_logical(dx: float, dy: float) -> None:
    sdx, sdy = scale_ref_logical_delta(dx, dy)
    ox, oy = map_center()
    drag(ox, oy, ox + sdx, oy + sdy)
    time.sleep(float(_cfg().get("pan_settle_sec", 1.2)))


def looks_like_territory_map(color) -> bool:
    """Territory view has large purple/pink/orange region fills."""
    return _looks_like_territory_map(color)


def _looks_like_territory_map(color) -> bool:
    """Territory view has large purple/pink/orange region fills."""
    from lastz.scouting.house_detect import _map_roi
    import cv2
    import numpy as np

    roi, _, x0, y0 = _map_roi(color)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    territory = cv2.inRange(hsv, (0, 40, 60), (175, 255, 255))
    return float(territory.mean()) > 12


def ensure_house_zoom(*, max_attempts: int = 8) -> None:
    """Adjust zoom until house icons are visible (not HQ-detail or territory)."""
    from lastz.screen import capture_both
    from lastz.scouting.house_detect import find_house_hqs

    for _ in range(max_attempts):
        color, _ = capture_both()
        count = len(find_house_hqs(color))
        if 3 <= count <= 40:
            print(f"-> House-icon zoom OK ({count} icons visible)")
            return
        if _looks_like_territory_map(color) or count < 3:
            print(f"-> Zooming IN ({count} icons — territory or too sparse)")
            zoom_in(steps=3)
        else:
            print(f"-> Zooming OUT ({count} icons — still at HQ detail)")
            zoom_out(steps=2)
        time.sleep(0.8)
    print("-> House-icon zoom: best effort")


def strategic_zoom() -> None:
    """Reach the zoom level where HQs appear as colored house icons."""
    z = _zoom_cfg()
    n = int(z.get("strategic_out_steps", 6))
    zoom_out(steps=n)
    ensure_house_zoom()


def depart_home_city() -> None:
    """Leave alliance city view and settle at house-icon zoom."""
    z = _zoom_cfg()
    n = int(z.get("depart_out_steps", z.get("out_steps", 10)))
    zoom_out(steps=n)
    ensure_house_zoom()


def pan_travel_sector(sector_index: int) -> None:
    """Large pan at strategic zoom to reach a new map area."""
    sectors = _travel_cfg().get("sector_pans", [
        [0, -500], [500, 0], [0, 500], [-500, 0],
        [400, -400], [-400, -400], [-400, 400], [400, 400],
    ])
    if not sectors:
        return
    dx, dy = sectors[sector_index % len(sectors)]
    print(f"-> Travel pan sector {sector_index % len(sectors)}: ({dx}, {dy})")
    pan_logical(float(dx), float(dy))


def pan_scan_step(step_index: int) -> None:
    """Small pan at HQ zoom within the current sector."""
    swipes = _scan_cfg().get("pan_swipes", [
        [0, -150], [150, 0], [0, 150], [-150, 0],
        [0, -150], [-150, 0],
    ])
    if not swipes:
        return
    dx, dy = swipes[step_index % len(swipes)]
    print(f"-> Scan pan step {step_index % len(swipes)}: ({dx}, {dy})")
    pan_logical(float(dx), float(dy))


def enter_sector(sector_index: int) -> None:
    """Pan to a new sector at strategic (house-icon) zoom."""
    pan_travel_sector(sector_index)
