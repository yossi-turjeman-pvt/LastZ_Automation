"""
Extract templates for the HQ Resource Collection flow (Flow 5).

Source image: assets/8-e305994f-02a2-4c6e-9740-8ac2e084ad76.png
  1024×643 logical pixels.

IMPORTANT: The reference screenshot contains red annotation arrows drawn on top
of the icons (for documentation).  This script detects those red pixels and
replaces them with the median colour of surrounding non-red pixels before
saving, so templates match the live game UI rather than the annotation overlay.

Templates crop the INNER RESOURCE SYMBOL of each badge circle, excluding the
numeric count label below the icon.

To re-calibrate with a clean live screenshot (no annotation arrows):
  1. Focus the game in HQ mode with buildings at capacity
  2. screencapture -x ~/Downloads/hq_ref.png
  3. Update ASSET below and CROPS coordinates (logical px in source image)
  4. Re-run this script
  5. Run scripts/dev/verify_hq_resource_templates.py to check confidence
"""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lastz.config import retina_scale as _retina_scale

ASSETS = Path("/Users/yossiturjeman/.cursor/projects/Users-yossiturjeman-LastZ-Automation/assets")
OUT = Path(__file__).resolve().parents[2] / "templates" / "active"

# Prefer the annotated reference; swap to a clean live capture when available.
ASSET = ASSETS / "8-e305994f-02a2-4c6e-9740-8ac2e084ad76.png"

# Source image logical dimensions (1024x643 screenshot)
SOURCE_WIDTH = 1024

# CROPS: output filename → (left, upper, right, lower) in source-image logical px.
# Each box crops the inner badge circle (symbol only, no count text below).
# Coordinates verified against the reference screenshot; red arrows are stripped.
CROPS = {
    # Food / Farmhouse: inner meat symbol only (excludes "1.3K" count text below).
    "hq_resource_food.png": (64, 322, 92, 350),

    # Wood / Lumberyard: log-bundle symbol inside badge circle.
    # Verified: 3 true matches at threshold 0.85 on reference screenshot.
    "hq_resource_wood.png": (241, 220, 273, 252),

    # Energy / Smelting Plant: lightning-bolt center (excludes "660" count text).
    "hq_resource_energy.png": (620, 46, 648, 74),

    # Gold / Residence: Z-coin symbol only (excludes "291" count text below).
    "hq_resource_gold.png": (924, 218, 948, 242),
}


def _red_annotation_mask(hsv: np.ndarray) -> np.ndarray:
    """Return boolean mask of bright red annotation arrow pixels."""
    lower_red1 = np.array([0, 150, 150])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([170, 150, 150])
    upper_red2 = np.array([180, 255, 255])
    return (
        cv2.inRange(hsv, lower_red1, upper_red1) > 0
    ) | (cv2.inRange(hsv, lower_red2, upper_red2) > 0)


def _strip_red_annotations(crop_bgr: np.ndarray, red_mask: np.ndarray) -> np.ndarray:
    """
    Replace red annotation pixels with the median colour of non-red pixels.

    This removes the documentation arrows from the reference screenshot so
    the saved template matches what the live game shows.
    """
    cleaned = crop_bgr.copy()
    if not red_mask.any():
        return cleaned
    non_red = cleaned[~red_mask]
    if len(non_red) == 0:
        return cleaned
    fill = np.median(non_red, axis=0).astype(np.uint8)
    cleaned[red_mask] = fill
    return cleaned


def _game_logical_width() -> int:
    script = (
        'tell application "System Events" to get size of '
        'first window of first process whose name is "Survival.exe"'
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        try:
            return int(r.stdout.strip().split(",")[0].strip())
        except ValueError:
            pass
    return 1512


def main() -> None:
    if not ASSET.exists():
        print(f"ERROR: Source asset not found: {ASSET}")
        print("Capture a clean HQ screenshot and update ASSET in this script.")
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    game_w = _game_logical_width()
    retina = _retina_scale()
    scale = (game_w / SOURCE_WIDTH) * retina
    print(
        f"Source: {ASSET.name}\n"
        f"Game logical width: {game_w}px  |  retina: {retina}x  |  "
        f"scale: {scale:.4f}x\n"
    )

    img_bgr = cv2.imread(str(ASSET))
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    full_red = _red_annotation_mask(hsv)

    for out_name, (left, upper, right, lower) in CROPS.items():
        crop_bgr = img_bgr[upper:lower, left:right]
        crop_red = full_red[upper:lower, left:right]
        red_count = int(crop_red.sum())
        cleaned = _strip_red_annotations(crop_bgr, crop_red)

        lw, lh = right - left, lower - upper
        phys_w = max(1, int(round(lw * scale)))
        phys_h = max(1, int(round(lh * scale)))
        gray = cv2.cvtColor(cleaned, cv2.COLOR_BGR2GRAY)
        scaled = cv2.resize(gray, (phys_w, phys_h), interpolation=cv2.INTER_LANCZOS4)

        dest = OUT / out_name
        cv2.imwrite(str(dest), scaled)
        print(
            f"  {out_name}  {lw}×{lh}px → {phys_w}×{phys_h}px  "
            f"red_pixels_stripped={red_count}"
        )

    print(f"\nTemplates saved to {OUT}")
    print("Next: run scripts/dev/verify_hq_resource_templates.py against the live game.")
    print("Tip: for best results, re-capture from a clean screenshot with NO annotation arrows.")


if __name__ == "__main__":
    main()
