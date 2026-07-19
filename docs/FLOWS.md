# Flows

## Gifts collection (Battlefield + Alliance Gifts + Alliance Techs)

**Entry:** menu `1`, watcher loop (`2` / `lastz_watcher.py`), or `from lastz.flows.alliance_gifts import run_alliance_gifts_flow`.

One flow. Not a separate menu item. Clicks are full-dynamic (template centers + window-fraction dismiss). **Spatial bands** reject high-confidence matches outside expected UI regions.

### Steps

1. Ensure the game is running and focused.
2. `reset_ui` — outside clicks at `coordinates.dismiss_outside_frac` of the game window.
3. **`ensure_wilderness`** — World button → HQ→Wilderness; Headquarters button → already wilderness (`[Map]` logs).
4. **Battlefield Gifts** — `orange_icon_no_badge.png` match center → Claim All if present → dismiss.
5. Open **Alliance** — HUD shield in right-stack band only.
6. Open **Alliance Gifts** — `alliance_gifts_precise.png` in grid band.
7. **Common tab** — Claim All if present (**one** outside dismiss for reward popup), else green individual Claims (`y ≤ 0.82`, green HSV ≥ 0.20, top-of-list first).
8. **Rare tab** — match `rare_tab.png` in tab band (~yf 0.35–0.52 under Level bar); click; **no** second outside dismiss. Then Claim All if present / else green Claims same as Common.
9. Dismiss Gifts (stay on Alliance).
10. **Alliance open check** — if grid tiles (`alliance_techs` / `alliance_gifts`) in mid band → stay; else re-open only via HUD shield in **right-stack** band (never center-screen FPs).
11. **Alliance Techs** — microscope `alliance_techs.png` in grid band (label fallback only in-band); thumbs with **orange HSV + tree band** (ignores map help icons); else lit hex; **blue** Donate only.
12. Dismiss Techs + Alliance.

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
| `hq_world_button.png` / `wilderness_hq_button.png` | Map mode |

### Config keys

- Thresholds including `alliance_techs`, `tech_thumbs_up` (0.78), `donate_blue`, …
- `alliance_techs.max_donates`
- `coordinates.dismiss_outside_frac`
- `watcher.alliance_interval_sec`
