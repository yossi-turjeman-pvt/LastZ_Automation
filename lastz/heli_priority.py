"""
Helicopter priority interrupt — shared flag between BR monitor and gifts flow.
"""
from __future__ import annotations

import threading
import time

_pending = threading.Event()
_lock = threading.Lock()
_resume_step: str | None = None

# Failure cooldown: a stuck BR icon (heli event never completes, e.g. troops
# still out) can otherwise retrigger heli priority every cycle, each attempt
# failing and eating ~1-2 min, and gifts never gets more than a few seconds
# between preemptions (observed 2026-07-30 07:39-08:00). After enough
# consecutive failures, snooze heli priority so gifts can make real progress;
# the monitor will naturally re-signal once the snooze lifts if the BR icon
# is still there.
_FAIL_LIMIT = 3
_SNOOZE_SEC = 20 * 60
_fail_streak = 0
_snooze_until = 0.0


class HeliInterrupt(Exception):
    """Raised when a gifts run must yield to Helicopter."""

    def __init__(self, resume_step: str):
        self.resume_step = resume_step
        super().__init__(f"HeliInterrupt resume_at={resume_step}")


def signal_heli() -> None:
    _pending.set()


def clear_heli() -> None:
    _pending.clear()


def heli_pending() -> bool:
    return _pending.is_set()


def set_resume_step(step: str | None) -> None:
    global _resume_step
    with _lock:
        _resume_step = step


def get_resume_step() -> str | None:
    with _lock:
        return _resume_step


def record_heli_failure() -> None:
    """Call after a heli flow attempt fails or raises. After _FAIL_LIMIT
    consecutive failures, heli priority snoozes for _SNOOZE_SEC."""
    global _fail_streak, _snooze_until
    with _lock:
        _fail_streak += 1
        if _fail_streak >= _FAIL_LIMIT:
            _snooze_until = time.time() + _SNOOZE_SEC
            _fail_streak = 0


def record_heli_success() -> None:
    """Call after a heli flow attempt completes ("complete" status)."""
    global _fail_streak
    with _lock:
        _fail_streak = 0


def heli_snoozed() -> bool:
    with _lock:
        return time.time() < _snooze_until


def heli_snooze_remaining() -> float:
    with _lock:
        return max(0.0, _snooze_until - time.time())


def check_heli_interrupt(resume_step: str) -> None:
    """If heli is pending (and not snoozed after repeated failures), raise
    HeliInterrupt so watcher can run heli then resume."""
    if heli_pending() and not heli_snoozed():
        raise HeliInterrupt(resume_step)
