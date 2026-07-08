"""
Extract templates for the HQ Drone Gift flow from reference screenshots.

Source images in Downloads/LastZFlow are full Retina captures (~3020×1898).
Crops are taken in physical pixel space — no scaling needed.

If template matching confidence is still low, recapture from the live game:
    screencapture -x /tmp/ref.png
Measure the element in the Retina image, update the crop boxes, and re-run.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Prefer Downloads reference set; fall back to Cursor assets folder.
_SOURCE_DIRS = [
    Path("/Users/yossiturjeman/Downloads/LastZFlow"),
    Path("/Users/yossiturjeman/.cursor/projects/Users-yossiturjeman-LastZ-Automation/assets"),
]
OUT = Path(__file__).resolve().parents[2] / "templates" / "active"

# Map: output filename → (source suffix, crop box left, upper, right, lower in physical px)
# Boxes derived from green-button detection on 6.1.png / 7.1.png reference captures.
CROPS = {
    "hq_drone_gift_chest.png": ("5.1", (1378, 1048, 1518, 1158)),
    "drone_claim_btn.png": ("6.1", (1734, 1351, 1930, 1444)),
    "drone_collect_btn.png": ("7.1", (1332, 1361, 1691, 1465)),
    "hq_world_button.png": ("5.1", (2847, 1749, 3020, 1898)),
}


def _resolve_source(suffix: str) -> Path | None:
    for base in _SOURCE_DIRS:
        if not base.exists():
            continue
        matches = sorted(base.glob(f"{suffix}*.png"))
        if matches:
            return matches[0]
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Output: {OUT}\n")
    for out_name, (src_key, box) in CROPS.items():
        src_path = _resolve_source(src_key)
        if src_path is None:
            print(f"[WARN] Source '{src_key}' not found — skipping {out_name}")
            continue
        img = cv2.imread(str(src_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"[WARN] Could not read {src_path}")
            continue
        l, u, r, b = box
        crop = img[u:b, l:r]
        dest = OUT / out_name
        cv2.imwrite(str(dest), crop)
        print(f"Saved {out_name}  {crop.shape[1]}×{crop.shape[0]}px  ← {src_path.name}")


if __name__ == "__main__":
    main()
