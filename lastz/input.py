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
_KEY_ESCAPE = 53  # macOS virtual key code

_cg.CGEventCreateKeyboardEvent.argtypes = [_void_p, _uint32, ctypes.c_bool]
_cg.CGEventCreateKeyboardEvent.restype = _void_p


class GameNotFocusedError(RuntimeError):
    """
    Raised when the game is not actually the frontmost app right before
    sending a click or keystroke.

    This is not theoretical: a live flow's "thank you" chat message was
    once typed directly into this IDE's own chat input and submitted as a
    user message, because the agent was working in Cursor (reading files,
    running diagnostics) while the flow's paste_text()/press_return() fired
    — Cursor, not the game, had keyboard focus at that instant, and neither
    function verified focus before sending. Every input-sending function
    below now refuses to fire blindly.
    """

    pass


def is_game_frontmost() -> bool:
    """True if the game process is the actual frontmost (focused) app.

    Stronger than is_game_running(): a running-but-backgrounded game still
    silently receives no keystrokes at all — they go to whatever app is
    actually focused instead (see GameNotFocusedError).
    """
    proc = game_process()
    result = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to return name of first process whose frontmost is true'],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == proc


def _require_game_frontmost(attempts: int = 3) -> None:
    """
    Verify focus, re-focusing (with retries) if needed; raise rather than
    fire blindly.

    A single refocus attempt was too brittle for long-running, time-sensitive
    flows (heli): a transient focus flicker (e.g. an OS/app switch animation
    still settling) killed the entire in-progress flow on one missed click
    instead of just costing a couple seconds of retry. Real incident
    2026-08-04: a heli run died mid-March step this way. Each attempt still
    calls focus_game() (~1.5s) before rechecking, so this raises only after
    genuinely failing to (re)focus for a few seconds straight.
    """
    for _ in range(max(1, attempts)):
        if is_game_frontmost():
            return
        focus_game()
        if is_game_frontmost():
            return
    raise GameNotFocusedError(
        f"Refusing to send input: '{game_process()}' is not the frontmost app."
    )


def click(x: float, y: float) -> None:
    """Post a left-click at logical coordinates (x, y)."""
    _require_game_frontmost()
    move = _cg.CGEventCreateMouseEvent(None, _kCGEventMouseMoved, x, y, 0)
    _cg.CGEventPost(_kCGHIDEventTap, move)
    time.sleep(0.15)
    down = _cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseDown, x, y, 0)
    _cg.CGEventPost(_kCGHIDEventTap, down)
    time.sleep(0.15)
    up = _cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseUp, x, y, 0)
    _cg.CGEventPost(_kCGHIDEventTap, up)
    time.sleep(0.15)


def rapid_click(
    x: float,
    y: float,
    *,
    count: int = 80,
    interval: float = 0.003,
) -> None:
    """
    Near-zero-delay left-click burst at logical (x, y).

    Used for Helicopter prize window (≤10 claimants). Moves once, then
    down/up with minimal sleeps — much faster than click().

    Checks focus ONCE up front (not per-click, which would blow the
    latency budget of an 80+ click burst) — callers doing a long wait
    beforehand should have already reasserted focus close to the burst.
    """
    _require_game_frontmost()
    move = _cg.CGEventCreateMouseEvent(None, _kCGEventMouseMoved, x, y, 0)
    _cg.CGEventPost(_kCGHIDEventTap, move)
    # Tiny settle so Wine/Unity sees the cursor
    time.sleep(0.01)
    n = max(1, int(count))
    gap = max(0.0, float(interval))
    for _ in range(n):
        down = _cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseDown, x, y, 0)
        _cg.CGEventPost(_kCGHIDEventTap, down)
        up = _cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseUp, x, y, 0)
        _cg.CGEventPost(_kCGHIDEventTap, up)
        if gap:
            time.sleep(gap)


def paste_text(text: str) -> None:
    """
    Paste `text` via clipboard + Cmd+V (reliable for game chat under CrossOver).

    Caller must focus the text field first.
    """
    _require_game_frontmost()
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
    time.sleep(0.05)
    subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ],
        capture_output=True,
    )
    time.sleep(0.15)


def press_return() -> None:
    """Press Return / Enter (virtual key 36)."""
    press_key(36)


def press_key(key_code: int) -> None:
    """Post a key down/up for a macOS virtual key code."""
    _require_game_frontmost()
    down = _cg.CGEventCreateKeyboardEvent(None, _uint32(key_code), True)
    _cg.CGEventPost(_kCGHIDEventTap, down)
    time.sleep(0.05)
    up = _cg.CGEventCreateKeyboardEvent(None, _uint32(key_code), False)
    _cg.CGEventPost(_kCGHIDEventTap, up)
    time.sleep(0.1)


def press_escape() -> None:
    """Press Escape — closes Trucks UI and many overlays."""
    press_key(_KEY_ESCAPE)


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
    _require_game_frontmost()
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
    _require_game_frontmost()
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
