"""
Alliance Gifts flow — Battlefield chest + Alliance Common/Rare tabs.

Navigation uses template matching so clicks stay accurate on any display size.
"""
import time

from lastz.config import coord_offset, threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.input import click, ensure_game_running, focus_game
from lastz.screen import capture, physical_to_logical, scale_capture_offset
from lastz.vision import click_template, find_all_templates, find_any, find_template

_MAX_INDIVIDUAL_CLAIMS = 15
# Gift-list Claim buttons sit above the modal footer (back / trash / notifications).
# Matches below this Y fraction are the back icon area — ignore them; outside dismiss closes.
_CLAIM_MAX_Y_FRAC = 0.52


def _find_list_claim_button(screen):
    """Best Claim button in the gift list; None if only footer/back-icon matches remain."""
    matches = find_all_templates(
        screen,
        "claim_button_clean.png",
        cfg_threshold("claim_button"),
    )
    if not matches:
        return None

    max_y = screen.shape[0] * _CLAIM_MAX_Y_FRAC
    list_matches = [m for m in matches if m.phys_y <= max_y]
    if not list_matches:
        best = matches[0]
        print(
            f"-> No list Claim buttons left "
            f"(best match in footer/back area y={best.phys_y:.0f}, conf={best.confidence:.4f}) — stopping"
        )
        return None
    return list_matches[0]


def _claim_tab(is_common: bool) -> str:
    if is_common:
        screen = capture()
        m = find_any(
            screen,
            ["claim_all_button_clean.png", "universal_claim_all_button.png"],
            cfg_threshold("claim_all"),
        )
        if m is not None:
            lx, ly = physical_to_logical(m.phys_x, m.phys_y)
            print(f"-> Found 'Claim All' at logical ({lx:.1f}, {ly:.1f}) [conf={m.confidence:.4f}]")
            click(lx, ly)
            time.sleep(2.0)
            dismiss_overlay()
            return "Claimed All (Instant)"

    claimed = 0
    for _ in range(_MAX_INDIVIDUAL_CLAIMS):
        screen = capture()
        m = _find_list_claim_button(screen)
        if m is None:
            break
        lx, ly = physical_to_logical(m.phys_x, m.phys_y)
        print(f"-> Claiming individual gift at logical ({lx:.1f}, {ly:.1f}) [conf={m.confidence:.4f}]")
        click(lx, ly)
        claimed += 1
        time.sleep(1.5)

    return f"Claimed {claimed} individual gifts"


def _claim_battlefield_gifts() -> str:
    """Claim Battlefield Gifts from the wilderness chest icon if present."""
    print("Checking for Battlefield Gifts chest...")
    screen = capture()
    orange_match = find_template(
        screen,
        "orange_icon_no_badge.png",
        cfg_threshold("orange_icon"),
    )

    if orange_match is None:
        print("-> Battlefield Gifts chest not on screen — skipping.")
        return "skipped"

    # Offset so we click the chest body, not the red badge number
    ox, oy = coord_offset("battle_rewards_offset")
    sox, soy = scale_capture_offset(ox, oy)
    lx, ly = physical_to_logical(orange_match.phys_x + sox, orange_match.phys_y + soy)

    print(f"-> Opening Battlefield Gifts at logical ({lx:.1f}, {ly:.1f}) [conf={orange_match.confidence:.4f}]")
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
        print("Dismissing Battlefield rewards overlay...")
        dismiss_overlay()
    else:
        print("-> No 'Claim All' button inside Battlefield Gifts modal.")

    print("Closing Battlefield Gifts modal...")
    dismiss_overlay()
    return "claimed"


def run_alliance_gifts_flow() -> None:
    ensure_game_running()
    focus_game()

    print("Resetting game UI to main base screen...")
    reset_ui(clicks=3, delay=1.5)

    # Battlefield chest lives on the wilderness map — claim before opening Alliance UI
    battlefield_status = _claim_battlefield_gifts()
    print(f"Battlefield Gifts: {battlefield_status}.")

    print("Opening Alliance menu...")
    if click_template("alliance_shield_clean.png", cfg_threshold("alliance_shield"), label="Alliance menu") is None:
        raise RuntimeError("Alliance menu button not found")
    time.sleep(2.0)

    print("Opening Alliance Gifts window...")
    if click_template("alliance_gifts_precise.png", cfg_threshold("alliance_gifts"), label="Alliance Gifts") is None:
        raise RuntimeError("Alliance Gifts button not found")
    time.sleep(2.0)

    print("Processing Common tab...")
    common_status = _claim_tab(is_common=True)
    print(f"Common tab complete: {common_status}.")

    print("Switching to Rare tab...")
    if click_template("rare_tab.png", cfg_threshold("rare_tab"), label="Rare tab") is None:
        raise RuntimeError("Rare tab not found")
    time.sleep(2.0)

    print("Processing Rare tab...")
    rare_status = _claim_tab(is_common=False)
    print(f"Rare tab complete: {rare_status}.")

    print("Closing Alliance Gifts window...")
    dismiss_overlay(delay=3.0)

    print("Closing Alliance Menu window...")
    dismiss_overlay(delay=3.0)

    print("Alliance Gifts Claim flow complete!")
