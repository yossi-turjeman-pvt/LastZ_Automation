# Architecture

## Overview

Pure Python macOS automation. No game-network dependency and no game-file modification. It only:

- **Reads** the screen via `screencapture`
- **Clicks** via CoreGraphics synthetic mouse events

```
config.yaml
    │
    ▼
lastz/config.py
    │
    ├── lastz/screen.py   → capture, physical↔logical mapping
    ├── lastz/vision.py   → template match (+ auto scale)
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

Coordinates from matching are in **capture pixels**. Clicks use **logical** screen coordinates. `physical_to_logical()` maps through the active display bounds and, when possible, the game window rect.

### 3. Template matching (`lastz/vision.py`)

`find_template()` / `find_all_templates()` use OpenCV `TM_CCOEFF_NORMED`.

Before matching, scale is calibrated from the display pixel ratio and refined against wilderness/HQ map-switcher anchors:

- `wilderness_hq_button.png`
- `hq_world_button.png`

Templates larger than the screen are skipped safely (no OpenCV assertion crash).

### 4. Click (`lastz/input.py`)

`click(x, y)` sends `MouseMoved` → `LeftMouseDown` → `LeftMouseUp` at logical coordinates.

## Alliance Gifts flow

See [FLOWS.md](FLOWS.md) for the step list. In short:

1. `reset_ui` — outside clicks to clear overlays
2. Open Alliance → Alliance Gifts (templates)
3. Common tab — Claim All when present, else individual Claim buttons
4. Rare tab — individual Claim buttons in the **gift list only** (footer / back-icon matches ignored)
5. Outside dismiss ×2 — close Gifts, then Alliance

## Watcher loop

```
run_watcher_loop()
  loop forever:
    ensure wilderness (click hq_world_button if in HQ)
    run_alliance_gifts_flow()
    sleep alliance_interval_sec   # default 180
```

KeyboardInterrupt exits cleanly. `GameNotRunningError` sleeps and retries. Other errors retry after 10s. Logs go to `logs/watcher.log`.

## Config-driven design

Paths, thresholds, intervals, process name, and dismiss offset live in `config.yaml`. `lastz/config.py` resolves `PROJECT_ROOT` from the package location so clones work from any directory.

## File map

| File | Role |
|------|------|
| `lastz/config.py` | Load `config.yaml`, accessors |
| `lastz/input.py` | Focus + click |
| `lastz/screen.py` | Capture + coordinate mapping |
| `lastz/vision.py` | Template matching / NMS / scale |
| `lastz/flows/base.py` | `reset_ui`, `dismiss_overlay` |
| `lastz/flows/alliance_gifts.py` | Alliance Gifts claim logic |
| `lastz/watcher.py` | Timed claim loop |
| `lastz/cli.py` | Menu (1–3) |
| `lastz/__main__.py` | `python -m lastz` |
| `lastz_auto_master.py` | Thin shim → `cli.main` |
| `lastz_watcher.py` | Thin shim → watcher loop |
