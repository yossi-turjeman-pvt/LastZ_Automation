# Architecture

## Overview

The automation is a pure Python macOS script. It has no network dependency on the game and does not modify game files. It operates entirely at the OS input/output level:

- **Output**: reads the screen with `screencapture`
- **Input**: posts synthetic mouse events via CoreGraphics

```
config.yaml
    │
    ▼
lastz/config.py  ──────────────────────────────────────────────┐
                                                                │
lastz/screen.py         lastz/vision.py        lastz/input.py  │
  screencapture()         find_template()         click()       │
       │                       │                   │            │
       │ numpy array           │ Match(x, y, conf) │            │
       ▼                       ▼                   ▼            │
  lastz/flows/alliance_gifts.py                                │
  lastz/flows/battle_rewards.py  ◄──────────────────────────────┘
  lastz/watcher.py
  lastz/cli.py
```

## Input Pipeline

### 1. Game Focus (`lastz/input.py`)

Before any flow runs, `focus_game()` brings `Survival.exe` to the foreground:

```
osascript -e 'tell application "System Events" to set frontmost of process "Survival.exe" to true'
```

A 1.5 second sleep follows to let the OS animate the window transition.

### 2. Screen Capture (`lastz/screen.py`)

`capture()` runs `screencapture -x /tmp/lastz_screen.png` and reads the result as a grayscale NumPy array.

On a Retina display the captured image is at physical resolution (e.g. 3024×1964 on a 14" MacBook Pro). This is exactly 2× the logical screen coordinates used for clicks.

### 3. Template Matching (`lastz/vision.py`)

`find_template()` uses OpenCV's `TM_CCOEFF_NORMED` (normalised cross-correlation). This is robust to minor brightness differences but sensitive to size changes — if the game window is resized, templates need to be recaptured.

**Size guard**: before calling `cv2.matchTemplate`, the module checks that the template dimensions are smaller than the screen. If not, it logs a warning and returns `None` instead of raising an OpenCV assertion (the root cause of the crash seen in earlier watcher logs).

The function returns a `Match(phys_x, phys_y, confidence)` in physical pixel space, or `None` if no match exceeds the threshold.

### 4. Coordinate Conversion (`lastz/screen.py`)

Physical pixel coordinates from template matching must be halved to get logical click coordinates on a Retina display:

```python
logical_x = physical_x / retina_scale   # retina_scale = 2.0 by default
logical_y = physical_y / retina_scale
```

This conversion is done inside each flow just before calling `click()`.

### 5. Click (`lastz/input.py`)

`click(x, y)` sends three CoreGraphics events at logical coordinates: `MouseMoved`, `LeftMouseDown`, `LeftMouseUp`, each separated by 150ms. This matches what human interaction looks like to the game's event loop.

## Watcher Loop

```
┌─────────────────────────────────────────┐
│          run_watcher_loop()             │
│                                         │
│  Every 60 seconds:                      │
│  ┌────────────────────────────────────┐ │
│  │ capture screen                    │ │
│  │ find orange_icon_no_badge template │ │
│  │  ├─ found → run_battle_rewards()  │ │
│  │  └─ not found → skip              │ │
│  └────────────────────────────────────┘ │
│                                         │
│  Every 180 seconds (3 minutes):         │
│  ┌────────────────────────────────────┐ │
│  │ run_alliance_gifts_flow()          │ │
│  └────────────────────────────────────┘ │
│                                         │
│  Exception → log + retry in 10s        │
│  KeyboardInterrupt → graceful exit     │
└─────────────────────────────────────────┘
```

Both intervals are configurable in `config.yaml` under `watcher:`.

## Config-Driven Design

All magic numbers — coordinates, thresholds, intervals, the game process name — live in `config.yaml`. No flow file contains a hardcoded pixel coordinate or a hardcoded path. This means:

- Tuning for a different display or window size only requires editing one file
- The project root is resolved from `Path(__file__).resolve().parent.parent` inside `lastz/config.py`, so the project works regardless of where it is cloned

## HQ Session Block (Flow 4 + Flow 5)

Both the Drone Gift (Flow 4) and HQ Resource Collection (Flow 5) require navigating to the HQ base map, which means leaving the wilderness.  The watcher cannot call `_ensure_wilderness()` in the middle of a multi-step pan sweep.

The watcher groups HQ flows into a single **HQ session block**:

```
Watcher loop:
  ┌─ Wilderness phase (battle rewards + alliance gifts) ──┐
  │  _ensure_wilderness()                                 │
  │  scan/claim battle rewards                            │
  │  run alliance gifts (if due)                          │
  └───────────────────────────────────────────────────────┘
  ┌─ HQ session phase (only when Flow 4 or 5 is due) ─────┐
  │  navigate_to_hq() once                                │
  │  run_hq_resources_flow() if interval elapsed          │
  │  run_drone_gift_flow()   if interval elapsed          │
  │  navigate_to_wilderness() in finally block            │
  └───────────────────────────────────────────────────────┘
```

`_ensure_wilderness()` is NEVER called during an HQ session — doing so would abort a pan sweep mid-scan and break the two-pass state machine.

## Multi-Match Vision (`find_all_templates`)

`find_all_templates()` extends `find_template()` to return ALL occurrences:

1. `cv2.matchTemplate` produces a full confidence heatmap
2. All pixels above threshold are collected
3. **Non-Maximum Suppression (NMS)** removes redundant overlapping boxes (IoU threshold 0.3)
4. Optional **HUD exclusion mask** ignores bottom/top/side UI chrome where false positives arise
5. Returns `list[MatchWithBBox]` sorted by confidence

`cluster_matches()` deduplicates icons seen in overlapping pan frames by merging all detections within `dedupe_radius_px` physical pixels into one representative match (the highest-confidence one).

## Map Panning (`drag()`)

`drag(x1, y1, x2, y2)` in `lastz/input.py` sends:

```
MouseDown(x1,y1) → [N × MouseMoved(interpolated)] → MouseUp(x2,y2)
```

All in logical screen coordinates. The HQ base map responds to this as a touch-drag, scrolling the camera to reveal off-screen buildings.

## File Responsibilities

| File | Responsibility |
|------|---------------|
| `lastz/config.py` | Loads `config.yaml`, resolves `PROJECT_ROOT`, exposes typed accessors |
| `lastz/input.py` | CoreGraphics `click()`, `drag()`, osascript focus |
| `lastz/screen.py` | Screen capture, Retina scaling, temp file cleanup |
| `lastz/vision.py` | `find_template()` (single), `find_all_templates()` + NMS (multi), `cluster_matches()` |
| `lastz/ocr.py` | Timer OCR (`HH:MM:SS`) and resource count OCR (`1.3K`, `291`) |
| `lastz/flows/base.py` | `reset_ui()`, `dismiss_overlay()` shared by all flows |
| `lastz/flows/hq_nav.py` | `is_hq_mode()`, `navigate_to_hq()`, `navigate_to_wilderness()`, `run_in_hq()` context manager |
| `lastz/flows/alliance_gifts.py` | Flows 1 & 2 logic |
| `lastz/flows/battle_rewards.py` | Flow 3 logic |
| `lastz/flows/drone_gift.py` | Flow 4 logic (imports nav from `hq_nav`) |
| `lastz/flows/hq_resources.py` | Flow 5 logic — pan sweep, two-pass state machine, collect+verify |
| `lastz/watcher.py` | Daemon loop, HQ session block, logging |
| `lastz/cli.py` | Interactive menu (options 1–8) |
| `lastz/__main__.py` | `python -m lastz` entry point |
