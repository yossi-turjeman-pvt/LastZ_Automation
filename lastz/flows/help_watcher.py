"""
Help watcher — tight poll of the bottom-right 1/8 of the game window.

Clicks the Alliance Help handshake icon the instant it appears. Focuses the
game once at start; does not re-focus every frame so the player can keep playing.

Also runs healing flow in parallel (prioritized over help clicks).
"""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from lastz.config import healing_cfg, help_watcher_cfg, logs_dir, threshold as cfg_threshold
from lastz.input import GameNotRunningError, click, ensure_game_running, focus_game, is_game_running
from lastz.runlog import dump_crash
from lastz.screen import (
    capture,
    capture_region,
    game_window_band_logical,
    game_window_band_phys,
    physical_to_logical,
)
from lastz.stats import format_summary, record_help_clicks
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
            record_help_clicks(1)
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
            record_help_clicks(1)
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

    # Healing config
    heal_cfg = healing_cfg()
    healing_enabled = heal_cfg["enabled"]
    healing_band = list(heal_cfg["icon_band"])
    healing_batch_size = heal_cfg["batch_size"]
    healing_check_interval = heal_cfg["check_interval_sec"]
    last_healing_check = 0.0
    healing_checks_count = 0

    log("=" * 60)
    log("      LASTZ HELP WATCHER STARTED")
    log("=" * 60)
    log(f"Poll={poll_sec}s  band={band}  threshold={thr}")
    if healing_enabled:
        log(f"Healing enabled: batch={healing_batch_size}, interval={healing_check_interval}s")
    else:
        log("Healing disabled")
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

            # PRIORITY: Check for healing (slower interval)
            #
            # This runs synchronously in the same loop that polls the help
            # icon, blocking it for the duration of a healing cycle - by
            # design (healing is prioritized), not an oversight. Evaluated
            # backgrounding this to a thread (like helicopter.py's read-only
            # BR monitor) and rejected it: the heli monitor only ever reads
            # the screen (capture_game_window_bg(), never focus-stealing),
            # while healing must click (rapid_click/click/press_escape),
            # all of which require the game frontmost - running that
            # concurrently with this loop's own clicks risks real
            # cursor/focus races, not just a shared-state bug. The OCR-
            # verified batch-size step (see healing.py's _zero_out_stepper)
            # already keeps the common-case blocking window to ~1-2s rather
            # than a blind worst-case sweep, which was the actual pressure
            # point pushing toward threading in the first place.
            now = time.time()
            if healing_enabled and (now - last_healing_check) >= healing_check_interval:
                last_healing_check = now
                healing_checks_count += 1

                # Periodic heartbeat log (every ~60s)
                if healing_checks_count % 12 == 1:  # 12 checks * 5s = 60s
                    log(f"[Help] Healing monitor active (check #{healing_checks_count})")

                try:
                    from lastz.flows.healing import check_and_collect_healing, check_and_heal_once

                    # First check if healing is complete (collect priority)
                    if check_and_collect_healing(healing_band, debug=False):
                        # Healing collected, loop again immediately to check for more wounded
                        log("[Help] Healing collected, rechecking for more wounded troops")
                        continue

                    # Then check if we need to start new healing
                    if check_and_heal_once(healing_band, healing_batch_size, debug=False):
                        # Healing started, continue to help polling
                        log("[Help] Healing cycle started, resuming help polling")

                except Exception as heal_err:
                    log(f"[Help] Healing check failed: {heal_err}")
                    import traceback
                    log(f"[Help] Traceback: {traceback.format_exc()}")

            # Continue help polling
            _poll_once(band, thr)
            time.sleep(poll_sec)

        except KeyboardInterrupt:
            log("Help watcher stopped by user.")
            print(format_summary(include_run=False))
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
