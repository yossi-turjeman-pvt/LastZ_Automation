"""
Help watcher — tight poll of the bottom-right 1/8 of the game window.

Clicks the Alliance Help handshake icon the instant it appears. Focuses the
game once at start; does not re-focus every frame so the player can keep playing.
"""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from lastz.config import help_watcher_cfg, logs_dir, threshold as cfg_threshold
from lastz.input import GameNotRunningError, click, ensure_game_running, focus_game, is_game_running
from lastz.runlog import dump_crash
from lastz.screen import (
    capture,
    capture_region,
    game_window_band_logical,
    game_window_band_phys,
    physical_to_logical,
)
from lastz.vision import ensure_template_scale, find_template_local


def _log_path() -> Path:
    p = logs_dir() / "help_watcher.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(_log_path(), "a") as f:
        f.write(line + "\n")


def _poll_once(band: list[float], thr: float) -> bool:
    """
    Capture BR band, match help_button, click if found.

    Prefer region capture; fall back to full capture + crop.
    Returns True if a click was issued.
    """
    # Region path: logical rect → local match → map click via image size.
    try:
        lx, ly, lw, lh = game_window_band_logical(band)
        region = capture_region(lx, ly, lw, lh)
        match = find_template_local(region, "help_button.png", thr)
        if match is not None:
            ih, iw = region.shape[:2]
            click_x = lx + (match.phys_x / max(iw, 1)) * lw
            click_y = ly + (match.phys_y / max(ih, 1)) * lh
            log(
                f"Help click (region) at logical ({click_x:.0f}, {click_y:.0f}) "
                f"[conf={match.confidence:.4f}]"
            )
            click(click_x, click_y)
            return True
        return False
    except Exception as region_err:
        # Fall back: full display capture + crop to same band.
        try:
            screen = capture()
            ensure_template_scale(screen)
            ox, oy, rw, rh = game_window_band_phys(band)
            crop = screen[oy : oy + rh, ox : ox + rw]
            if crop.size == 0:
                raise RuntimeError("Empty band crop")
            match = find_template_local(
                crop, "help_button.png", thr, origin_x=ox, origin_y=oy
            )
            if match is None:
                return False
            cx, cy = physical_to_logical(match.phys_x, match.phys_y)
            log(
                f"Help click (full+crop) at logical ({cx:.0f}, {cy:.0f}) "
                f"[conf={match.confidence:.4f}]"
            )
            click(cx, cy)
            return True
        except Exception as full_err:
            raise RuntimeError(
                f"region capture failed ({region_err}); full+crop failed ({full_err})"
            ) from full_err


def run_help_watcher_loop() -> None:
    cfg = help_watcher_cfg()
    poll_sec = float(cfg["poll_sec"])
    band = list(cfg["band"])
    thr = cfg_threshold("help_button")
    backoff_sec = 2.0

    log("=" * 60)
    log("      LASTZ HELP WATCHER STARTED")
    log("=" * 60)
    log(f"Poll={poll_sec}s  band={band}  threshold={thr}")
    log("Focus once, then watch BR 1/8. Ctrl+C to stop.")
    log("=" * 60)

    try:
        ensure_game_running()
        focus_game()
        # Lock template scale from a full frame before the tight loop.
        screen = capture()
        ensure_template_scale(screen)
    except GameNotRunningError as e:
        log(f"Game not running at start: {e}")
    except Exception as e:
        log(f"Startup warn (will retry in loop): {e}")

    while True:
        try:
            if not is_game_running():
                log("Game not running — backoff...")
                time.sleep(backoff_sec)
                continue

            _poll_once(band, thr)
            time.sleep(poll_sec)

        except KeyboardInterrupt:
            log("Help watcher stopped by user.")
            break
        except GameNotRunningError as e:
            log(f"GAME NOT RUNNING: {e}")
            time.sleep(backoff_sec)
        except Exception as e:
            # Window gone / capture flake — brief log, don't crash the watcher.
            msg = str(e)
            if "No game window" in msg or "Could not read game window" in msg:
                log(f"Window unavailable — backoff: {msg}")
                time.sleep(backoff_sec)
            else:
                dump_crash(e, prefix="crash_help_watcher")
                log(f"ERROR: {e} — retrying in {backoff_sec}s")
                time.sleep(backoff_sec)
