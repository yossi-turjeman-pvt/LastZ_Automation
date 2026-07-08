# Flows Reference

## Flow 1 & 2 — Alliance Gifts

**File**: `lastz/flows/alliance_gifts.py`
**Menu option**: 1 (or step 1 of the Full Loop)

### What it does

Claims all available gifts from the Alliance Gifts window — both Common tab (with a "Claim All" shortcut if available) and Rare tab (individual Claim buttons one at a time).

### Steps

1. **Focus game** — bring Survival.exe to foreground
2. **Reset UI** — click outside 3 times to dismiss any open modal, returning to the main base map
3. **Open Alliance Menu** — click at `coordinates.alliance_menu` (logical `[1480, 757]`)
4. **Open Alliance Gifts window** — click at `coordinates.alliance_gifts_button` (logical `[887, 650]`)
5. **Common tab claim**:
   - Screenshot → try to match `claim_all_button_clean.png` or `universal_claim_all_button.png`
   - If found: click Claim All, wait 2s, dismiss overlay → done instantly
   - If not found: loop matching `claim_button_clean.png` up to 15 times, clicking each
6. **Switch to Rare tab** — click at `coordinates.rare_tab` (logical `[950, 390]`)
7. **Rare tab claim** — same individual Claim button loop (no Claim All on Rare tab)
8. **Close Gifts window** — click outside, wait 3s
9. **Close Alliance Menu** — click outside, wait 3s

### Expected output (success)

```
Activating game window (Survival.exe)...
Resetting game UI to main base screen...
Opening Alliance menu...
Opening Alliance Gifts window...
Processing Common tab...
[vision] 'claim_all_button_clean.png' match confidence = 0.9312 (threshold 0.82)
-> Found 'Claim All' at logical (756.0, 912.0) [conf=0.9312]
Common tab complete: Claimed All (Instant).
Switching to Rare tab...
Processing Rare tab...
[vision] 'claim_button_clean.png' match confidence = 0.3201 (threshold 0.85)
Rare tab complete: Claimed 0 individual gifts.
Closing Alliance Gifts window...
Closing Alliance Menu window...
Alliance Gifts Claim flow complete!
```

### Expected output (no gifts available)

The claim steps will report `Claimed 0 individual gifts` — this is normal when all gifts have already been claimed or none are available yet.

---

## Flow 3 — Battle Rewards

**File**: `lastz/flows/battle_rewards.py`
**Menu option**: 2 (or step 2 of the Full Loop)

### What it does

Detects the orange battle rewards badge icon on screen. If present, opens the Battle Rewards modal, clicks Claim All, and dismisses the overlay.

### Steps

1. **Focus game** — bring Survival.exe to foreground
2. **Reset UI** — click outside once to dismiss any stale overlay
3. **Detect orange icon** — screenshot → match `orange_icon_no_badge.png` with threshold `0.82`
4. If **not found**: print message and exit (flow is a no-op — this is not an error)
5. If **found**: click at `(icon_center + battle_rewards_offset) / retina_scale`
6. Wait 2.5s for modal to animate open
7. Screenshot inside modal → match `universal_claim_all_button.png` with threshold `0.82`
8. If found: click Claim All, wait 2s, dismiss overlay
9. **Close modal** — click outside

### Expected output (chest present)

```
Activating game window (Survival.exe)...
Resetting game UI...
[vision] 'orange_icon_no_badge.png' match confidence = 0.9402 (threshold 0.82)
-> Found dynamic orange chest at logical (312.0, 187.0). Opening Battle Rewards...
[vision] 'universal_claim_all_button.png' match confidence = 0.9100 (threshold 0.82)
-> Clicking 'Claim All' at logical (756.0, 922.0)...
Dismissing rewards overlay...
Closing Battle Rewards modal...
Battle Rewards flow complete!
```

### Expected output (no chest)

```
[vision] 'orange_icon_no_badge.png' match confidence = 0.5244 (threshold 0.82)
-> Dynamic orange chest badge icon is NOT present on screen right now.
```

---

## Flow 4 — Background Watcher

**File**: `lastz/watcher.py`
**Menu option**: 4

### What it does

Runs indefinitely, checking for rewards on a schedule and triggering flows automatically.

### Schedule

- **Every 60 seconds**: scans for the Battle Rewards orange badge → triggers Flow 3 if found
- **Every 180 seconds (3 minutes)**: runs Alliance Gifts (Flows 1 & 2) regardless of what was found on screen

Both intervals are configurable in `config.yaml` under `watcher:`.

### Log file

All watcher output is written to `logs/watcher.log` in addition to stdout. Each line is prefixed with a timestamp:

```
[2026-06-05 11:00:22] Scanning screen for Battle Rewards...
[2026-06-05 11:00:22] Screen scan: Orange Badge Icon match confidence = 0.9402
[2026-06-05 11:00:22] >>> CLAIM TRIGGER: Found Battle Rewards icon! Launching Flow 3...
[2026-06-05 11:00:31] >>> Flow 3 completed.
```

### Stopping the watcher

Press `Ctrl+C`. The daemon catches `KeyboardInterrupt` and exits cleanly.

### Error handling

Any exception inside the loop is caught, logged with a timestamp, and the loop retries after 10 seconds. This prevents a single screencapture failure or temporary game state from crashing the daemon.

---

## Flow 4 — HQ Drone Gift

**File**: `lastz/flows/drone_gift.py`
**Menu option**: 3 (standalone), included in option 4 Full Loop

### What it does

Collects the idle reward that accumulates in the Area Exploration screen ("drone car on road"). The reward is only worth collecting once the Exploration Duration timer reaches **08:00:00** (configurable in `config.yaml` as `drone_gift.min_duration`). After collecting, the chest badge disappears for ~15 minutes — the watcher skips cleanly during this cooldown.

### Steps

1. **Ensure game running + focus** — same as other flows
2. **Confirm HQ mode** — match `hq_world_button.png` (bottom-right). If not found → `"Not in HQ mode"`
3. **Detect chest badge** — match `hq_drone_gift_chest.png` on the base. If not found → `"No chest visible (cooldown)"`
4. **OCR timer** — read HH:MM:SS from the region above/on the chest badge. If timer < 8h → `"Not ready (HH:MM:SS)"`
5. **Click chest** → Area Exploration screen opens
6. **Click Claim button** — match `drone_claim_btn.png`
7. **Idle Reward modal** — OCR Exploration Duration as a safety check; if < 8h, close without collecting
8. **Click Collect** — match `drone_collect_btn.png`
9. **Dismiss** — click outside twice to return to HQ base

### Expected output (8h reached)

```
Activating game window (Survival.exe)...
[vision] 'hq_world_button.png' match confidence = 0.8840 (threshold 0.80)
[vision] 'hq_drone_gift_chest.png' match confidence = 0.7512 (threshold 0.72)
[ocr] raw text from region (465,370,95x22): '08:02:15'
-> Timer 08:02:15 >= 08:00:00 — proceeding to collect.
-> Clicking chest badge at logical (250.5, 194.0)...
[vision] 'drone_claim_btn.png' match confidence = 0.9214 (threshold 0.85)
-> Clicking Claim at logical (310.5, 241.0)...
[vision] 'drone_collect_btn.png' match confidence = 0.9350 (threshold 0.85)
-> Clicking Collect at logical (260.5, 490.0)...
-> Drone Gift collected! Duration was 08:02:15.
```

### Expected output (not ready / cooldown)

```
[vision] 'hq_drone_gift_chest.png' match confidence = 0.5102 (threshold 0.72)
-> Gift chest not visible on screen (cooldown or not available).
```

or

```
[ocr] raw text from region ...: '02:48:20'
-> Timer 02:48:20 < 08:00:00 — not ready yet.
```

### OCR requirement

This flow uses `pytesseract` to read timer text. Install with:
```bash
pip install pytesseract
brew install tesseract
```
See [docs/SETUP.md](SETUP.md) for details. If `pytesseract` is not installed, the flow returns `"OCR unavailable — skipping"` without crashing.

### Calibration

The timer OCR region and modal region are configured in `config.yaml` under `drone_gift:`. If the OCR reads incorrectly on your display, capture a screenshot with `screencapture -x /tmp/ref.png`, open it in Preview to find the physical pixel coordinates of the timer text, and update `timer_crop_offset` and `modal_timer_region` accordingly.

---

---

## Flow 5 — HQ Resource Collection

**File**: `lastz/flows/hq_resources.py`
**Menu option**: 4 (standalone), 5 (dry run), included in option 6 Full Loop

### What it does

Scans all four production building types in the HQ base for floating resource badge icons. When a resource type's buildings show a consistent count across two successive full scans, the agent clicks one icon per type to collect all production instantly.

**Building types:**

| Building | Resource | Template |
|----------|----------|----------|
| Farmhouse | Food (tin can icon) | `hq_resource_food.png` |
| Lumberyard | Wood (log bundle icon) | `hq_resource_wood.png` |
| Smelting plant | Energy (lightning bolt icon) | `hq_resource_energy.png` |
| Residence | Gold / Z-coins (Z-coin icon) | `hq_resource_gold.png` |

### Steps

1. **Focus game + navigate to HQ** — same pattern as Drone Gift
2. **Reset UI** — dismiss any open panels
3. **Recenter map** — execute reverse pan swipes to restore default camera position
4. **Full pan sweep** — pan in a 4-step grid, capturing a full-screen frame at each stop
   - `find_all_templates()` × 4 resource types per frame (with HUD exclusion mask)
   - Results accumulate across all pan positions
5. **Spatial clustering** — merge icons seen in overlapping pan frames within `dedupe_radius_px`
6. **OCR per cluster** — read the count label below each icon (e.g. "1.3K", "291")
7. **Within-scan aggregation** — if all visible icons of a type agree on the same count → `consensus`; any disagreement or OCR failure → `still_filling` / `ocr_incomplete`
8. **Two-scan gating** — collect only if:
   - Both pass 1 and pass 2 found unanimous consensus on the **same integer count**
   - Pass 2 count is not greater than pass 1 (still-rising → skip)
   - Minimum `min_icons_per_type` (default 2) seen in both scans
   - At least `hq_resources_confirm_sec` (default 180) has elapsed between scans
9. **Click** — click the best-confidence icon per ready type (one click = instant collect-all)
10. **Verify** — re-scan once; icons gone or count dropped → mark collected; still present → log warning, skip state reset
11. **Restore wilderness** if started there

### State machine

Resource state is persisted to `logs/hq_resources_state.json` (atomic write) between watcher cycles. The schema tracks:

```json
{
  "food": {
    "consensus_count": 1300,
    "consensus_raw": "1.3K",
    "icons_seen": 5,
    "all_visible_agreed": true,
    "pan_positions_completed": 5,
    "ts": 1718123456,
    "last_collect_at": null
  }
}
```

### Expected output

```
-> Now in HQ mode.
-> Recentering HQ map...
-> Starting pan sweep (5 positions)...
  [pan 0] energy: 4 icon(s) found
  [pan 1] energy: 3 icon(s) found
  ...
  [energy] 7 raw → 4 clustered icon(s)
  [food] scan: status=consensus count=1300 icons=5 raw='1.3K'
  [energy] scan: status=still_filling count=None icons=4 raw='664 / 660'
  [gold] scan: status=consensus count=291 icons=3 raw='291'
  [food] Clicking icon at logical (145, 297) [conf=0.821]...
  [food] post-collect verify: icons gone ✓
Collected: food | still filling: energy=664/660 | pass 1 stored: gold=291 (3 icons)
```

### Calibration

Use the dev scripts to tune template thresholds and OCR crop offsets:

```bash
# Extract templates from reference screenshot
python3 scripts/dev/extract_hq_resource_templates.py

# Verify template confidence against live screen
python3 scripts/dev/verify_hq_resource_templates.py

# Diagnose OCR — dumps cropped badge images + parsed values
python3 scripts/dev/diagnose_hq_resource_ocr.py
```

Update `thresholds.hq_resource_*` and `hq_resources.count_crop_offset.*` in `config.yaml` based on results.

---

## Full Loop (option 6)

Runs Flow 1 & 2 (Alliance Gifts) → Flow 3 (Battle Rewards) → Flow 5 (HQ Resources) → Flow 4 (Drone Gift), with a 2 second pause between each. Useful for a manual one-shot full clear before starting a long session.

---

## Flow 6 — World Map Scouting

**File**: `lastz/flows/scouting.py`
**Menu options**: 8 (live loop), 9 (dry run)

### What it does

Runs a continuous scouting loop on the **wilderness world map**. Finds enemy HQs (not your alliance), filters by configurable max HQ level and max Power, and dispatches scout drones (up to 3 parallel). Press `Ctrl+C` to stop.

### Filters (config.yaml `scouting:`)

| Setting | Purpose |
|---------|---------|
| `own_alliance` | Never scout your own alliance |
| `alliance_blacklist` | Extra alliances to skip |
| `max_hq_level` | Skip HQs above this level (read from map label) |
| `max_power` | Skip if modal Power exceeds this |

### Calibration

```bash
python3 scripts/dev/calibrate_scouting_flow.py
python3 scripts/dev/verify_scouting_templates.py
python3 scripts/dev/diagnose_scouting_ocr.py
```

### Intel and reports (v2)

Scout results arrive as in-game Mail. `lastz/flows/scouting_mail.py` is a stub for future mail parsing. Attack-priority report:

```bash
python3 scripts/dev/generate_attack_report.py
```
