"""
Flow 3 — Battle Rewards (Dynamic Orange Chest).

Steps:
  1. Focus game and reset UI
  2. Capture screen and match the orange badge icon
  3. If found: open the Battle Rewards modal
  4. Match and click the universal Claim All button inside the modal
  5. Dismiss the rewards overlay
  6. Close the modal
"""
import time

from lastz.config import coord_offset, threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.input import click, ensure_game_running, focus_game
from lastz.screen import capture, physical_to_logical, scale_capture_offset
from lastz.vision import find_template


def run_battle_rewards_flow() -> None:
    ensure_game_running()
    focus_game()

    print("Resetting game UI...")
    reset_ui(clicks=1, delay=1.0)

    screen = capture()
    orange_match = find_template(
        screen,
        "orange_icon_no_badge.png",
        cfg_threshold("orange_icon"),
    )

    if orange_match is None:
        print("-> Dynamic orange chest badge icon is NOT present on screen right now.")
        return

    # Apply the configured offset so we click inside the chest, not the badge
    ox, oy = coord_offset("battle_rewards_offset")
    sox, soy = scale_capture_offset(ox, oy)
    lx, ly = physical_to_logical(orange_match.phys_x + sox, orange_match.phys_y + soy)

    print(f"-> Found dynamic orange chest at logical ({lx:.1f}, {ly:.1f}). Opening Battle Rewards...")
    click(lx, ly)
    time.sleep(2.5)

    screen_modal = capture()
    claim_match = find_template(
        screen_modal,
        "universal_claim_all_button.png",
        cfg_threshold("claim_all"),
    )

    if claim_match is not None:
        clx, cly = physical_to_logical(claim_match.phys_x, claim_match.phys_y)
        print(f"-> Clicking 'Claim All' at logical ({clx:.1f}, {cly:.1f})...")
        click(clx, cly)
        time.sleep(2.0)
        print("Dismissing rewards overlay...")
        dismiss_overlay()
    else:
        print("-> No 'Claim All' button found inside Battle Rewards modal.")

    print("Closing Battle Rewards modal...")
    dismiss_overlay()
    print("Battle Rewards flow complete!")
