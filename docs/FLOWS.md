# Flows

## Gifts collection (HQ Drone + Battlefield + Alliance Gifts + Alliance Techs + Trucks)

**Entry:** menu `1`, watcher loop (`2` / `lastz_watcher.py`), or `from lastz.flows.alliance_gifts import run_alliance_gifts_flow`.

One flow. Not a separate menu item. Clicks are full-dynamic (template centers + window-fraction dismiss). **Spatial bands** reject high-confidence matches outside expected UI regions.

### Steps

1. Ensure the game is running and focused.
2. `reset_ui` — Escape up to N times; if Quit Tips ("Exit the game?") appears, click blue **Cancel** (never map-corner clicks on HQ).
3. **HQ Drone Gift** — enter HQ if needed; OCR Exploration Duration under the chest; collect only if ≥ `drone_gift.min_duration` (default `08:00:00`); Claim → Collect; always return to Wilderness. Skip if no chest / not ready / OCR unavailable.
4. **`ensure_wilderness`** — confirm Wilderness before map gifts (`[Map]` logs).
5. **Battlefield Gifts** — `orange_icon_no_badge.png` match center → Claim All if present → dismiss.
6. Open **Alliance** — HUD shield in right-stack band only.
7. Open **Alliance Gifts** — `alliance_gifts_precise.png` in grid band.
8. **Common tab** — Claim All if present (**one** outside dismiss for reward popup), else green individual Claims (`y ≤ 0.82`, green HSV ≥ 0.20, top-of-list first).
9. **Rare tab** — match `rare_tab.png` in tab band (~yf 0.35–0.52 under Level bar); click; **no** second outside dismiss. Then Claim All if present / else green Claims same as Common.
10. Dismiss Gifts (stay on Alliance).
11. **Alliance open check** — if grid tiles (`alliance_techs` / `alliance_gifts`) in mid band → stay; else re-open only via HUD shield in **right-stack** band (never center-screen FPs).
12. **Alliance Techs** — open tile via microscope in grid band; if badge breaks icon match, use **left neighbor of Alliance Gifts** with OCR confirm (`tech` in label); label template only if OCR confirms (never bare text FP → Shop). Then thumbs with **orange HSV + tree band**; else lit hex; **blue** Donate only.
13. Dismiss Techs + Alliance.
14. **Trucks** (if `trucks.include_trucks_flow`, default true) — open when left-HUD icon has a **red badge**, or every `open_every_n_runs` gifts runs (default 5). Then: My Truck → claim chest(s) → if trade &lt; 4/4: **discover all highway tracks** (empty `+` + occupied chests/trucks in `highway_band`) → use **only the uppermost**; if that row is empty, refresh for orange (or purple if `allow_purple_trucks`) → **Go only if color wanted** and Go conf ≥ 0.92; if upper occupied → **leave it** (ignore lower empties). One truck at a time.

### Spatial bands (`lastz/flows/ui_bands.py`)

| Target | Y frac | X frac |
|--------|--------|--------|
| Rare tab | 0.35–0.52 | 0.40–0.72 |
| List Claim max Y | ≤ 0.82 | — |
| Alliance grid | 0.40–0.78 | 0.15–0.85 |
| Tech tree | 0.12–0.72 | 0.18–0.82 |
| HUD shield | 0.55–0.95 | 0.72–1.0 |

### Vision scout (observe only)

Agent/debug tool — **no Claim/Donate**, no new menu item:

```bash
python -m lastz.flows.vision_scout
```

Writes annotated PNGs + `logs/debug/scout/report.md`. Flow debug clicks also dump under `logs/debug/flow/`.

### Templates (`templates/active/`)

| File | Used for |
|------|----------|
| `hq_drone_gift_chest.png` | HQ Area Exploration gift chest badge |
| `drone_claim_btn.png` | Area Exploration Claim |
| `drone_collect_btn.png` | Idle Reward Collect |
| `orange_icon_no_badge.png` | Battlefield chest |
| `alliance_shield_clean.png` | Open Alliance (+ HUD re-open in right stack) |
| `alliance_gifts_precise.png` | Open Gifts / grid presence |
| `rare_tab.png` | Rare tab (tab strip under Level bar) |
| `claim_all_button_clean.png` / `universal_claim_all_button.png` | Claim All |
| `claim_button_clean.png` | Per-gift Claim (green filter) |
| `alliance_techs.png` | Techs microscope (badge-free), grid band |
| `alliance_techs_label.png` | In-band fallback only |
| `tech_thumbs_up.png` | Recommended tech (orange + tree band) |
| `tech_hex_active.png` | Lit hex fallback |
| `donate_blue.png` | Blue gold Donate only |
| `hq_world_button.png` / `wilderness_hq_button.png` | Map mode (HQ ↔ Wilderness) |
| `trucks_icon.png` | Left-HUD trucks entry |
| `trucks_my_truck_tab.png` | My Truck tab |
| `trucks_claim_chest.png` | Arrived truck claim chest |
| `trucks_slot_plus.png` | Empty slot green `+` |
| `trucks_refresh.png` | Picker refresh |
| `trucks_go.png` | Picker Go |
| `trucks_details_back.png` | Details modal back after claim |

### Config keys

- Thresholds including `drone_gift_chest`, `alliance_techs`, `tech_thumbs_up` (0.78), `donate_blue`, `trucks_*`, …
- `drone_gift.min_duration` / `timer_crop_offset` / `modal_timer_region`
- `alliance_techs.max_donates`
- `trucks.include_trucks_flow` / `allow_purple_trucks` / `max_refreshes` / `open_every_n_runs`
- `coordinates.dismiss_outside_frac`
- `watcher.alliance_interval_sec`

See README **Configuration flags** for the full table.
