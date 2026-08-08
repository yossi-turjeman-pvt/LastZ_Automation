# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LastZ Automation is a macOS automation bot for the LastZ (Survival.exe) game that performs timed gifts collection flows. It operates entirely at the OS level using screen capture and synthetic mouse clicks - no game file modification or network interception.

**Core principle:** Full-dynamic clicks. Template scale and click coordinates are discovered from the live game window every run. No per-machine calibration files.

## Development Commands

### Running the bot

```bash
# Activate virtual environment
source .venv/bin/activate

# Main entry point (interactive menu)
python -m lastz

# Direct watcher loop
python lastz_watcher.py

# Vision scout (observe-only, no clicks)
python -m lastz.flows.vision_scout
```

### Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_alliance_gifts.py

# Run with verbose output
pytest -v
```

### Dependencies

```bash
# Install/update dependencies
pip install -r requirements.txt
```

## Architecture

### Core Layers

1. **Configuration** (`lastz/config.py`)
   - Loads `config.yaml` at runtime
   - All thresholds, intervals, and tuning parameters live in YAML
   - Code should never hardcode magic numbers - use config accessors

2. **Screen Capture** (`lastz/screen.py`)
   - `capture()` - grayscale capture via macOS `screencapture`
   - `capture_both()` - returns (color, gray) tuple
   - `capture_game_window_bg()` - off-screen window capture (doesn't require focus)
   - Coordinates are in **capture pixels** (Retina 2x or higher)
   - `physical_to_logical()` maps capture pixels → global logical click coordinates

3. **Template Matching** (`lastz/vision.py`)
   - OpenCV `TM_CCOEFF_NORMED` with auto-scale discovery
   - **Multi-anchor calibration**: Uses 4 always-visible anchors to discover scale (0.35-1.25 range)
   - **Game window ROI**: Searches only within the game window to reject desktop chrome false positives
   - **Thread-local state**: Concurrent threads (main flow + background heli monitor) maintain separate calibration
   - Scale cache on disk (`logs/.template_scale_cache.json`) with 24h TTL and revalidation
   - `find_template()` - single best match above threshold
   - `find_all_templates()` - all matches with NMS (Non-Maximum Suppression)

4. **Input** (`lastz/input.py`)
   - `focus_game()` - brings game to front via AppleScript
   - `click(x, y)` - synthetic click at logical coordinates
   - `rapid_click()` - burst clicking (for helicopter prize window)
   - **Focus verification**: Every input function checks `is_game_frontmost()` before firing (prevents keystrokes going to IDE/other apps)
   - `press_escape()` - closes overlays/modals

5. **Flows** (`lastz/flows/`)
   - `alliance_gifts.py` - main collection flow (drone + battlefield + gifts + techs + trucks)
   - `drone_gift.py` - HQ Area Exploration idle reward with OCR timer reading
   - `trucks.py` - truck claiming and sending (upper slot only, color-filtered)
   - `helicopter.py` - BR heli monitor and Explore Treasure flow
   - `base.py` - `reset_ui()`, `ensure_wilderness()`, `dismiss_overlay()`
   - `help_watcher.py` - tight poll for handshake Help icon (menu 4)

### Key Design Patterns

#### Verified Navigation (2026-08-02 fix)

Never assume a click worked just because it fired. After every "open X" action, verify X actually appeared:

```python
# BAD: Assume the panel opened
click_template("alliance_shield_clean.png", threshold)
# Now assume we're on Alliance screen...

# GOOD: Verify it opened, retry if not
click_template("alliance_shield_clean.png", threshold)
screen = capture()
if not find_template(screen, "alliance_gifts_precise.png", threshold):
    # Grid didn't appear - retry the shield click
```

Real incidents: Shield click logged as "success" but screen didn't change. Subsequent searches ran against wrong screen, reported "0 gifts" when gifts were actually unclaimed.

#### Spatial Bands (lastz/flows/ui_bands.py)

Reject high-confidence false positives outside expected UI regions:

```python
# Check if match falls within expected band
if not in_band(match, BAND_ALLIANCE_GRID):
    # Reject even if confidence is high
```

Templates can match unintended UI elements (checkmarks, icons in text). Spatial bands ensure matches are in the right location.

#### Thread Safety

Screen capture state and template calibration use **thread-local storage** (`threading.local()`). The background helicopter monitor runs in a separate thread and must not interfere with the main flow thread's capture/calibration state.

```python
# lastz/screen.py and lastz/vision.py
_local = threading.local()
# Each thread maintains its own capture_size, active_display_bounds, scale_center
```

#### Color Detection

Trucks use HSV color filtering to verify orange/purple before sending:

```python
# Extract ROI, convert to HSV, apply mask, compute dominant color
# See lastz/flows/trucks.py _analyze_truck_color()
```

HSV is more robust than RGB for in-game lighting variations.

## Testing Strategy

### Real Failure Frames

`tests/test_alliance_gifts.py` includes regression tests built from actual failure screenshots:

- `test_rare_tab_false_positive_in_alliance_text()` - green checkmark in description text matched as Rare tab
- `test_panel_not_open_after_shield()` - shield click didn't open Alliance menu

When adding new tests, prefer real screenshots from `logs/debug/flow/` over synthetic test images.

### Flow Verification

`tests/test_flow_verification.py` uses saved captures to verify the full flow logic without clicking.

## Configuration

All tuning lives in `config.yaml`. When adding new features:

1. Add config keys to `config.yaml` with sensible defaults
2. Add accessors in `lastz/config.py`
3. Document the flag in README.md under "Configuration flags"

## Logging and Debugging

### Run Logs

- `logs/runs.log` - structured run log with step markers
- `logs/watcher.log` - watcher loop messages
- `logs/heli.log` - helicopter flow

### Debug Dumps

- `logs/debug/flow/crash_*.png` - annotated screenshots on failure
- `logs/debug/scout/` - vision scout output
- `logs/debug/trucks/color/` - truck color detection ROIs (when `trucks.save_color_debug: true`)

Use `dump_crash(exc, prefix="crash_step_name")` to save annotated failure frames.

## Critical Files

### Templates (`templates/active/`)

**Production templates only**. Other template dirs are historical/unused.

Templates are captured on built-in Retina (3024×1964 capture, 1512×982 window). Auto-scale makes them work on any display.

### State Files (gitignored)

- `logs/.template_scale_cache.json` - disk cache for template scale (keyed by resolution)
- `logs/.trucks_state.json` - learned truck row positions (prevents double-send on hidden rows)
- `data/motivation_stats.json` - monthly loot ledger

## Common Tasks

### Adding a new template

1. Capture a clean screenshot at reference resolution (Retina built-in display)
2. Crop the template tightly around the target UI element
3. Save to `templates/active/<name>.png`
4. Add threshold to `config.yaml` under `thresholds:`
5. Use `find_template(screen, "<name>.png", cfg_threshold("<name>"))`

### Adding a new flow step

1. Create function in appropriate `lastz/flows/*.py` module
2. Add step logging: `log_step("Step Name", "start/skip/done/fail", details)`
3. Use try/except with `dump_crash()` on failure
4. Add spatial band checks if matching UI elements
5. Verify navigation - never assume clicks worked

### Modifying thresholds

Edit `config.yaml` and restart. No code changes needed. Thresholds are confidence values (0.0-1.0) for OpenCV template matching.

### Adding helicopter checkpoints

Watcher can yield to helicopter at step boundaries:

```python
_heli_checkpoint(source, "step_name")  # raises HeliInterrupt if heli spotted
```

## Gotchas

1. **Never use bare text templates** without verification. Text rendering varies by system. Use OCR (`lastz/ocr.py`) to confirm labels when needed.

2. **Trucks upper slot only**. Code deliberately ignores lower empty slots - only the uppermost track is used for sending. This prevents double-sends when en-route trucks become invisible.

3. **Truck color detection requires dominance**. Orange/purple classification now checks both pixel count AND dominance percentage. A gray truck with orange cargo bags has its gray body pixels counted - if gray dominates, it's correctly classified as "other" not "orange". Fixed 2026-08-08 after real incident where 2907 orange pixels (decorations) on a gray body caused wrong classification.

4. **Escape-safe dismiss**. Startup `reset_ui` uses Escape + verified Cancel button, never blind map clicks (which could dismiss HQ buildings).

5. **Focus before input**. `_require_game_frontmost()` is called before every click/keystroke. A backgrounded game silently drops input.

6. **Tesseract required for OCR**. Drone gift timer reading needs system Tesseract. Flow gracefully skips if unavailable.

7. **CrossOver Hebrew fix is one-time setup** (menu 3). Not part of regular flows.

8. **Template matching uses grayscale**. Color is only used for HSV filtering (trucks, tech thumbs).

9. **Concurrent captures need thread-local state**. Background threads must not share `_last_capture_size` or `_active_display_bounds`.

## Code Style

- Avoid over-engineering. Only add complexity when explicitly required.
- Log every step clearly (`log_step()`, `log_click()`, `log_skip()`)
- Config-driven: thresholds, intervals, paths go in YAML
- Defensive matching: verify navigation actually worked
- Spatial bands: reject out-of-band matches even at high confidence
- No per-machine calibration: everything scales from live window every run
