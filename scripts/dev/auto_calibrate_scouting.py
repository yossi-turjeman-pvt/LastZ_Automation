#!/usr/bin/env python3
"""Automated scouting calibration — navigate, click HQs, export templates."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import yaml

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.flows.hq_nav import is_hq_mode, navigate_to_wilderness
from lastz.input import ensure_game_running, focus_game
from lastz.scouting.map_nav import depart_home_city, enter_sector, pan_logical, zoom_in, zoom_out
from lastz.scouting.map_scan import scan_map_labels
from lastz.scouting.modal_detect import is_player_hq_modal
from lastz.screen import capture_both, click_capture_phys

ASSETS = PROJECT / "assets" / "scouting"
TEMPLATES = PROJECT / "templates" / "active"
CONFIG = PROJECT / "config.yaml"

# Known click points from find_enemies.png (capture pixels) — px78/FiK cluster
REF_HQ_CLICKS = [
    (2035, 380),  # [FiK]NTQ99 area
    (1875, 380),  # [px78]Doomcreeper
    (1715, 380),  # [FiK]ZombiefeveR7
    (1555, 380),  # [px78]azi777
    (1395, 380),  # [px78]PrinceJIB
    (1235, 380),  # [px78]Hussein Ali
]


def _save_templates_from_modal(color, hq_px: float, hq_py: float) -> bool:
    h, w = color.shape[:2]
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(ASSETS / "hq_modal_calibrated.png"), color)

    hx, hy = int(hq_px), int(hq_py + 45)
    half = 50
    hq_crop = color[max(0, hy - half) : min(h, hy + half), max(0, hx - half) : min(w, hx + half)]
    if hq_crop.size < 100:
        return False
    cv2.imwrite(str(TEMPLATES / "wilderness_enemy_hq.png"), hq_crop)

    row = color[int(h * 0.52) : int(h * 0.72), int(w * 0.30) : int(w * 0.70)]
    cv2.imwrite(str(ASSETS / "modal_action_row.png"), row)
    rh, rw = row.shape[:2]
    scout = row[int(rh * 0.12) : int(rh * 0.88), int(rw * 0.02) : int(rw * 0.26)]
    if scout.size > 100:
        cv2.imwrite(str(TEMPLATES / "scout_action_btn.png"), scout)

    panel = color[int(h * 0.30) : int(h * 0.62), int(w * 0.28) : int(w * 0.52)]
    cv2.imwrite(str(ASSETS / "modal_stats_panel.png"), panel)
    ph, pw = panel.shape[:2]
    power_crop = [int(w * 0.28), int(h * 0.38), int(pw * 0.85), 42]
    alliance_crop = [int(w * 0.28), int(h * 0.50), int(pw * 0.95), 42]

    with open(CONFIG) as f:
        cfg = yaml.safe_load(f)
    scouting = cfg.setdefault("scouting", {})
    scouting["modal_power_crop"] = power_crop
    scouting["modal_alliance_crop"] = alliance_crop
    with open(CONFIG, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)

    print(f"  HQ template {hq_crop.shape[1]}x{hq_crop.shape[0]}")
    print(f"  Scout template {scout.shape[1]}x{scout.shape[0]}")
    return True


def _interesting_hit(hit, blacklist: set[str], own: str) -> bool:
    tag = (hit.alliance_tag or "").upper()
    if not tag or len(tag) < 2:
        return False
    if own and tag == own.upper():
        return False
    if tag in blacklist:
        return False
    return True


def _try_click_hq(px: float, py: float) -> bool:
    dismiss_overlay(delay=0.3)
    click_capture_phys(px, py + 40)
    time.sleep(1.8)
    color, _ = capture_both()
    if is_player_hq_modal(color):
        return _save_templates_from_modal(color, px, py)
    dismiss_overlay(delay=0.5)
    return False


def _navigate_to_enemy_cluster() -> None:
    ref = cv2.imread(str(ASSETS / "find_enemies.png"))
    depart_home_city()
    if ref is None:
        for dx, dy in [(700, 0), (700, 0), (0, -450)]:
            pan_logical(dx, dy)
        zoom_in(steps=5)
        return

    rh, rw = ref.shape[:2]
    ref_crop = ref[int(rh * 0.12) : int(rh * 0.48), int(rw * 0.22) : int(rw * 0.72)]
    cv2.imwrite(str(ASSETS / "ref_cluster_crop.png"), ref_crop)

    for i, (dx, dy) in enumerate(
        [(700, 0), (700, 0), (0, -450), (0, -200), (300, 0), (-300, 100)]
    ):
        pan_logical(dx, dy)
        zoom_in(steps=5)
        time.sleep(0.8)
        color, _ = capture_both()
        h, w = color.shape[:2]
        live = color[int(h * 0.12) : int(h * 0.48), int(w * 0.22) : int(w * 0.72)]
        if live.shape[0] >= ref_crop.shape[0] and live.shape[1] >= ref_crop.shape[1]:
            score = float(cv2.matchTemplate(live, ref_crop, cv2.TM_CCOEFF_NORMED).max())
            print(f"  nav step {i}: cluster match {score:.3f}")
            if score >= 0.30:
                return
        zoom_out(steps=3)


def _calibrate_loop(blacklist: set[str], own: str) -> bool:
    for attempt in range(10):
        color, _ = capture_both()
        cv2.imwrite(str(ASSETS / f"cal_attempt_{attempt}.png"), color)

        for px, py in REF_HQ_CLICKS:
            print(f"  ref click @({px},{py})")
            if _try_click_hq(px, py):
                return True

        hits = scan_map_labels(color, kind="hq")
        targets = [h for h in hits if _interesting_hit(h, blacklist, own)]
        print(f"attempt {attempt}: {len(targets)} OCR targets")
        for h in targets[:10]:
            print(f"  -> {h.alliance_tag} @({h.phys_x:.0f},{h.phys_y:.0f})")
            if _try_click_hq(h.phys_x, h.phys_y):
                return True

        pan_logical(180, -120)

    enter_sector(1)
    color, _ = capture_both()
    for h in scan_map_labels(color, kind="hq"):
        if _interesting_hit(h, blacklist, own) and _try_click_hq(h.phys_x, h.phys_y):
            return True
    return False


def main() -> None:
    ensure_game_running()
    focus_game()
    time.sleep(1)
    if is_hq_mode(capture_both()[1]):
        navigate_to_wilderness()
        time.sleep(2)
    reset_ui(2, 0.8)

    with open(CONFIG) as f:
        cfg = yaml.safe_load(f)
    sc = cfg.get("scouting", {})
    own = (sc.get("own_alliance") or "").upper()
    blacklist = {t.upper() for t in sc.get("alliance_blacklist", [])}

    _navigate_to_enemy_cluster()
    if _calibrate_loop(blacklist, own):
        print("SUCCESS — templates saved")
    else:
        print("FAILED — check assets/scouting/cal_attempt_*.png")


if __name__ == "__main__":
    main()
