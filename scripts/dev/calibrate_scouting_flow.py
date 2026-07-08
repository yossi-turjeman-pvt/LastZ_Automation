#!/usr/bin/env python3
"""
Interactive calibration wizard for the Scouting flow.

Guides you through capturing reference screenshots and recording click
positions to produce templates and OCR crop regions in config.yaml.

Usage (game focused in wilderness):
    cd /Users/yossiturjeman/LastZ_Automation
    python3 scripts/dev/calibrate_scouting_flow.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS = PROJECT_ROOT / "assets" / "scouting"
TEMPLATES = PROJECT_ROOT / "templates" / "active"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

sys.path.insert(0, str(PROJECT_ROOT))


def _prompt(msg: str) -> str:
    return input(f"\n{msg}\n> ").strip()


def _mouse_position() -> tuple[int, int]:
    script = 'tell application "System Events" to get {mouse location}'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("Could not read mouse position — grant Accessibility to Terminal.")
    parts = r.stdout.strip().replace("{", "").replace("}", "").split(",")
    return int(parts[0].strip()), int(parts[1].strip())


def _capture(name: str) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    path = ASSETS / name
    ret = subprocess.run(["screencapture", "-x", str(path)])
    if ret.returncode != 0:
        raise RuntimeError("screencapture failed — grant Screen Recording permission.")
    print(f"  Saved {path}")
    return path


def _crop_around(path: Path, cx: int, cy: int, half: int, out_name: str) -> Path:
    """Crop a square region around logical click (approximate — full screen capture)."""
    img = cv2.imread(str(path))
    if img is None:
        raise RuntimeError(f"Could not read {path}")
    # screencapture is physical pixels; mouse is logical — scale by 2 on Retina
    from lastz.screen import capture_both, pixel_ratio

    capture_both()
    ratio = pixel_ratio()
    px, py = int(cx * ratio), int(cy * ratio)
    h, w = img.shape[:2]
    x1 = max(0, px - half)
    y1 = max(0, py - half)
    x2 = min(w, px + half)
    y2 = min(h, py + half)
    crop = img[y1:y2, x1:x2]
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    out = TEMPLATES / out_name
    cv2.imwrite(str(out), crop)
    print(f"  Template {out} ({crop.shape[1]}x{crop.shape[0]})")
    return out


def _update_config(updates: dict) -> None:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    scouting = cfg.setdefault("scouting", {})
    scouting.update(updates)
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
    print(f"  Updated config.yaml scouting section")


def main() -> None:
    print("=" * 60)
    print("  SCOUTING FLOW CALIBRATION WIZARD")
    print("=" * 60)
    print("Focus the game in WILDERNESS mode. Press Enter at each step.")

    _prompt("Step 1: Wilderness map visible near your HQ. Press Enter to capture.")
    map_path = _capture("01_wilderness_map.png")

    _prompt("Step 2: Click an ENEMY HQ (not your alliance), then press Enter.")
    ex, ey = _mouse_position()
    print(f"  Enemy HQ click at logical ({ex}, {ey})")
    _crop_around(map_path, ex, ey, 40, "wilderness_enemy_hq.png")

    _prompt("Step 3: With HQ modal open, press Enter to capture modal.")
    modal_path = _capture("02_hq_modal.png")

    _prompt("Step 4: Click the SCOUT icon below the HQ preview, then Enter.")
    sx, sy = _mouse_position()
    _crop_around(modal_path, sx, sy, 35, "scout_action_btn.png")

    _prompt("Step 5: Click center of POWER text in modal, then Enter.")
    px, py = _mouse_position()
    from lastz.screen import capture_both, pixel_ratio

    capture_both()
    ratio = pixel_ratio()
    ppx, ppy = int(px * ratio), int(py * ratio)
    power_crop = [ppx - 80, ppy - 12, 160, 28]

    _prompt("Step 6: Click ALLIANCE text in modal, then Enter.")
    ax, ay = _mouse_position()
    apx, apy = int(ax * ratio), int(ay * ratio)
    alliance_crop = [apx - 100, apy - 12, 200, 28]

    _prompt("Step 7: Drone tray visible (idle + busy). Press Enter to capture.")
    drone_path = _capture("03_drone_tray.png")

    _prompt("Step 8: Click an IDLE drone slot, then Enter.")
    ix, iy = _mouse_position()
    _crop_around(drone_path, ix, iy, 30, "drone_slot_idle.png")

    _prompt("Step 9: Click a BUSY drone slot (if visible), then Enter (or type skip).")
    if _prompt("Type 'skip' to skip busy drone, or Enter after clicking busy slot:") != "skip":
        bx, by = _mouse_position()
        _crop_around(drone_path, bx, by, 30, "drone_slot_busy.png")

    _prompt("Step 10 (optional v2): Open a scout mail. Enter to capture, or type skip.")
    if _prompt("Type 'skip' or Enter to capture scout mail:") != "skip":
        _capture("04_scout_mail.png")

    report = {
        "enemy_hq_click_logical": [ex, ey],
        "scout_click_logical": [sx, sy],
        "power_crop_physical": power_crop,
        "alliance_crop_physical": alliance_crop,
    }
    report_path = ASSETS / "calibration_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\n  Report: {report_path}")

    _update_config({
        "modal_power_crop": power_crop,
        "modal_alliance_crop": alliance_crop,
    })

    md = ASSETS / "calibration_report.md"
    md.write_text(
        "# Scouting calibration\n\n"
        f"- Enemy HQ click (logical): `{ex}, {ey}`\n"
        f"- Scout button click (logical): `{sx}, {sy}`\n"
        f"- modal_power_crop: `{power_crop}`\n"
        f"- modal_alliance_crop: `{alliance_crop}`\n"
    )
    print(f"  Markdown report: {md}")
    print("\nCalibration complete. Run verify_scouting_templates.py next.")


if __name__ == "__main__":
    main()
