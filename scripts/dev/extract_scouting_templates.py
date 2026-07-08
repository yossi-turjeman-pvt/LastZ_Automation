"""
Extract scouting templates from saved calibration assets.

Run calibrate_scouting_flow.py first, or place reference images in
assets/scouting/ and update CROPS below.

    python3 scripts/dev/extract_scouting_templates.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS = PROJECT_ROOT / "assets" / "scouting"
OUT = PROJECT_ROOT / "templates" / "active"

# Physical-pixel crops (left, upper, right, lower) — tune after calibration capture.
CROPS: dict[str, tuple[str, tuple[int, int, int, int]]] = {
    "wilderness_enemy_hq.png": ("01_wilderness_map.png", (0, 0, 0, 0)),
    "scout_action_btn.png": ("02_hq_modal.png", (0, 0, 0, 0)),
    "drone_slot_idle.png": ("03_drone_tray.png", (0, 0, 0, 0)),
    "drone_slot_busy.png": ("03_drone_tray.png", (0, 0, 0, 0)),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    extracted = 0
    for out_name, (src_name, box) in CROPS.items():
        src = ASSETS / src_name
        if not src.exists():
            print(f"SKIP {out_name}: missing {src}")
            continue
        if box == (0, 0, 0, 0):
            print(f"SKIP {out_name}: crop not set — run calibrate_scouting_flow.py")
            continue
        im = Image.open(src)
        im.crop(box).save(OUT / out_name)
        print(f"OK {out_name} from {src_name} box={box}")
        extracted += 1

    if extracted == 0:
        print("\nNo templates extracted. Run: python3 scripts/dev/calibrate_scouting_flow.py")
        sys.exit(1)
    print(f"\nExtracted {extracted} template(s) to {OUT}")


if __name__ == "__main__":
    main()
