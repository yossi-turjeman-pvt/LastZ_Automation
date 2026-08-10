"""
Background Watcher Daemon — Alliance Gifts on an interval, with Helicopter priority.

When BR heli indication appears (background poll), the current gifts run yields
at the next step boundary, heli runs, then gifts resume from that step.
"""
import datetime
import time
from pathlib import Path

from lastz.config import logs_dir, watcher_cfg
from lastz.flows.alliance_gifts import run_alliance_gifts_flow
from lastz.flows.helicopter import (
    helicopter_cfg,
    poll_br_heli_once,
    run_helicopter_flow,
    start_heli_monitor,
    stop_heli_monitor,
)
from lastz.heli_priority import (
    HeliInterrupt,
    clear_heli,
    heli_pending,
    heli_snoozed,
    heli_snooze_remaining,
    record_heli_failure,
    record_heli_success,
)
from lastz.input import GameNotRunningError
from lastz.runlog import dump_crash


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


def _sleep_polling_heli(total_sec: float) -> None:
    """Sleep in short chunks; return early if heli becomes pending (unless
    heli priority is currently snoozed after repeated failures)."""
    cfg = helicopter_cfg()
    chunk = min(1.0, float(cfg.get("poll_sec") or 1.0))
    end = time.time() + max(0.0, total_sec)
    while time.time() < end:
        if cfg.get("enabled", True) and not heli_snoozed():
            if heli_pending() or poll_br_heli_once():
                return
        remaining = end - time.time()
        time.sleep(min(chunk, max(0.05, remaining)))


def _run_heli_flow_tracked(reraise: bool) -> None:
    """Run the heli flow once, updating the failure-cooldown streak based on
    its outcome. If reraise is False, exceptions are logged and swallowed
    (matches the prior HeliInterrupt-branch behavior of not crashing the
    watcher on a heli failure mid-gifts-yield)."""
    try:
        status = run_helicopter_flow(source="watcher")
    except Exception as e:
        record_heli_failure()
        if heli_snoozed():
            log(f">>> Helicopter snoozed for {heli_snooze_remaining():.0f}s after repeated failures")
        if reraise:
            raise
        dump_crash(e, prefix="crash_heli")
        log(f"HELI ERROR: {e}")
        return

    if status.startswith("failed"):
        record_heli_failure()
        log(f"HELI WARN: {status}")
        if heli_snoozed():
            log(f">>> Helicopter snoozed for {heli_snooze_remaining():.0f}s after repeated failures")
    else:
        record_heli_success()


def run_watcher_loop() -> None:
    cfg = watcher_cfg()
    alliance_interval = int(cfg["alliance_interval_sec"])
    heli_on = helicopter_cfg().get("enabled", True)

    log("=" * 60)
    log("      LASTZ ALLIANCE GIFTS WATCHER STARTED             ")
    log("=" * 60)
    log(f"Claiming Alliance Gifts every {alliance_interval}s")
    log(f"Helicopter priority: {'ON' if heli_on else 'OFF'}")
    log("=" * 60)

    resume_at: str | None = None
    if heli_on:
        start_heli_monitor()

    try:
        while True:
            try:
                # Priority: run heli before starting / resuming gifts
                if heli_on and not heli_snoozed() and (heli_pending() or poll_br_heli_once()):
                    log(">>> Helicopter priority — running heli flow")
                    _run_heli_flow_tracked(reraise=True)
                    log(">>> Helicopter complete — continuing gifts")
                    clear_heli()

                log(
                    ">>> Running Alliance Gifts..."
                    + (f" (resume_at={resume_at})" if resume_at else "")
                )
                run_alliance_gifts_flow(source="watcher", start_at=resume_at)
                resume_at = None
                log(f">>> Alliance Gifts complete. Next run in {alliance_interval}s.")
                print("-" * 60)
                _sleep_polling_heli(alliance_interval)

            except HeliInterrupt as hi:
                # check_heli_interrupt() only raises when not heli_snoozed(),
                # so by construction this branch is never entered while
                # snoozed — no separate snooze check needed here.
                log(f">>> Gifts yielded to Heli (resume_at={hi.resume_step})")
                resume_at = hi.resume_step
                _run_heli_flow_tracked(reraise=False)
                clear_heli()
                # Immediately resume gifts — do not wait full interval
                continue

            except KeyboardInterrupt:
                log("Watcher stopped by user.")
                break
            except GameNotRunningError as e:
                log(f">>> GAME NOT RUNNING: {e}")
                log(f"Sleeping {alliance_interval}s before next check...")
                _sleep_polling_heli(alliance_interval)
            except Exception as e:
                dump_crash(e, prefix="crash_watcher")
                log(f"ERROR: {e}")
                log("Retrying in 10 seconds...")
                time.sleep(10)
    finally:
        stop_heli_monitor()
