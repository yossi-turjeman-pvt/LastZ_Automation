"""
Verify scouting templates against the live wilderness screen.

    python3 scripts/dev/verify_scouting_templates.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lastz.config import PROJECT_ROOT as ROOT, threshold as cfg_threshold
from lastz.vision import find_all_templates, find_template

SCREEN = "/tmp/lastz_scouting_verify.png"
TEMPLATES_DIR = ROOT / "templates" / "active"

CHECKS = [
    ("wilderness_enemy_hq.png", "wilderness_enemy_hq", "enemy HQ buildings"),
    ("scout_action_btn.png", "scout_action_btn", "Scout button (modal must be open)"),
    ("drone_slot_idle.png", "drone_slot_idle", "idle drone slots"),
    ("drone_slot_busy.png", "drone_slot_busy", "busy drone slots"),
]


def main() -> None:
    print("Capturing screen (wilderness map; open HQ modal for Scout btn check)...")
    ret = subprocess.run(["screencapture", "-x", SCREEN])
    if ret.returncode != 0:
        print("ERROR: screencapture failed")
        sys.exit(1)

    screen = cv2.imread(SCREEN, cv2.IMREAD_GRAYSCALE)
    h, w = screen.shape
    print(f"Screen: {w}x{h}\n")

    for name, thresh_key, note in CHECKS:
        path = TEMPLATES_DIR / name
        if not path.exists():
            print(f"  {name:<30} MISSING — run calibrate_scouting_flow.py")
            continue
        thresh = cfg_threshold(thresh_key)
        matches = find_all_templates(screen, name, thresh)
        best = max((m.confidence for m in matches), default=0.0)
        single = find_template(screen, name, thresh)
        status = "OK" if matches else "NOT FOUND"
        print(f"  {name:<30} matches={len(matches):>2} best={best:.4f} thresh={thresh:.2f}  {status}")
        if not matches:
            print(f"      ({note})")


if __name__ == "__main__":
    main()
