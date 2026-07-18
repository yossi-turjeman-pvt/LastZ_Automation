"""
Background Watcher Daemon — runs Alliance Gifts collection on a timer.

Interval is configurable in config.yaml under watcher.alliance_interval_sec.
"""
import datetime
import time
from pathlib import Path

from lastz.config import logs_dir, watcher_cfg
from lastz.config import threshold as cfg_threshold
from lastz.flows.alliance_gifts import run_alliance_gifts_flow
from lastz.input import GameNotRunningError, click, focus_game
from lastz.screen import capture_both, physical_to_logical
from lastz.vision import find_template


def _log_path() -> Path:
    p = logs_dir() / "watcher.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(_log_path(), "a") as f:
        f.write(line + "\n")


def _ensure_wilderness() -> None:
    """If the game is in HQ mode, switch back to the wilderness map."""
    try:
        focus_game()
        _, screen = capture_both()
        world_btn = find_template(screen, "hq_world_button.png", cfg_threshold("hq_world_button"))
        if world_btn is not None:
            lx, ly = physical_to_logical(world_btn.phys_x, world_btn.phys_y)
            log(">>> Game is in HQ mode — switching to Wilderness...")
            click(lx, ly)
            time.sleep(3.0)
    except Exception as e:
        log(f"_ensure_wilderness: {e}")


def run_watcher_loop() -> None:
    cfg = watcher_cfg()
    alliance_interval = int(cfg["alliance_interval_sec"])

    log("=" * 60)
    log("      LASTZ ALLIANCE GIFTS WATCHER STARTED             ")
    log("=" * 60)
    log(f"Claiming Alliance Gifts every {alliance_interval}s")
    log("=" * 60)

    while True:
        try:
            _ensure_wilderness()
            log(">>> Running Alliance Gifts...")
            run_alliance_gifts_flow()
            log(f">>> Alliance Gifts complete. Next run in {alliance_interval}s.")
            print("-" * 60)
            time.sleep(alliance_interval)

        except KeyboardInterrupt:
            log("Watcher stopped by user.")
            break
        except GameNotRunningError as e:
            log(f">>> GAME NOT RUNNING: {e}")
            log(f"Sleeping {alliance_interval}s before next check...")
            time.sleep(alliance_interval)
        except Exception as e:
            log(f"ERROR: {e}")
            log("Retrying in 10 seconds...")
            time.sleep(10)
