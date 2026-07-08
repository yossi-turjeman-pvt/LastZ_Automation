"""
Verify HQ resource templates against the live game screen.

Run from your terminal while the game is open in HQ mode with buildings
that have resources ready (floating badge icons visible):

    cd /Users/yossiturjeman/LastZ_Automation
    python3 scripts/dev/verify_hq_resource_templates.py

Expected results when buildings are at capacity (icons visible):
  hq_resource_food.png   → 0.65+  (depends on how many icons are visible)
  hq_resource_wood.png   → 0.65+
  hq_resource_energy.png → 0.65+
  hq_resource_gold.png   → 0.65+

The find_all_templates() function is used (multiple match version), so the
output shows ALL locations above the configured threshold. The goal is to
verify that real building icons are detected and false positives are minimal.
"""
import os
import subprocess
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lastz.config import PROJECT_ROOT
from lastz.vision import find_all_templates

SCREEN = "/tmp/lastz_hq_verify.png"
TEMPLATES_DIR = PROJECT_ROOT / "templates" / "active"

RESOURCE_TEMPLATES = [
    ("hq_resource_food.png",   0.58, "farmhouse food icons"),
    ("hq_resource_wood.png",   0.55, "lumberyard wood icons"),
    ("hq_resource_energy.png", 0.58, "smelting plant energy icons"),
    ("hq_resource_gold.png",   0.58, "residence gold icons"),
    ("hq_resource_exp.png",    0.55, "barracks / hero EXP icons"),
]


def main() -> None:
    print("Capturing screen (ensure game is in HQ mode with resource icons visible)...")
    ret = subprocess.run(["screencapture", "-x", SCREEN])
    if ret.returncode != 0:
        print("ERROR: screencapture failed — grant Screen Recording to your terminal app.")
        print("       System Settings → Privacy & Security → Screen Recording")
        sys.exit(1)

    screen = cv2.imread(SCREEN, cv2.IMREAD_GRAYSCALE)
    h, w = screen.shape
    print(f"Screen: {w}×{h} physical pixels\n")

    print(f"{'Template':<35}  {'Size':>10}  {'Matches':>8}  {'Best conf':>10}  {'Thresh':>8}  Status")
    print("-" * 85)

    for name, threshold, note in RESOURCE_TEMPLATES:
        path = TEMPLATES_DIR / name
        tpl = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            print(f"  {name:<33}  MISSING — run extract_hq_resource_templates.py first")
            continue
        th, tw = tpl.shape
        if th > h or tw > w:
            print(f"  {name:<33}  {tw}×{th}  TEMPLATE LARGER THAN SCREEN — recalibrate")
            continue

        matches = find_all_templates(screen, name, threshold)
        n = len(matches)
        best = max((m.confidence for m in matches), default=0.0)

        if n > 0:
            locs = "  locations: " + ", ".join(
                f"({m.phys_x / 2:.0f},{m.phys_y / 2:.0f})" for m in matches[:6]
            )
            if len(matches) > 6:
                locs += f" +{len(matches)-6} more"
        else:
            locs = f"  (not found — {note})"

        status = "PASS" if n > 0 else "LOW"
        print(f"  {name:<33}  {tw}×{th}  {n:>8}  {best:>10.4f}  {threshold:>8.2f}  {status}")
        print(f"    {locs}")

    if os.path.exists(SCREEN):
        os.remove(SCREEN)
    print("\nTuning: raise threshold if false positives appear; lower if known icons are missed.")
    print("Update config.yaml thresholds accordingly.")


if __name__ == "__main__":
    main()
