"""
Diagnose scouting OCR — dumps processed label crops from live screen.

Usage:
    python3 scripts/dev/diagnose_scouting_ocr.py

With HQ modal open, also tests modal Alliance/Power regions from config.yaml.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lastz.config import scouting_cfg
from lastz.input import focus_game
from lastz.scouting.ocr_labels import ocr_map_label_at, ocr_modal_fields
from lastz.screen import capture_both
from lastz.vision import find_all_templates

DEBUG = PROJECT_ROOT / "logs" / "scouting_ocr_debug"


def main() -> None:
    DEBUG.mkdir(parents=True, exist_ok=True)
    focus_game()
    color, gray = capture_both()
    cfg = scouting_cfg()
    offset = cfg.get("name_label_crop_offset", [-90, -55, 220, 70])

    thresh = 0.55
    tpl = "wilderness_enemy_hq.png"
    matches = find_all_templates(gray, tpl, thresh)
    print(f"Found {len(matches)} HQ candidate(s) with {tpl}\n")

    for i, m in enumerate(matches[:5]):
        label = ocr_map_label_at(
            color, m.phys_x, m.phys_y, offset,
            debug_dir=DEBUG, debug_prefix=f"map_{i}",
        )
        print(f"[{i}] conf={m.confidence:.3f} label={label.display_name!r} "
              f"level={label.hq_level} alliance={label.alliance_tag}")
        print(f"     raw: {label.raw_text!r}\n")

    alliance_crop = cfg.get("modal_alliance_crop", [0, 0, 0, 0])
    power_crop = cfg.get("modal_power_crop", [0, 0, 0, 0])
    if any(alliance_crop) or any(power_crop):
        modal = ocr_modal_fields(color, alliance_crop, power_crop, debug_dir=DEBUG)
        print(f"Modal alliance={modal.alliance_tag!r} raw={modal.alliance_raw!r}")
        print(f"Modal power={modal.power} raw={modal.power_raw!r}")
    else:
        print("Modal OCR crops not calibrated — run calibrate_scouting_flow.py")

    print(f"\nDebug images: {DEBUG}")


if __name__ == "__main__":
    main()
