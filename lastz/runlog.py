"""
Runtime diagnostics for gifts collection runs.

Writes to stdout and appends to logs/runs.log so a failed run can be shared
without relying on terminal scrollback alone.
"""
from __future__ import annotations

import datetime
import platform
import subprocess
import sys
import traceback
from pathlib import Path

from lastz.config import game_process, logs_dir


def _runs_log_path() -> Path:
    p = logs_dir() / "runs.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log(msg: str) -> None:
    """Print and append a timestamped line to logs/runs.log."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(_runs_log_path(), "a") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"[runlog] WARN: could not write runs.log: {e}")


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
