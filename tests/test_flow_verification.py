"""
Three-run verification test for the Alliance Gifts flow.

Runs the full Alliance Gifts claim flow three consecutive times with
pixel-color state checks at each step.  Results are written to
logs/verification_results.txt.

Usage:
    python tests/test_flow_verification.py
"""
import datetime
import subprocess
import sys
import time
from pathlib import Path

import cv2

# Allow running from the project root without installing the package
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lastz.config import window_offset_click, logs_dir
from lastz.flows.alliance_gifts import _claim_tab
from lastz.input import click, focus_game

VERIFICATION_LOG = logs_dir() / "verification_results.txt"


def _log(msg: str) -> None:
    print(msg)
    VERIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(VERIFICATION_LOG, "a") as f:
        f.write(msg + "\n")


def _capture_and_state(tag: str) -> str:
    path = f"/tmp/verify_{tag}.png"
    subprocess.run(["screencapture", "-x", path], check=True)
    img = cv2.imread(path)
    if img is None:
        return "UNKNOWN (No Image)"

    # Gifts modal: gold/brown header at physical (1512, 150)
    gh_b, gh_g, gh_r = img[150, 1512]
    if gh_r > 150 and gh_g > 120 and gh_b < 100:
        state = "ALLIANCE_GIFTS_OPEN"
    else:
        # Alliance Menu: grey/white back button at physical (1225, 1845)
        b, g, r = img[1845, 1225]
        state = "ALLIANCE_MENU_OPEN" if (r > 100 and g > 100 and b > 100) else "MAIN_BASE_MAP_CLEAN"

    import os
    if os.path.exists(path):
        import os; os.remove(path)
    return state


def run_single_verification(run_id: int) -> None:
    _log(f"=================== RUN {run_id} START ===================")
    focus_game()

    _log("Step 1: Resetting UI by clicking outside...")
    dx, dy = window_offset_click("dismiss_outside")
    for _ in range(3):
        click(dx, dy)
        time.sleep(1.5)
    _log(f"-> Verified Starting State: {_capture_and_state(f'{run_id}_init')}")

    from lastz.vision import click_template
    from lastz.config import threshold as cfg_threshold

    _log("Step 2: Opening Alliance Menu...")
    click_template("alliance_shield_clean.png", cfg_threshold("alliance_shield"), label="Alliance menu")
    time.sleep(2.5)
    _log(f"-> Verified Alliance Menu State: {_capture_and_state(f'{run_id}_alliance')}")

    _log("Step 3: Opening Alliance Gifts...")
    click_template("alliance_gifts_precise.png", cfg_threshold("alliance_gifts"), label="Alliance Gifts")
    time.sleep(2.5)
    _log(f"-> Verified Alliance Gifts State: {_capture_and_state(f'{run_id}_gifts')}")

    _log("Step 4: Processing Claiming Loop...")
    common_status = _claim_tab(is_common=True)
    _log(f"-> Common Tab: {common_status}")

    click_template("rare_tab.png", cfg_threshold("rare_tab"), label="Rare tab")
    time.sleep(2.0)
    rare_status = _claim_tab(is_common=False)
    _log(f"-> Rare Tab: {rare_status}")

    _log("Step 5: Closing Alliance Gifts sub-window by clicking outside...")
    click(dx, dy)
    time.sleep(3.0)
    _log(f"-> Verified Post-Gifts Window State: {_capture_and_state(f'{run_id}_post_gifts')}")

    _log("Step 6: Closing Alliance Menu window by clicking outside...")
    click(dx, dy)
    time.sleep(3.0)
    _log(f"-> Verified Final State: {_capture_and_state(f'{run_id}_final')}")
    _log(f"=================== RUN {run_id} COMPLETE ===================")


def start_verification_suite() -> None:
    VERIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(VERIFICATION_LOG, "w") as f:
        f.write("=== LASTZ AUTOMATION THREE-RUN VERIFICATION REPORT ===\n")
        f.write(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    _log("Launching 3 consecutive test runs with active state verification...")

    for i in range(1, 4):
        run_single_verification(i)
        time.sleep(3.0)

    _log("Verification suite finished. See logs/verification_results.txt for full details.")


if __name__ == "__main__":
    start_verification_suite()
