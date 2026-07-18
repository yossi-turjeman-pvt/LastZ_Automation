# Flows

## Alliance Gifts

**Entry:** menu `1`, watcher loop (`2` / `lastz_watcher.py`), or `from lastz.flows.alliance_gifts import run_alliance_gifts_flow`.

### Steps

1. Ensure the game is running and focused.
2. `reset_ui` — a few outside clicks (`coordinates.dismiss_outside`) to close stray modals.
3. Click **Alliance** — `alliance_shield_clean.png`.
4. Click **Alliance Gifts** — `alliance_gifts_precise.png`.
5. **Common tab**
   - Prefer **Claim All** (`claim_all_button_clean.png` or `universal_claim_all_button.png`).
   - If Claim All is used, dismiss the reward overlay once, then continue.
   - Otherwise claim individual gifts via `claim_button_clean.png` (up to 15).
6. Switch to **Rare** — `rare_tab.png`.
7. **Rare tab** — individual `claim_button_clean.png` clicks in the gift list only.
   - Matches in the modal footer (back / trash / notifications band, below ~52% of screen height) are **ignored**. Closing is done by outside clicks, not the back icon.
8. Outside click — close Alliance Gifts.
9. Outside click — close Alliance menu.

### Templates (`templates/active/`)

| File | Used for |
|------|----------|
| `alliance_shield_clean.png` | Open Alliance menu |
| `alliance_gifts_precise.png` | Open Gifts window |
| `rare_tab.png` | Switch to Rare |
| `claim_all_button_clean.png` | Common Claim All |
| `universal_claim_all_button.png` | Alternate Claim All |
| `claim_button_clean.png` | Per-gift Claim |
| `hq_world_button.png` | Watcher: leave HQ → wilderness |
| `wilderness_hq_button.png` | Vision scale calibration anchor |

### Config keys

- `thresholds.claim_all`, `claim_button`, `alliance_shield`, `alliance_gifts`, `rare_tab`, `hq_world_button`
- `coordinates.dismiss_outside`
- `watcher.alliance_interval_sec` (watcher only)
