"""
Background Watcher Daemon — continuously monitors the screen and triggers
claim flows when rewards become available.

Scan schedule
-------------
Wilderness phase (every loop tick):
  • Every 60 seconds:  check for Battle Rewards orange badge → Flow 3
  • Every 180 seconds: run Alliance Gifts (Flows 1 & 2)

HQ session phase (when either HQ flow is due):
  • Every 150 seconds: HQ Resource Collection sweep (Flow 5)
  • Every 300 seconds: HQ Drone Gift collect (Flow 4)

The HQ session is a dedicated block: _ensure_wilderness() is NOT called during
it, preventing mode conflicts while the map is being panned.  After all HQ work
completes, the game is returned to wilderness before the next wilderness scan.

All intervals are configurable in config.yaml under watcher:.
"""
import datetime
import time
from pathlib import Path

from lastz.config import logs_dir, watcher_cfg
from lastz.config import threshold as cfg_threshold
from lastz.flows.alliance_gifts import run_alliance_gifts_flow
from lastz.flows.battle_rewards import run_battle_rewards_flow
from lastz.flows.drone_gift import run_drone_gift_flow
from lastz.flows.hq_nav import is_hq_mode, navigate_to_hq, navigate_to_wilderness
from lastz.flows.hq_resources import run_hq_resources_flow
from lastz.input import GameNotRunningError, click, focus_game
from lastz.screen import capture, capture_both, physical_to_logical
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
    """If the game is currently in HQ mode, switch back to the wilderness map.

    Called before wilderness-only scans (battle rewards, alliance gifts).
    The HQ flows handle their own navigation and always restore wilderness
    in their finally blocks, but if the game was left in HQ by the user or
    another action, this corrects it.

    NOT called during the HQ session block — see run_watcher_loop().
    """
    try:
        focus_game()
        _, screen = capture_both()
        world_btn = find_template(screen, "hq_world_button.png", cfg_threshold("hq_world_button"))
        if world_btn is not None:
            lx, ly = physical_to_logical(world_btn.phys_x, world_btn.phys_y)
            log(">>> Game is in HQ mode — switching to Wilderness for scan...")
            click(lx, ly)
            time.sleep(3.0)
    except Exception as e:
        log(f"_ensure_wilderness: {e}")


def _orange_icon_present() -> bool:
    try:
        screen = capture()
    except Exception as e:
        log(f"Screen capture failed: {e}")
        return False
    match = find_template(screen, "orange_icon_no_badge.png", cfg_threshold("orange_icon"))
    return match is not None


def _run_hq_session(
    now: float,
    last_resources_time: float,
    last_drone_gift_time: float,
    resources_interval: float,
    drone_gift_interval: float,
) -> tuple[float, float]:
    """
    Run all HQ-mode flows in a single session to avoid repeated mode switches.

    Navigates to HQ once, runs due HQ flows, then returns to wilderness.
    Returns updated (last_resources_time, last_drone_gift_time).
    """
    resources_due    = (now - last_resources_time) >= resources_interval
    drone_gift_due   = (now - last_drone_gift_time) >= drone_gift_interval

    if not resources_due and not drone_gift_due:
        return last_resources_time, last_drone_gift_time

    log(">>> HQ SESSION START <<<")
    try:
        focus_game()
        _, screen = capture_both()
        started_in_wilderness = not is_hq_mode(screen)

        if started_in_wilderness:
            log("-> Navigating to HQ for session...")
            if not navigate_to_hq(screen):
                log("-> HQ navigation failed — skipping HQ session.")
                return last_resources_time, last_drone_gift_time
            _, screen = capture_both()
            if not is_hq_mode(screen):
                log("-> Still not in HQ after navigation — skipping HQ session.")
                return last_resources_time, last_drone_gift_time

        # --- Flow 4: Drone Gift FIRST (needs default HQ camera; must run before map pan) ---
        if drone_gift_due:
            log(">>> PERIODIC TRIGGER: Checking HQ Drone Gift (Flow 4)...")
            from lastz.flows.hq_resources import _recenter_map
            _recenter_map()
            time.sleep(0.5)
            try:
                drone_status = run_drone_gift_flow()
            except Exception as e:
                drone_status = f"ERROR: {e}"
            last_drone_gift_time = now
            log(f">>> Drone Gift: {drone_status}")
        else:
            remaining_drone = int(drone_gift_interval - (now - last_drone_gift_time))
            log(f"Next Drone Gift check in ~{remaining_drone}s.")

        # --- Flow 5: HQ Resource Collection SECOND (pans map; runs after drone gift) ---
        if resources_due:
            log(">>> PERIODIC TRIGGER: Running HQ Resource Collection (Flow 5)...")
            from lastz.flows.hq_resources import _collect_resources
            status = _collect_resources(dry_run=False)
            last_resources_time = now
            log(f">>> HQ Resources: {status}")
        else:
            remaining = int(resources_interval - (now - last_resources_time))
            log(f"Next HQ Resources check in ~{remaining}s.")

    finally:
        # Restore wilderness regardless of what happened inside
        try:
            _, screen = capture_both()
            if is_hq_mode(screen):
                log("-> Restoring wilderness after HQ session...")
                navigate_to_wilderness()
        except Exception as e:
            log(f"HQ session restore: {e}")
        log(">>> HQ SESSION END <<<")

    return last_resources_time, last_drone_gift_time


def run_watcher_loop() -> None:
    cfg = watcher_cfg()
    scan_interval        = int(cfg["scan_interval_sec"])
    alliance_interval    = int(cfg["alliance_interval_sec"])
    drone_gift_interval  = int(cfg.get("drone_gift_interval_sec",   300))
    resources_interval   = int(cfg.get("hq_resources_interval_sec", 150))

    log("=" * 60)
    log("      LASTZ BACKGROUND WATCHER GUARDIAN STARTED        ")
    log("=" * 60)
    log(
        f"Scanning every {scan_interval}s · Alliance Gifts every {alliance_interval}s · "
        f"HQ Resources every {resources_interval}s · Drone Gift every {drone_gift_interval}s"
    )
    log("=" * 60)

    last_alliance_time    = 0.0
    last_drone_gift_time  = 0.0
    last_resources_time   = 0.0

    while True:
        try:
            now = time.time()

            # ── Wilderness phase ──────────────────────────────────────────
            # Battle rewards and alliance gifts require the wilderness map.
            # _ensure_wilderness() is called ONLY here, not during HQ work.
            hq_session_due = (
                (now - last_resources_time)  >= resources_interval or
                (now - last_drone_gift_time) >= drone_gift_interval
            )

            if not hq_session_due:
                _ensure_wilderness()

                log("Scanning screen for Battle Rewards...")
                if _orange_icon_present():
                    log(">>> CLAIM TRIGGER: Found Battle Rewards icon! Launching Flow 3...")
                    run_battle_rewards_flow()
                    log(">>> Flow 3 completed.")
                    time.sleep(2.0)
                else:
                    log("No Battle Rewards detected on screen.")

                elapsed_since_alliance = now - last_alliance_time
                if elapsed_since_alliance >= alliance_interval:
                    log(">>> PERIODIC TRIGGER: Running Alliance Gifts (Flows 1 & 2)...")
                    run_alliance_gifts_flow()
                    last_alliance_time = now
                    log(">>> Alliance Gifts complete. Next check in 3 minutes.")
                else:
                    remaining = int(alliance_interval - elapsed_since_alliance)
                    log(f"Next Alliance Gifts check in ~{remaining}s.")

            # ── HQ session phase ──────────────────────────────────────────
            last_resources_time, last_drone_gift_time = _run_hq_session(
                now=now,
                last_resources_time=last_resources_time,
                last_drone_gift_time=last_drone_gift_time,
                resources_interval=resources_interval,
                drone_gift_interval=drone_gift_interval,
            )

            # After HQ session, run wilderness flows too if they are due
            if hq_session_due:
                _ensure_wilderness()

                log("Scanning screen for Battle Rewards (post-HQ)...")
                if _orange_icon_present():
                    log(">>> CLAIM TRIGGER: Found Battle Rewards icon! Launching Flow 3...")
                    run_battle_rewards_flow()
                    log(">>> Flow 3 completed.")
                    time.sleep(2.0)

                elapsed_since_alliance = now - last_alliance_time
                if elapsed_since_alliance >= alliance_interval:
                    log(">>> PERIODIC TRIGGER: Running Alliance Gifts (Flows 1 & 2)...")
                    run_alliance_gifts_flow()
                    last_alliance_time = now
                    log(">>> Alliance Gifts complete.")

            log(f"Sleeping {scan_interval}s...")
            print("-" * 60)
            time.sleep(scan_interval)

        except KeyboardInterrupt:
            log("Watcher stopped by user.")
            break
        except GameNotRunningError as e:
            log(f">>> GAME NOT RUNNING: {e}")
            log(f"Sleeping {scan_interval}s before next check...")
            time.sleep(scan_interval)
        except Exception as e:
            log(f"ERROR: {e}")
            log("Retrying in 10 seconds...")
            time.sleep(10)
