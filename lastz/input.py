"""
Low-level input: mouse clicks via CoreGraphics and game window focus via osascript.
"""
import ctypes
import subprocess
import time

from lastz.config import game_process

_cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_double = ctypes.c_double
_uint32 = ctypes.c_uint32
_int32 = ctypes.c_int32
_void_p = ctypes.c_void_p


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", _double), ("y", _double)]


# Mouse events historically used two doubles (CGPoint ABI as separate args) — keep that.
_cg.CGEventCreateMouseEvent.argtypes = [_void_p, _uint32, _double, _double, _uint32]
_cg.CGEventCreateMouseEvent.restype = _void_p
_cg.CGEventCreateScrollWheelEvent.argtypes = [
    _void_p,
    _uint32,
    _uint32,
    _int32,
    _int32,
]
_cg.CGEventCreateScrollWheelEvent.restype = _void_p
_cg.CGEventPost.argtypes = [_uint32, _void_p]
_cg.CGEventPost.restype = None
_cg.CGEventSetLocation.argtypes = [_void_p, _CGPoint]
_cg.CGEventSetLocation.restype = None
_cg.CGWarpMouseCursorPosition.argtypes = [_CGPoint]
_cg.CGWarpMouseCursorPosition.restype = None

_kCGEventMouseMoved = 5
_kCGEventLeftMouseDown = 1
_kCGEventLeftMouseUp = 2
_kCGHIDEventTap = 0
_kCGScrollEventUnitLine = 1
_kCGScrollEventUnitPixel = 0


def click(x: float, y: float) -> None:
    """Post a left-click at logical coordinates (x, y)."""
    move = _cg.CGEventCreateMouseEvent(None, _kCGEventMouseMoved, x, y, 0)
    _cg.CGEventPost(_kCGHIDEventTap, move)
    time.sleep(0.15)
    down = _cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseDown, x, y, 0)
    _cg.CGEventPost(_kCGHIDEventTap, down)
    time.sleep(0.15)
    up = _cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseUp, x, y, 0)
    _cg.CGEventPost(_kCGHIDEventTap, up)
    time.sleep(0.15)


def drag(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    steps: int = 12,
    step_delay: float = 0.02,
) -> None:
    """
    Perform a click-drag from (x1, y1) to (x2, y2) at logical coordinates.

    MouseDown → N × MouseMoved (evenly spaced) → MouseUp.
    Used for panning the HQ map to scan off-screen buildings.

    Args:
        x1, y1:     Start position in logical screen coordinates.
        x2, y2:     End position in logical screen coordinates.
        steps:      Number of intermediate move events (higher = smoother).
        step_delay: Seconds between each move event.
    """
    # Mouse down at start position
    down = _cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseDown, x1, y1, 0)
    _cg.CGEventPost(_kCGHIDEventTap, down)
    time.sleep(0.1)

    # Intermediate move events
    for i in range(1, steps + 1):
        t = i / steps
        mx = x1 + (x2 - x1) * t
        my = y1 + (y2 - y1) * t
        move = _cg.CGEventCreateMouseEvent(None, _kCGEventMouseMoved, mx, my, 0)
        _cg.CGEventPost(_kCGHIDEventTap, move)
        time.sleep(step_delay)

    # Mouse up at end position
    up = _cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseUp, x2, y2, 0)
    _cg.CGEventPost(_kCGHIDEventTap, up)
    time.sleep(0.2)


def scroll_wheel(x: float, y: float, delta_y: int, *, steps: int = 1, step_delay: float = 0.2) -> None:
    """
    Scroll the mouse wheel at logical (x, y) to zoom/pan the world map.

    Negative delta_y zooms out; positive zooms in (game-dependent).

    CrossOver/Wine needs the cursor actually at (x,y) AND the scroll event
    location set — posting scroll without location often does nothing.
    """
    pt = _CGPoint(float(x), float(y))
    # Hard-warp cursor into the game map (MouseMoved alone is flaky under Wine)
    _cg.CGWarpMouseCursorPosition(pt)
    move = _cg.CGEventCreateMouseEvent(None, _kCGEventMouseMoved, x, y, 0)
    _cg.CGEventPost(_kCGHIDEventTap, move)
    time.sleep(0.12)

    per_step = delta_y // steps if steps else delta_y
    remainder = delta_y - per_step * steps
    for i in range(steps):
        dy = per_step + (remainder if i == steps - 1 else 0)
        # Try pixel units first (Wine/Unity), fall back path uses same API with larger dy
        event = _cg.CGEventCreateScrollWheelEvent(
            None, _kCGScrollEventUnitPixel, 2, _int32(int(dy) * 20), _int32(0)
        )
        _cg.CGEventSetLocation(event, pt)
        _cg.CGEventPost(_kCGHIDEventTap, event)
        time.sleep(step_delay)


class GameNotRunningError(RuntimeError):
    """Raised when the game process is not active and a flow cannot proceed."""
    pass


def is_game_running() -> bool:
    """Return True if the game process is currently running.

    Prefer System Events (matches focus_game). Fall back to pgrep — CrossOver
    wraps Survival.exe and System Events can flake under automation.
    """
    proc = game_process()
    result = subprocess.run(
        ["osascript", "-e",
         f'tell application "System Events" to return exists (processes where name is "{proc}")'],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() == "true":
        return True
    # Fallback: CrossOver / Wine process table
    pg = subprocess.run(["pgrep", "-fl", proc], capture_output=True, text=True)
    return pg.returncode == 0 and bool(pg.stdout.strip())


def ensure_game_running() -> None:
    """Raise GameNotRunningError if the game process is not active."""
    if not is_game_running():
        raise GameNotRunningError(
            f"Game process '{game_process()}' is not running. Skipping flow."
        )


def focus_game() -> None:
    """Bring the game window to the foreground."""
    proc = game_process()
    print(f"Activating game window ({proc})...")
    subprocess.run(
        ["osascript", "-e",
         f'tell application "System Events" to set frontmost of process "{proc}" to true'],
        capture_output=True,
    )
    time.sleep(1.5)
