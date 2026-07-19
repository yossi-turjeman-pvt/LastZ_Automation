# Architecture

## Overview

Pure Python macOS automation. No game-network dependency and no game-file modification. It only:

- **Reads** the screen via `screencapture`
- **Clicks** via CoreGraphics synthetic mouse events

Clicks are **full dynamic**: template scale and hit points come from the live game window every run — no per-machine calibration profile.

```
config.yaml
    │
    ▼
lastz/config.py
    │
    ├── lastz/screen.py   → capture, physical↔logical mapping
    ├── lastz/vision.py   → template match (auto scale + window ROI)
    ├── lastz/input.py    → focus_game, click
    │
    ├── lastz/flows/alliance_gifts.py
    ├── lastz/flows/base.py
    ├── lastz/watcher.py
    └── lastz/cli.py
```

## Pipeline

### 1. Focus (`lastz/input.py`)

`focus_game()` brings `Survival.exe` (or `game.process_name`) to the front with AppleScript / System Events, then briefly waits for the window to settle.

### 2. Capture (`lastz/screen.py`)

`capture()` / `capture_both()` run `screencapture` into a temp PNG and load it with OpenCV (grayscale for matching, color when needed).

Coordinates from matching are in **capture pixels**. Clicks use **logical** screen coordinates. `physical_to_logical()` maps through the active display bounds and the game window rect.

### 3. Template matching (`lastz/vision.py`)

`find_template()` / `find_all_templates()` use OpenCV `TM_CCOEFF_NORMED`.

Before matching:

1. Crop search to the **game window ROI** inside the capture
2. Discover template scale over `0.35–1.25` from multi-anchors:
   - `wilderness_hq_button.png`, `hq_world_button.png`
   - `alliance_shield_clean.png`
   - `orange_icon_no_badge.png` (when present)
3. Accept scale only at confidence ≥ 0.70 (else pixel-ratio fallback + WARN)
4. Match with a local scale band; if below threshold, one full-band refine for that template
5. Remap ROI-local match centers back to full-capture coordinates

Templates larger than the ROI are skipped safely (no OpenCV assertion crash).

### 4. Click (`lastz/input.py`)

`click(x, y)` sends `MouseMoved` → `LeftMouseDown` → `LeftMouseUp` at logical coordinates.

Action buttons always use **match centers**. Startup `reset_ui` uses **Escape** + Quit Tips **Cancel** (verified). Mid-flow reward dismiss still uses `coordinates.dismiss_outside_frac` of the current game window.

## Gifts collection flow

See [FLOWS.md](FLOWS.md). In short:

1. `reset_ui` → **HQ Drone Gift** (if timer ≥ `08:00:00`) → always leave Wilderness
2. `ensure_wilderness` (`[Map]` logs)
3. Battlefield chest if present
4. Alliance → Gifts → Common (Claim All / green Claims)
5. Rare tab (tab-strip band ~yf 0.35–0.52 + one click; no extra dismiss) → Claim All / green Claims (`y ≤ 0.82`)
6. Dismiss Gifts; confirm Alliance grid (or HUD shield in right stack only)
7. Techs (microscope in grid band); thumbs need orange HSV + tree band; blue Donate only
8. Dismiss Techs + Alliance

Debug dumps: `logs/debug/flow/`. Observe-only scout: `python -m lastz.flows.vision_scout` → `logs/debug/scout/`.

## Watcher loop

```
run_watcher_loop()
  loop forever:
    run_alliance_gifts_flow()   # includes ensure_wilderness
    sleep alliance_interval_sec
```

KeyboardInterrupt exits cleanly. `GameNotRunningError` sleeps and retries. Other errors retry after 10s. Logs go to `logs/watcher.log`.

## Config-driven design

Paths, thresholds, intervals, process name, and dismiss fractions live in `config.yaml`. `lastz/config.py` resolves `PROJECT_ROOT` from the package location so clones work from any directory.

## File map

| File | Role |
|------|------|
| `lastz/config.py` | Load `config.yaml`, accessors |
| `lastz/input.py` | Focus + click |
| `lastz/screen.py` | Capture + coordinate mapping |
| `lastz/vision.py` | Template matching / NMS / auto scale / window ROI |
| `lastz/runlog.py` | Run header / step markers / clicks → `logs/runs.log`; crash dumps |
| `lastz/ocr.py` | Timer OCR (HH:MM:SS) for HQ drone gift |
| `lastz/flows/base.py` | `reset_ui`, `dismiss_overlay`, `ensure_wilderness` |
| `lastz/flows/hq_nav.py` | HQ ↔ Wilderness mode switch |
| `lastz/flows/drone_gift.py` | HQ Area Exploration idle reward (≥ 08:00:00) |
| `lastz/flows/ui_bands.py` | Spatial ROI fractions for Rare / grid / tech / HUD |
| `lastz/flows/vision_scout.py` | Observe-only scout (`python -m lastz.flows.vision_scout`) |
| `lastz/debug_match.py` | Annotated match dumps under `logs/debug/` |
| `lastz/flows/alliance_gifts.py` | Full collection: Drone + Battlefield + Gifts + Techs |
| `lastz/watcher.py` | Timed claim loop |
| `lastz/cli.py` | Menu (1–3) |
| `lastz/__main__.py` | `python -m lastz` |
| `lastz_auto_master.py` | Thin shim → `cli.main` |
| `lastz_watcher.py` | Thin shim → watcher loop |
