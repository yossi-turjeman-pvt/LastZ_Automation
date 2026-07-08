"""
Diagnose OCR for HQ resource count badges.

Runs a full scan, finds resource icons, crops the count label below each,
runs OCR, and dumps debug images to logs/debug/hq_resources/.

Run while game is in HQ mode with resource buildings at or near capacity:

    cd /Users/yossiturjeman/LastZ_Automation
    python3 scripts/dev/diagnose_hq_resource_ocr.py

Output in logs/debug/hq_resources/:
  <type>_<n>_raw.png     — raw color crop of count badge region
  <type>_<n>_proc.png    — processed image fed to Tesseract
  <type>_<n>_result.txt  — OCR raw text and parsed value

Use these to tune count_crop_offset per resource type in config.yaml.
"""
import os
import subprocess
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lastz.config import PROJECT_ROOT, load_config
from lastz.ocr import read_resource_count_from_region
from lastz.vision import find_all_templates

SCREEN = "/tmp/lastz_hq_diag.png"
DEBUG_DIR = PROJECT_ROOT / "logs" / "debug" / "hq_resources"

RESOURCE_TYPES = [
    ("food",   "hq_resource_food.png",   0.55),
    ("wood",   "hq_resource_wood.png",   0.55),
    ("energy", "hq_resource_energy.png", 0.55),
    ("gold",   "hq_resource_gold.png",   0.55),
]


def main() -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config().get("hq_resources", {})
    default_offset = [-40, 20, 90, 28]  # [dx, dy, w, h] relative to icon center

    print("Capturing screen (ensure game is in HQ mode)...")
    ret = subprocess.run(["screencapture", "-x", SCREEN])
    if ret.returncode != 0:
        print("ERROR: screencapture failed — grant Screen Recording to your terminal.")
        sys.exit(1)

    import numpy as np
    color = cv2.imread(SCREEN, cv2.IMREAD_COLOR)
    gray  = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    h, w  = gray.shape
    print(f"Screen: {w}×{h} px\n")

    for res_type, template_name, threshold in RESOURCE_TYPES:
        matches = find_all_templates(gray, template_name, threshold)
        print(f"--- {res_type} ({template_name}): {len(matches)} icon(s) found ---")

        offsets = cfg.get("count_crop_offset", {}).get(res_type, default_offset)
        dx, dy, cw, ch = offsets

        for i, m in enumerate(matches[:5]):
            cx = int(m.phys_x)
            cy = int(m.phys_y)
            rx = max(0, cx + dx)
            ry = max(0, cy + dy)
            rx2 = min(w, rx + cw)
            ry2 = min(h, ry + ch)

            raw_crop = color[ry:ry2, rx:rx2]
            raw_path = DEBUG_DIR / f"{res_type}_{i}_raw.png"
            cv2.imwrite(str(raw_path), raw_crop)

            value, raw_text = read_resource_count_from_region(
                color, rx, ry, cw, ch, debug_dir=DEBUG_DIR, debug_prefix=f"{res_type}_{i}"
            )
            result_path = DEBUG_DIR / f"{res_type}_{i}_result.txt"
            result_path.write_text(
                f"icon center: ({cx}, {cy})\n"
                f"crop region: ({rx},{ry}) {cw}x{ch}\n"
                f"raw OCR text: {repr(raw_text)}\n"
                f"parsed value: {value}\n"
            )
            status = f"= {value}" if value is not None else "PARSE FAILED"
            print(f"  [{i}] center=({cx},{cy})  crop=({rx},{ry},{cw}x{ch})  "
                  f"raw={repr(raw_text)}  {status}")

        if not matches:
            print(f"  No icons found — lower threshold or check template")
        print()

    if os.path.exists(SCREEN):
        os.remove(SCREEN)
    print(f"Debug images saved to {DEBUG_DIR}")
    print("Review *_proc.png files to tune OCR; update count_crop_offset in config.yaml.")


if __name__ == "__main__":
    main()
