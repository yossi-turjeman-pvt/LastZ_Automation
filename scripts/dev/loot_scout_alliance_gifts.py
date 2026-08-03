"""
Scout Alliance Gifts reward popup for loot-tracking planning.
Temporary dev script — does NOT modify production flows.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

from lastz.config import threshold as cfg_threshold
from lastz.debug_match import annotate_and_save, in_band
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.flows.ui_bands import BAND_ALLIANCE_GRID, BAND_HUD_SHIELD, BAND_RARE_TAB
from lastz.input import GameNotRunningError, click, ensure_game_running, focus_game, press_escape
from lastz.screen import capture, capture_both, physical_to_logical
from lastz.vision import ensure_template_scale, find_all_templates, find_any, find_template

OUT = Path("logs/debug/flow")
OUT.mkdir(parents=True, exist_ok=True)

SAVED: list[str] = []


def save(name: str, color) -> Path:
    path = OUT / name
    cv2.imwrite(str(path), color)
    SAVED.append(str(path))
    print(f"[loot_scout] saved {path} {color.shape}")
    return path


def save_center_crop(name: str, color, frac: float = 0.55) -> Path:
    h, w = color.shape[:2]
    ch, cw = int(h * frac), int(w * frac)
    y0 = (h - ch) // 2
    x0 = (w - cw) // 2
    crop = color[y0 : y0 + ch, x0 : x0 + cw]
    return save(name, crop)


def band_ok(match, h: int, w: int, band: tuple[float, float, float, float]) -> bool:
    y0, y1, x0, x1 = band
    return in_band(match.phys_x, match.phys_y, h, w, y0, y1, x0, x1)


def open_alliance_gifts() -> bool:
    color, gray = capture_both()
    h, w = gray.shape[:2]
    shields = find_all_templates(
        gray, "alliance_shield_clean.png", cfg_threshold("alliance_shield")
    )
    hud = [m for m in shields if band_ok(m, h, w, BAND_HUD_SHIELD)]
    if not hud:
        print("[loot_scout] FAIL: alliance shield not in HUD band")
        annotate_and_save(color, "loot_scout_shield_miss", [], subdir="flow")
        return False
    hud.sort(key=lambda m: m.confidence, reverse=True)
    m = hud[0]
    lx, ly = physical_to_logical(m.phys_x, m.phys_y)
    print(f"[loot_scout] Click alliance shield logical ({lx:.1f}, {ly:.1f})")
    click(lx, ly)
    time.sleep(2.0)

    color, gray = capture_both()
    h, w = gray.shape[:2]
    gifts = find_all_templates(
        gray, "alliance_gifts_precise.png", cfg_threshold("alliance_gifts")
    )
    gifts_in = [m for m in gifts if band_ok(m, h, w, BAND_ALLIANCE_GRID)]
    if not gifts_in:
        print("[loot_scout] FAIL: alliance gifts tile not found")
        annotate_and_save(color, "loot_scout_gifts_miss", [], subdir="flow")
        return False
    gifts_in.sort(key=lambda m: m.confidence, reverse=True)
    g = gifts_in[0]
    lx, ly = physical_to_logical(g.phys_x, g.phys_y)
    print(f"[loot_scout] Click alliance gifts logical ({lx:.1f}, {ly:.1f})")
    click(lx, ly)
    time.sleep(2.0)
    return True


def find_claim_all(gray):
    return find_any(
        gray,
        ["claim_all_button_clean.png", "universal_claim_all_button.png"],
        cfg_threshold("claim_all"),
    )


def claim_and_capture(prefix: str) -> str:
    """Return 'claim_all', 'individual', or 'none'."""
    color, gray = capture_both()
    save(f"loot_scout_01_gifts_{prefix}.png", color)

    claim_all = find_claim_all(gray)
    if claim_all is not None:
        lx, ly = physical_to_logical(claim_all.phys_x, claim_all.phys_y)
        print(f"[loot_scout] Claim All at logical ({lx:.1f}, {ly:.1f}) conf={claim_all.confidence:.4f}")
        click(lx, ly)
        time.sleep(1.25)
        reward = capture()
        save(f"loot_scout_02_reward_{prefix}.png", reward)
        save_center_crop(f"loot_scout_02_reward_{prefix}_crop.png", reward)
        print("[loot_scout] Dismissing reward popup (single outside click)...")
        dismiss_overlay(delay=1.2)
        after = capture()
        save(f"loot_scout_03_after_dismiss_{prefix}.png", after)
        return "claim_all"

    # Individual claim — one only
    from lastz.flows.alliance_gifts import _find_list_claim_button

    color, gray = capture_both()
    m = _find_list_claim_button(gray, color)
    if m is None:
        print(f"[loot_scout] No Claim All or individual Claim on {prefix}")
        save(f"loot_scout_01_gifts_{prefix}_list_only.png", color)
        return "none"

    lx, ly = physical_to_logical(m.phys_x, m.phys_y)
    print(f"[loot_scout] Individual Claim at logical ({lx:.1f}, {ly:.1f})")
    click(lx, ly)
    time.sleep(1.25)
    reward = capture()
    save(f"loot_scout_02_reward_{prefix}.png", reward)
    save_center_crop(f"loot_scout_02_reward_{prefix}_crop.png", reward)
    dismiss_overlay(delay=1.2)
    after = capture()
    save(f"loot_scout_03_after_dismiss_{prefix}.png", after)
    return "individual"


def switch_to_rare() -> bool:
    thr = cfg_threshold("rare_tab")
    for attempt in range(3):
        color, gray = capture_both()
        h, w = gray.shape[:2]
        m = find_template(gray, "rare_tab.png", thr)
        if m is None:
            print(f"[loot_scout] rare_tab miss attempt {attempt + 1}")
            continue
        if not band_ok(m, h, w, BAND_RARE_TAB):
            print(f"[loot_scout] rare_tab outside band attempt {attempt + 1}")
            continue
        lx, ly = physical_to_logical(m.phys_x, m.phys_y)
        print(f"[loot_scout] Click Rare tab logical ({lx:.1f}, {ly:.1f})")
        click(lx, ly)
        time.sleep(1.8)
        return True
    return False


def cleanup_ui() -> None:
    print("[loot_scout] Cleanup: dismiss + Escape...")
    dismiss_overlay(delay=1.0)
    press_escape()
    time.sleep(0.8)
    press_escape()
    time.sleep(0.8)


def main() -> int:
    try:
        ensure_game_running()
    except GameNotRunningError as exc:
        print(exc)
        return 1

    focus_game()
    screen = capture()
    ensure_template_scale(screen)
    save("loot_scout_00_start.png", screen)

    reset_ui(clicks=2, delay=0.8)

    if not open_alliance_gifts():
        cleanup_ui()
        return 2

    common_result = claim_and_capture("common")

    rare_result = "skipped"
    if switch_to_rare():
        save("loot_scout_04_rare_tab.png", capture())
        rare_result = claim_and_capture("rare")
    else:
        print("[loot_scout] Could not switch to Rare tab")

    cleanup_ui()
    print(f"[loot_scout] common={common_result} rare={rare_result}")
    print("[loot_scout] saved files:")
    for p in SAVED:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
