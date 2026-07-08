"""
Verify drone gift templates against the live game screen.

Run from your terminal (requires Screen Recording permission for screencapture):

    cd /Users/yossiturjeman/LastZ_Automation
    python3 scripts/dev/verify_drone_templates.py

Expected results when game is in HQ mode:
  hq_world_button.png    → 0.80+  (always visible in HQ)
  hq_drone_gift_chest.png → 0.70+  (visible when chest is available)
  drone_claim_btn.png    → LOW    (not on screen yet — need to open Area Exploration)
  drone_collect_btn.png  → LOW    (not on screen yet — only in modal)
"""
import subprocess, sys, os
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lastz.config import PROJECT_ROOT

SCREEN = "/tmp/lastz_verify.png"
TEMPLATES_DIR = PROJECT_ROOT / "templates" / "active"
DRONE_TEMPLATES = [
    ("hq_world_button.png",      0.70, "visible in HQ mode"),
    ("hq_drone_gift_chest.png",  0.65, "visible when chest is available"),
    ("drone_claim_btn.png",      0.80, "only in Area Exploration"),
    ("drone_collect_btn.png",    0.80, "only in Idle Reward modal"),
]


def main() -> None:
    print("Capturing screen...")
    ret = subprocess.run(["screencapture", "-x", SCREEN])
    if ret.returncode != 0:
        print("ERROR: screencapture failed — grant Screen Recording to your terminal app")
        print("       System Settings → Privacy & Security → Screen Recording")
        sys.exit(1)

    screen = cv2.imread(SCREEN, cv2.IMREAD_GRAYSCALE)
    print(f"Screen: {screen.shape[1]}x{screen.shape[0]} physical pixels\n")

    print(f"{'Template':<35} {'Size':>12}  {'Confidence':>12}  {'Threshold':>10}  Status")
    print("-" * 90)
    for name, threshold, note in DRONE_TEMPLATES:
        path = TEMPLATES_DIR / name
        tpl = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            print(f"  {name:<33}  MISSING")
            continue
        th, tw = tpl.shape
        if th > screen.shape[0] or tw > screen.shape[1]:
            print(f"  {name:<33}  {tw}x{th:>4}  TEMPLATE LARGER THAN SCREEN")
            continue
        result = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        conf = float(cv2.minMaxLoc(result)[1])
        status = "PASS" if conf >= threshold else f"LOW ({note})"
        print(f"  {name:<33}  {tw}x{th:>4}  {conf:>12.4f}  {threshold:>10.2f}  {status}")

    if os.path.exists(SCREEN):
        os.remove(SCREEN)


if __name__ == "__main__":
    main()
