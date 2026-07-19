# Flows

## Alliance Gifts (includes Battlefield)

**Entry:** menu `1`, watcher loop (`2` / `lastz_watcher.py`), or `from lastz.flows.alliance_gifts import run_alliance_gifts_flow`.

One flow. Not a separate menu item. Clicks are full-dynamic (template centers + window-fraction dismiss).

### Steps

1. Ensure the game is running and focused.
2. `reset_ui` — outside clicks at `coordinates.dismiss_outside_frac` of the game window.
3. **Battlefield Gifts** (wilderness map chest icon) — if `orange_icon_no_badge.png` is found:
   - Click the **match center**
   - Claim All via `universal_claim_all_button.png` when present
   - Outside dismiss to clear reward overlay + close modal  
   If the chest is absent, skip and continue.
4. Click **Alliance** — `alliance_shield_clean.png`.
5. Click **Alliance Gifts** — `alliance_gifts_precise.png`.
6. **Common tab**
   - Prefer **Claim All** (`claim_all_button_clean.png` or `universal_claim_all_button.png`).
   - If Claim All is used, dismiss the reward overlay once, then continue.
   - Otherwise claim individual gifts via `claim_button_clean.png` (up to 15).
7. Switch to **Rare** — `rare_tab.png`.
8. **Rare tab** — individual `claim_button_clean.png` clicks in the gift list only.
   - Matches in the modal footer (back / trash / notifications band, below ~52% of screen height) are **ignored**. Closing is done by outside clicks, not the back icon.
9. Outside click — close Alliance Gifts.
10. Outside click — close Alliance menu.

### Templates (`templates/active/`)

| File | Used for |
|------|----------|
| `orange_icon_no_badge.png` | Battlefield Gifts chest on wilderness map |
| `alliance_shield_clean.png` | Open Alliance menu (+ scale anchor) |
| `alliance_gifts_precise.png` | Open Gifts window |
| `rare_tab.png` | Switch to Rare |
| `claim_all_button_clean.png` | Common Claim All |
| `universal_claim_all_button.png` | Claim All (Alliance + Battlefield) |
| `claim_button_clean.png` | Per-gift Claim |
| `hq_world_button.png` | Watcher leave HQ + scale anchor |
| `wilderness_hq_button.png` | Scale calibration anchor |

### Config keys

- `thresholds.orange_icon`, `claim_all`, `claim_button`, `alliance_shield`, `alliance_gifts`, `rare_tab`, `hq_world_button`
- `coordinates.dismiss_outside_frac`
- `watcher.alliance_interval_sec` (watcher only)
