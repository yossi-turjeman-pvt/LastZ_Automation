"""
Runtime diagnostics for gifts collection runs.

Writes to stdout and appends to logs/runs.log so a failed run can be shared
without relying on terminal scrollback alone.

While a flow has timing enabled, every stdout line (including bare print() from
vision/UI) is prefixed with wall-clock ms + elapsed-since-run-start and mirrored
to runs.log — so timing analysis is not limited to log() call sites.
"""
from __future__ import annotations

import datetime
import platform
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import TextIO

from lastz.config import game_process, logs_dir

# Wall clock for RUN START elapsed deltas (perf_counter).
_run_t0: float | None = None
_tee: "_TimestampTee | None" = None

# Lines already stamped by us (avoid double-prefix if something re-prints).
_TS_PREFIX_RE = re.compile(
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3})?(?: \+\d+\.\d{2}s)?\] "
)


def _runs_log_path() -> Path:
    p = logs_dir() / "runs.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _append_runs(line: str) -> None:
    try:
        with open(_runs_log_path(), "a") as f:
            f.write(line + "\n")
    except OSError as e:
        # Avoid recursion through tee — write straight to real stderr/stdout.
        real = sys.__stdout__
        real.write(f"[runlog] WARN: could not write runs.log: {e}\n")
        real.flush()


def _elapsed_suffix() -> str:
    if _run_t0 is None:
        return ""
    return f" +{time.perf_counter() - _run_t0:.2f}s"


def format_log_line(msg: str) -> str:
    """Build `[YYYY-mm-dd HH:MM:SS.mmm +12.34s] msg` (elapsed omitted before clock start)."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return f"[{ts}{_elapsed_suffix()}] {msg}"


def start_run_clock() -> None:
    """Reset elapsed timer (call once at the very start of a Menu 1 / watcher pass)."""
    global _run_t0
    _run_t0 = time.perf_counter()


def enable_run_tee() -> None:
    """Mirror/timestamp all stdout lines into runs.log for the duration of a run."""
    global _tee
    if _tee is not None:
        return
    _tee = _TimestampTee(sys.stdout)
    sys.stdout = _tee  # type: ignore[assignment]


def disable_run_tee() -> None:
    """Restore stdout after a run."""
    global _tee
    if _tee is None:
        return
    _tee.flush()
    sys.stdout = _tee.real  # type: ignore[assignment]
    _tee = None


def begin_run_logging() -> None:
    """Start clock + stdout tee (idempotent-ish: always resets the clock)."""
    start_run_clock()
    enable_run_tee()


def end_run_logging() -> None:
    disable_run_tee()


def log(msg: str) -> None:
    """Print and append a timestamped line to logs/runs.log."""
    if _tee is not None:
        # Tee stamps + mirrors to runs.log.
        print(msg, flush=True)
        return
    line = format_log_line(msg)
    print(line, flush=True)
    _append_runs(line)


class _TimestampTee:
    """Buffer stdout, stamp complete lines, echo to terminal + runs.log."""

    def __init__(self, real: TextIO) -> None:
        self.real = real
        self._buf = ""

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(data)

    def _emit(self, raw: str) -> None:
        # Preserve empty lines lightly.
        if raw == "":
            self.real.write("\n")
            self.real.flush()
            return
        if _TS_PREFIX_RE.match(raw):
            stamped = raw
        else:
            stamped = format_log_line(raw)
        self.real.write(stamped + "\n")
        self.real.flush()
        _append_runs(stamped)

    def flush(self) -> None:
        if self._buf:
            # Incomplete line without newline — still stamp so we don't lose it at end.
            partial = self._buf
            self._buf = ""
            self._emit(partial)
        self.real.flush()

    def isatty(self) -> bool:
        return self.real.isatty()

    def fileno(self) -> int:
        return self.real.fileno()

    @property
    def encoding(self) -> str | None:
        return getattr(self.real, "encoding", None)


def _git_short_hash() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        return out.strip() or "unknown"
    except Exception:
        return "unknown"


def log_run_header(*, source: str = "menu") -> None:
    """
    Once-per-run environment dump (call after first capture if possible so
    window size is known; safe to call before capture with window=unknown).
    """
    from lastz.screen import get_game_window_bounds
    from lastz.vision import current_template_scale

    try:
        wx, wy, ww, wh = get_game_window_bounds()
        window = f"{ww:.0f}x{wh:.0f} at ({wx:.0f},{wy:.0f})"
    except Exception:
        window = "unknown"

    try:
        from lastz.screen import _last_size

        cap_w, cap_h = _last_size()
        capture = f"{cap_w}x{cap_h}"
    except Exception:
        capture = "none_yet"

    scale = current_template_scale()
    log("=" * 60)
    log(f"RUN START source={source}")
    log(f"  git={_git_short_hash()}")
    log(f"  python={sys.version.split()[0]} platform={platform.platform()}")
    log(f"  process_name={game_process()}")
    log(f"  capture={capture} window={window} template_scale={scale:.3f}")
    log("=" * 60)


def log_step(name: str, status: str, detail: str = "") -> None:
    """Step marker: status is pass|skip|fail|info."""
    extra = f" detail={detail}" if detail else ""
    log(f"[Step] {name} status={status}{extra}")


def log_skip(reason: str, **fields) -> None:
    """Standardized skip line: SKIP reason=... key=value ..."""
    parts = [f"reason={reason}"]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    log(f"SKIP {' '.join(parts)}")


def log_click(
    label: str,
    *,
    template: str = "",
    conf: float | None = None,
    logical_xy: tuple[float, float] | None = None,
    phys_xy: tuple[float, float] | None = None,
    y_frac: float | None = None,
) -> None:
    """One-line summary after an important click."""
    bits = [f"[Click] {label}"]
    if template:
        bits.append(f"template={template}")
    if conf is not None:
        bits.append(f"conf={conf:.4f}")
    if logical_xy is not None:
        bits.append(f"logical=({logical_xy[0]:.1f},{logical_xy[1]:.1f})")
    if phys_xy is not None:
        bits.append(f"phys=({phys_xy[0]:.0f},{phys_xy[1]:.0f})")
    if y_frac is not None:
        bits.append(f"y_frac={y_frac:.2f}")
    log(" ".join(bits))


def log_gifts_modal_state(tag: str = "after_common_claim_all") -> str:
    """
    Check whether Alliance Gifts modal still looks open after Claim All dismiss.

    Returns a short state string and logs it.
    """
    from lastz.config import threshold as cfg_threshold
    from lastz.debug_match import in_band
    from lastz.flows.ui_bands import BAND_RARE_TAB
    from lastz.screen import capture_both
    from lastz.vision import find_any, find_template

    color, gray = capture_both()
    h, w = gray.shape[:2]
    rare = find_template(gray, "rare_tab.png", cfg_threshold("rare_tab"))
    rare_ok = (
        rare is not None
        and in_band(rare.phys_x, rare.phys_y, h, w, *BAND_RARE_TAB)
    )
    claim_all = find_any(
        gray,
        ["claim_all_button_clean.png", "universal_claim_all_button.png"],
        cfg_threshold("claim_all"),
    )
    gifts_tile = find_template(
        gray, "alliance_gifts_precise.png", cfg_threshold("alliance_gifts")
    )

    if rare_ok:
        state = "gifts_modal_open"
    elif gifts_tile is not None:
        state = "alliance_grid_visible_gifts_likely_closed"
    elif claim_all is not None:
        state = "claim_all_still_visible"
    else:
        state = "unknown_not_gifts_modal"

    rare_bit = (
        f"rare_yf={rare.phys_y / h:.2f} rare_conf={rare.confidence:.3f}"
        if rare is not None
        else "rare=none"
    )
    log(
        f"[GiftsState] tag={tag} state={state} {rare_bit} "
        f"claim_all={'yes' if claim_all else 'no'} "
        f"gifts_tile={'yes' if gifts_tile else 'no'}"
    )
    return state


def dump_crash(exc: BaseException, *, prefix: str = "crash") -> Path | None:
    """Save screenshot + write traceback; return screenshot path if any."""
    log(f"FATAL {type(exc).__name__}: {exc}")
    for line in traceback.format_exc().strip().splitlines():
        log(f"  {line}")

    shot_path: Path | None = None
    try:
        import cv2

        from lastz.screen import capture_both

        color, _ = capture_both()
        debug_dir = logs_dir() / "debug" / "flow"
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%H%M%S")
        shot_path = debug_dir / f"{prefix}_{stamp}.png"
        cv2.imwrite(str(shot_path), color)
        log(f"FATAL screenshot={shot_path}")
    except Exception as e:
        log(f"FATAL screenshot_failed: {e}")
        shot_path = None
    return shot_path
