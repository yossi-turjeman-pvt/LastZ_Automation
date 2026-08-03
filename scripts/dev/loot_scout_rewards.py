"""
Scout Battlefield / Trucks / Drone reward UIs for loot-tracking planning.
Temporary dev script — does NOT modify production flows.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

from lastz.config import threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, ensure_wilderness, reset_ui
from lastz.flows.drone_gift import (
    _find_chest,
    _gate_timer_reads,
    _min_duration,
    _wait_for_button,
)
from lastz.flows.hq_nav import is_hq_mode, navigate_to_hq, navigate_to_wilderness
from lastz.flows.trucks import _claim_arrived, _open_trucks, _switch_my_truck
from lastz.input import GameNotRunningError, click, ensure_game_running, focus_game, press_escape
from lastz.screen import capture, capture_both, physical_to_logical
from lastz.vision import ensure_template_scale, find_template

OUT = Path("logs/debug/flow")
OUT.mkdir(parents=True, exist_ok=True)

SAVED: list[str] = []
RESULTS: dict[str, str] = {}


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


def cleanup_ui() -> None:
    print("[loot_scout] Cleanup: dismiss + Escape...")
    dismiss_overlay(delay=0.8)
    press_escape()
    time.sleep(0.6)
    press_escape()
    time.sleep(0.6)


def scout_battlefield() -> None:
    print("\n=== Battlefield gifts ===")
    ensure_wilderness()
    color, gray = capture_both()
    save("loot_scout_bf_00_wilderness.png", color)

    orange = find_template(gray, "orange_icon_no_badge.png", cfg_threshold("orange_icon"))
    if orange is None:
        print("[loot_scout] Battlefield: orange chest not visible — unavailable")
        RESULTS["battlefield"] = "unavailable"
        return

    lx, ly = physical_to_logical(orange.phys_x, orange.phys_y)
    print(f"[loot_scout] Opening battlefield chest at ({lx:.1f}, {ly:.1f})")
    click(lx, ly)
    time.sleep(2.5)

    modal = capture()
    save("loot_scout_bf_01_modal.png", modal)

    claim = find_template(modal, "universal_claim_all_button.png", cfg_threshold("claim_all"))
    if claim is None:
        print("[loot_scout] Battlefield: no Claim All in modal")
        save("loot_scout_bf_unavailable.png", modal)
        RESULTS["battlefield"] = "modal_no_claim_all"
        dismiss_overlay()
        dismiss_overlay()
        return

    clx, cly = physical_to_logical(claim.phys_x, claim.phys_y)
    print(f"[loot_scout] Claim All at ({clx:.1f}, {cly:.1f})")
    click(clx, cly)
    time.sleep(1.25)
    reward = capture()
    save("loot_scout_bf_02_reward.png", reward)
    save_center_crop("loot_scout_bf_02_reward_crop.png", reward)
    RESULTS["battlefield"] = "claimed"
    print("[loot_scout] Dismissing battlefield reward...")
    dismiss_overlay(delay=1.2)
    save("loot_scout_bf_03_after_reward_dismiss.png", capture())
    dismiss_overlay(delay=1.0)
    save("loot_scout_bf_04_after_modal_close.png", capture())


def scout_trucks() -> None:
    print("\n=== Trucks claim rewards ===")
    ensure_wilderness()
    color, gray = capture_both()
    save("loot_scout_truck_00_wilderness.png", color)

    if not _open_trucks():
        print("[loot_scout] Trucks: icon not found — unavailable")
        save("loot_scout_truck_unavailable.png", capture())
        RESULTS["trucks"] = "unavailable_icon"
        return

    time.sleep(1.0)
    save("loot_scout_truck_01_open.png", capture())

    if not _switch_my_truck():
        print("[loot_scout] Trucks: My Truck tab failed")
        RESULTS["trucks"] = "my_truck_tab_fail"
        cleanup_ui()
        return

    time.sleep(1.0)
    color, gray = capture_both()
    save("loot_scout_truck_02_my_truck.png", color)

    thr = cfg_threshold("trucks_claim_chest")
    h, w = gray.shape[:2]
    chest = find_template(gray, "trucks_claim_chest.png", thr)
    if chest is None or not (
        0.15 <= chest.phys_y / h <= 0.60 and 0.25 <= chest.phys_x / w <= 0.75
    ):
        print("[loot_scout] Trucks: no claimable golden chest on My Truck")
        save("loot_scout_truck_unavailable.png", color)
        RESULTS["trucks"] = "unavailable_no_chest"
        cleanup_ui()
        return

    lx, ly = physical_to_logical(chest.phys_x, chest.phys_y)
    print(f"[loot_scout] Click claim chest at ({lx:.1f}, {ly:.1f})")
    click(lx, ly)
    time.sleep(1.25)
    reward = capture()
    save("loot_scout_truck_02_reward.png", reward)
    save_center_crop("loot_scout_truck_02_reward_crop.png", reward)
    RESULTS["trucks"] = "claimed"
    print("[loot_scout] Dismissing truck reward...")
    dismiss_overlay(delay=1.4)
    save("loot_scout_truck_03_after_dismiss.png", capture())
    # Back out of details if needed
    color2, gray2 = capture_both()
    back = find_template(gray2, "trucks_details_back.png", cfg_threshold("trucks_details_back"))
    if back is not None and 0.70 <= back.phys_y / gray2.shape[0] <= 0.92:
        blx, bly = physical_to_logical(back.phys_x, back.phys_y)
        click(blx, bly)
        time.sleep(1.0)
    cleanup_ui()


def scout_drone() -> None:
    print("\n=== HQ Drone idle reward ===")
    _, screen = capture_both()
    if not is_hq_mode(screen):
        print("[loot_scout] Navigating to HQ...")
        if not navigate_to_hq(screen):
            save("loot_scout_drone_unavailable.png", capture())
            RESULTS["drone"] = "unavailable_hq_nav"
            return
        time.sleep(2.0)

    color, gray = capture_both()
    save("loot_scout_drone_00_hq.png", color)

    min_sec = _min_duration()
    ready, chest_match, _readings, detail = _gate_timer_reads(min_sec, attempts=2)
    if chest_match is None:
        print("[loot_scout] Drone: no chest visible")
        save("loot_scout_drone_unavailable.png", color)
        RESULTS["drone"] = "unavailable_no_chest"
        navigate_to_wilderness()
        return

    if not ready:
        print(f"[loot_scout] Drone: not ready ({detail})")
        save("loot_scout_drone_unavailable.png", color)
        RESULTS["drone"] = f"unavailable_not_ready_{detail}"
        navigate_to_wilderness()
        return

    # Open chest modal
    fresh_chest = _find_chest(gray) or chest_match
    lx, ly = physical_to_logical(fresh_chest.phys_x, fresh_chest.phys_y)
    print(f"[loot_scout] Click drone chest at ({lx:.1f}, {ly:.1f})")
    click(lx, ly)
    time.sleep(2.0)
    save("loot_scout_drone_01_modal.png", capture())

    from lastz.flows.drone_gift import (
        _CLAIM_TEMPLATES,
        _COLLECT_TEMPLATES,
    )

    claim_thresh = cfg_threshold("drone_claim_btn")
    collect_thresh = cfg_threshold("drone_collect_btn")

    claim_match = _wait_for_button(
        list(_CLAIM_TEMPLATES), claim_thresh, timeout_sec=6.0, label="claim button"
    )
    if claim_match is not None:
        clx, cly = physical_to_logical(claim_match.phys_x, claim_match.phys_y)
        print(f"[loot_scout] Drone Claim at ({clx:.1f}, {cly:.1f})")
        click(clx, cly)
        time.sleep(2.0)
        save("loot_scout_drone_02_after_claim.png", capture())

    collect_match = _wait_for_button(
        list(_COLLECT_TEMPLATES), collect_thresh, timeout_sec=6.0, label="collect button"
    )
    if collect_match is None:
        print("[loot_scout] Drone: Collect button not found")
        save("loot_scout_drone_unavailable.png", capture())
        RESULTS["drone"] = "collect_not_found"
        dismiss_overlay(delay=1.0)
        dismiss_overlay(delay=1.0)
        navigate_to_wilderness()
        return

    colx, coly = physical_to_logical(collect_match.phys_x, collect_match.phys_y)
    print(f"[loot_scout] Drone Collect at ({colx:.1f}, {coly:.1f})")
    click(colx, coly)
    time.sleep(1.25)
    reward = capture()
    save("loot_scout_drone_02_reward.png", reward)
    save_center_crop("loot_scout_drone_02_reward_crop.png", reward)
    RESULTS["drone"] = "claimed"
    print("[loot_scout] Dismissing drone reward...")
    dismiss_overlay(delay=1.5)
    dismiss_overlay(delay=1.0)
    save("loot_scout_drone_03_after_dismiss.png", capture())
    navigate_to_wilderness()


def main() -> int:
    try:
        ensure_game_running()
    except GameNotRunningError as exc:
        print(exc)
        return 1

    focus_game()
    screen = capture()
    ensure_template_scale(screen)
    save("loot_scout_rewards_00_start.png", screen)
    reset_ui(clicks=2, delay=0.8)

    scout_battlefield()
    scout_trucks()
    scout_drone()

    cleanup_ui()
    print("\n[loot_scout] Results:")
    for k, v in RESULTS.items():
        print(f"  {k}: {v}")
    print("[loot_scout] saved files:")
    for p in SAVED:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
