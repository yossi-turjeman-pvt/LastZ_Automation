"""
Screen capture and coordinate helpers.

All capture, click mapping, and pixel scaling is derived at runtime from
macOS display bounds and the game window position — no per-monitor config.
"""
import contextlib
import ctypes
import os
import subprocess
from functools import lru_cache

import cv2
import numpy as np

from lastz.config import game_process

_TEMP_SCREEN = "/tmp/lastz_screen.png"

# Reference calibration (built-in Retina laptop, game fullscreen).
REF_CAPTURE_SIZE = (3024, 1964)
REF_WINDOW_SIZE = (1512, 982)

_last_capture_size: tuple[int, int] | None = None
_active_display: int | None = None
_active_display_bounds: tuple[float, float, float, float] | None = None  # logical x,y,w,h


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


_CG = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_CG.CGGetActiveDisplayList.argtypes = [
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_uint32),
]
_CG.CGGetActiveDisplayList.restype = ctypes.c_int32
_CG.CGDisplayBounds.argtypes = [ctypes.c_uint32]
_CG.CGDisplayBounds.restype = _CGRect


def _last_size() -> tuple[int, int]:
    if _last_capture_size is None:
        raise RuntimeError("No screen capture available yet — call capture() first.")
    return _last_capture_size


def active_capture_display() -> int:
    if _active_display is None:
        return resolve_capture_display()
    return _active_display


def active_display_bounds() -> tuple[float, float, float, float]:
    if _active_display_bounds is None:
        return 0.0, 0.0, float(_last_size()[0]), float(_last_size()[1])
    return _active_display_bounds


@lru_cache(maxsize=1)
def _game_process_name() -> str:
    return game_process()


def list_displays() -> list[dict]:
    """Return connected displays in screencapture -D order (1-based index)."""
    count = ctypes.c_uint32(0)
    _CG.CGGetActiveDisplayList(0, None, ctypes.byref(count))
    n = max(count.value, 1)
    ids = (ctypes.c_uint32 * n)()
    got = ctypes.c_uint32(0)
    err = _CG.CGGetActiveDisplayList(n, ids, ctypes.byref(got))
    if err != 0:
        return [{"index": 1, "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}]

    displays: list[dict] = []
    for i in range(got.value):
        bounds = _CG.CGDisplayBounds(ids[i])
        displays.append(
            {
                "index": i + 1,
                "id": int(ids[i]),
                "x": bounds.origin.x,
                "y": bounds.origin.y,
                "w": bounds.size.width,
                "h": bounds.size.height,
            }
        )
    return displays


def get_game_window_bounds() -> tuple[int, int, int, int]:
    """Return the game window as global logical (x, y, width, height)."""
    proc = _game_process_name()
    script = f'''
tell application "System Events"
    tell process "{proc}"
        if (count of windows) is 0 then error "No game window"
        set p to position of front window
        set s to size of front window
        return (item 1 of p as text) & "," & (item 2 of p as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text)
    end tell
end tell
'''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read game window bounds for '{proc}': {result.stderr.strip()}"
        )
    parts = [int(x.strip()) for x in result.stdout.strip().split(",")]
    if len(parts) != 4:
        raise RuntimeError(f"Unexpected window bounds: {result.stdout!r}")
    return parts[0], parts[1], parts[2], parts[3]


def _capture_file(display: int) -> bool:
    result = subprocess.run(
        ["screencapture", "-x", "-D", str(display), _TEMP_SCREEN],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and os.path.exists(_TEMP_SCREEN)


def _probe_display_size(display: int) -> tuple[int, int] | None:
    if not _capture_file(display):
        return None
    img = cv2.imread(_TEMP_SCREEN, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape
    return w, h


def _window_center() -> tuple[float, float] | None:
    try:
        wx, wy, ww, wh = get_game_window_bounds()
    except RuntimeError:
        return None
    return wx + ww / 2.0, wy + wh / 2.0


def _point_in_rect(px: float, py: float, rx: float, ry: float, rw: float, rh: float) -> bool:
    return rx <= px <= rx + rw and ry <= py <= ry + rh


def _rect_overlap_area(
    ax: float, ay: float, aw: float, ah: float,
    bx: float, by: float, bw: float, bh: float,
) -> float:
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax + aw, bx + bw)
    iy2 = min(ay + ah, by + bh)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


def resolve_capture_display() -> int:
    """Pick the display that contains the game window (largest overlap wins)."""
    center = _window_center()
    if center is None:
        return 1

    cx, cy = center
    try:
        wx, wy, ww, wh = get_game_window_bounds()
    except RuntimeError:
        return 1

    best_index = 1
    best_overlap = -1.0
    for disp in list_displays():
        overlap = _rect_overlap_area(wx, wy, ww, wh, disp["x"], disp["y"], disp["w"], disp["h"])
        if _point_in_rect(cx, cy, disp["x"], disp["y"], disp["w"], disp["h"]) and overlap > best_overlap:
            best_overlap = overlap
            best_index = disp["index"]

    if best_overlap >= 0:
        return best_index

    # Fallback: closest display center to window center.
    best_dist = float("inf")
    for disp in list_displays():
        dcx = disp["x"] + disp["w"] / 2.0
        dcy = disp["y"] + disp["h"] / 2.0
        dist = (dcx - cx) ** 2 + (dcy - cy) ** 2
        if dist < best_dist:
            best_dist = dist
            best_index = disp["index"]
    return best_index


def _set_active_display_bounds(display_index: int) -> None:
    global _active_display_bounds
    for disp in list_displays():
        if disp["index"] == display_index:
            _active_display_bounds = (disp["x"], disp["y"], disp["w"], disp["h"])
            return
    cap_w, cap_h = _last_size()
    _active_display_bounds = (0.0, 0.0, float(cap_w), float(cap_h))


def _run_capture(display: int | None = None) -> None:
    global _last_capture_size, _active_display

    display = display if display is not None else resolve_capture_display()
    if not _capture_file(display):
        raise RuntimeError(f"screencapture failed for display {display}")

    img = cv2.imread(_TEMP_SCREEN, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"screencapture produced no readable image at {_TEMP_SCREEN}")

    h, w = img.shape
    _last_capture_size = (w, h)
    _active_display = display
    _set_active_display_bounds(display)


def capture() -> np.ndarray:
    _run_capture()
    img = cv2.imread(_TEMP_SCREEN, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"screencapture produced no readable image at {_TEMP_SCREEN}")
    return img


def capture_color() -> np.ndarray:
    _run_capture()
    img = cv2.imread(_TEMP_SCREEN, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"screencapture produced no readable image at {_TEMP_SCREEN}")
    return img


def capture_both() -> tuple[np.ndarray, np.ndarray]:
    _run_capture()
    color = cv2.imread(_TEMP_SCREEN, cv2.IMREAD_COLOR)
    if color is None:
        raise RuntimeError(f"screencapture produced no readable image at {_TEMP_SCREEN}")
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    return color, gray


def cleanup_temp() -> None:
    if os.path.exists(_TEMP_SCREEN):
        os.remove(_TEMP_SCREEN)


@contextlib.contextmanager
def capture_context():
    try:
        yield capture()
    finally:
        cleanup_temp()


def pixel_ratio() -> float:
    """Capture pixels per logical point for the active display."""
    cap_w, _ = _last_size()
    _, _, dw, _ = active_display_bounds()
    return cap_w / dw if dw else 1.0


def physical_to_logical(phys_x: float, phys_y: float) -> tuple[float, float]:
    """Map capture-pixel coordinates to global logical click coordinates."""
    cap_w, cap_h = _last_size()
    dx, dy, dw, dh = active_display_bounds()

    try:
        wx, wy, ww, wh = get_game_window_bounds()
    except RuntimeError:
        return dx + phys_x * (dw / cap_w), dy + phys_y * (dh / cap_h)

    # Map through game window when the match falls inside the window area.
    win_x = (wx - dx) * cap_w / dw
    win_y = (wy - dy) * cap_h / dh
    win_w = ww * cap_w / dw
    win_h = wh * cap_h / dh

    if win_w > 0 and win_h > 0:
        rel_x = (phys_x - win_x) / win_w
        rel_y = (phys_y - win_y) / win_h
        if -0.05 <= rel_x <= 1.05 and -0.05 <= rel_y <= 1.05:
            return wx + rel_x * ww, wy + rel_y * wh

    return dx + phys_x * (dw / cap_w), dy + phys_y * (dh / cap_h)


def window_click(x_frac: float, y_frac: float) -> tuple[float, float]:
    """Click a point given as fractions (0–1) of the game window size."""
    wx, wy, ww, wh = get_game_window_bounds()
    return wx + x_frac * ww, wy + y_frac * wh


def click_capture_phys(phys_x: float, phys_y: float) -> None:
    """Click a point in the current screencapture's physical pixel coordinates."""
    from lastz.input import click

    cap_w, cap_h = _last_size()
    dx, dy, dw, dh = active_display_bounds()
    lx = dx + (phys_x / cap_w) * dw
    ly = dy + (phys_y / cap_h) * dh
    click(lx, ly)


def scale_capture_rect(rect: list[int]) -> list[int]:
    """Scale a [x, y, w, h] rect from reference capture size to the current capture."""
    cap_w, cap_h = _last_size()
    ref_w, ref_h = REF_CAPTURE_SIZE
    return [
        int(rect[0] * cap_w / ref_w),
        int(rect[1] * cap_h / ref_h),
        int(rect[2] * cap_w / ref_w),
        int(rect[3] * cap_h / ref_h),
    ]


def scale_capture_rect_uniform(rect: list[int]) -> list[int]:
    """
    Scale [x, y, w, h] with one factor (geometric mean of axis scales).

    Anisotropic scale_capture_rect breaks letterboxed ultrawide (tall ref → short
    current height): timer crops get too flat and OCR misreads 8 as 2.
    """
    import math

    cap_w, cap_h = _last_size()
    ref_w, ref_h = REF_CAPTURE_SIZE
    sx = cap_w / ref_w
    sy = cap_h / ref_h
    s = math.sqrt(sx * sy)
    return [int(round(v * s)) for v in rect]


def scale_capture_offset(dx: float, dy: float) -> tuple[float, float]:
    """Scale a physical-pixel offset from reference capture size to current capture."""
    cap_w, cap_h = _last_size()
    ref_w, ref_h = REF_CAPTURE_SIZE
    return dx * cap_w / ref_w, dy * cap_h / ref_h


def scale_ref_logical_delta(dx: float, dy: float) -> tuple[float, float]:
    """Scale a logical drag delta from reference window size to current game window."""
    _, _, ww, wh = get_game_window_bounds()
    ref_w, ref_h = REF_WINDOW_SIZE
    return dx * ww / ref_w, dy * wh / ref_h
