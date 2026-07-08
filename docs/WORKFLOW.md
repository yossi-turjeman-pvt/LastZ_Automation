# Development Workflow — Adding Features, Testing & Bug Fixing

This document is the source of truth for adding new automation features to this project.
Read it at the start of any new chat before touching code.

---

## 1. Project Overview (Quick Refresh)

| Layer | Files | Purpose |
|---|---|---|
| Config | `config.yaml` | All thresholds, regions, intervals, coordinates |
| Flows | `lastz/flows/<name>.py` | One file per game action sequence |
| Core libs | `lastz/screen.py`, `vision.py`, `ocr.py`, `input.py` | Screenshot, template match, OCR, click |
| Watcher | `lastz/watcher.py` | Background daemon, runs flows on a schedule |
| CLI | `lastz/cli.py` | Manual run menu |
| Templates | `templates/active/*.png` | Physical-pixel crops used for matching |
| Dev scripts | `scripts/dev/` | One-off tools: crop templates, diagnose, verify |

**Key constraint:** All coordinates are **physical pixels** (Retina 2× scale).
Clicks must be converted to logical: `lx, ly = physical_to_logical(phys_x, phys_y)`.

---

## 2. Adding a New Flow — Step by Step

### Step 1: Understand the game UI sequence

Before writing a single line of code, document the exact sequence:
- What screen does it start from? (HQ base map, wilderness, a dialog?)
- What buttons/elements are clicked, in what order?
- What are the success and failure conditions at each step?
- Are there timers, cooldowns, or minimum wait conditions?
- Does the flow change the game's mode/screen? Does it need to restore it?

Write these as numbered steps in the flow file's docstring before implementing.

### Step 2: Take reference screenshots

Run the game to each state involved and capture:

```bash
# Bring game to front first
osascript -e 'tell application "Survival.exe" to activate'
screencapture -x ~/Downloads/step1_hq_base.png
screencapture -x ~/Downloads/step2_modal_open.png
```

Take **one screenshot per distinct screen state**. Keep them — you'll need them for template cropping and OCR region calibration.

### Step 3: Crop templates

Create `scripts/dev/extract_<flow_name>_templates.py`.

**Critical: templates must be in physical pixels at game window scale.**

```python
# Pattern for correct physical-pixel cropping:
import subprocess, cv2, numpy as np
from lastz.screen import capture_both

# Always focus the game before capturing
subprocess.run(['osascript', '-e', 'tell application "Survival.exe" to activate'])
import time; time.sleep(0.5)
color, _ = capture_both()

# Crop using physical pixel coordinates (NOT logical)
# On Retina: logical coord × 2 = physical coord
crop = color[phys_y1:phys_y2, phys_x1:phys_x2]
cv2.imwrite('templates/active/my_element.png', crop)
```

**After cropping, always verify confidence against the live screen:**

```python
from lastz.screen import capture
from lastz.vision import find_template
screen = capture()
m = find_template(screen, 'my_element.png', threshold=0.0)
print(f'Confidence: {m.confidence:.4f}')  # aim for > 0.80
```

Acceptable confidence ranges:
- **> 0.85** — ideal, use threshold 0.82–0.85
- **0.70–0.85** — acceptable, use threshold 0.65–0.75
- **< 0.70** — re-crop tighter or capture at a better moment

Add thresholds to `config.yaml` under `thresholds:`.

### Step 4: Implement the flow

File: `lastz/flows/<flow_name>.py`

**Required patterns:**

```python
def run_my_flow() -> str:
    """Always return a human-readable status string for the watcher log."""
    ensure_game_running()   # raises GameNotRunningError if game is closed
    focus_game()

    # Use capture_both() when you need BOTH grayscale (template matching)
    # AND color (OCR) from the same frame — avoids frame drift between two captures.
    screen_color, screen = capture_both()

    # Template match in grayscale
    match = find_template(screen, "element.png", cfg_threshold("element"))
    if match is None:
        return "Element not found"

    # Click uses LOGICAL coordinates
    lx, ly = physical_to_logical(match.phys_x, match.phys_y)
    click(lx, ly)
    time.sleep(2.0)

    return "Done"
```

**Mode/screen state:**
- If the flow navigates away from the starting screen (e.g. HQ → wilderness), **restore it on exit**.
- Use `try/finally` so all return paths restore state:

```python
started_in_wilderness = not _is_hq_mode(screen)
try:
    # ... flow logic ...
    return "Done"
finally:
    if started_in_wilderness:
        _navigate_to_wilderness()
```

**If using OCR** — see Section 4.

### Step 5: Add to config.yaml

```yaml
thresholds:
  my_element: 0.82

my_flow:
  min_duration: "08:00:00"       # example: time gate
  timer_crop_offset: [-77, 8, 150, 20]  # [left, top, width, height] relative to matched element center
```

### Step 6: Wire into CLI and watcher

`lastz/cli.py` — add menu option and handler.

`lastz/watcher.py` — add interval config to `config.yaml` and periodic trigger in the loop.

---

## 3. Testing a New Flow

### Manual test (always do this first)

```bash
cd /Users/yossiturjeman/LastZ_Automation
python3 -c "
from lastz.flows.my_flow import run_my_flow
result = run_my_flow()
print('RESULT:', result)
"
```

Run it **with the game in the expected starting state** (e.g. HQ base, no dialogs open).
Check:
1. Result string matches expected
2. Game screen ends in the correct state (no stuck dialogs)
3. No exceptions

### Verify template matching confidence

```bash
python3 scripts/dev/verify_drone_templates.py   # adapt for your flow
```

Or inline:

```python
from lastz.input import focus_game
from lastz.screen import capture_both
from lastz.vision import find_template

focus_game()
_, screen = capture_both()
for tpl in ['element_a.png', 'element_b.png']:
    m = find_template(screen, tpl, threshold=0.0)
    print(f'{tpl}: {m.confidence:.4f}')
```

### Watch the watcher log

```bash
tail -f logs/watcher.log
```

After adding the flow to the watcher, let it run through at least one full cycle. Confirm:
- Correct schedule (fires at right interval)
- Correct result string logged
- No stuck states between runs

---

## 4. OCR for Timer Text

Used when a flow needs to read an `HH:MM:SS` timer from the screen.

### Calibrating the crop region

The crop region is defined relative to a matched template's physical center:
`timer_crop_offset: [left_offset, top_offset, width, height]`

**To find the correct offset:**

```python
from lastz.input import focus_game
from lastz.screen import capture_both
from lastz.vision import find_template
import cv2

focus_game()
color, screen = capture_both()
match = find_template(screen, 'my_element.png', threshold=0.0)
cx, cy = int(match.phys_x), int(match.phys_y)

# Save a wide crop around the element to visually find the timer
wide = color[cy-100:cy+100, cx-200:cx+200]
cv2.imwrite('/tmp/wide_crop.png', wide)
# Open /tmp/wide_crop.png and measure the timer position relative to (cx, cy)
```

Once you have offsets, test OCR:

```python
from lastz.ocr import read_duration_from_region, format_duration
secs = read_duration_from_region(color, cx+left, cy+top, width, height)
print(format_duration(secs) if secs else 'None')
```

### OCR preprocessing (what works for this game's font)

The game uses white text on a dark background. The pipeline in `lastz/ocr.py`:

1. Extract white pixels: `R+G+B > 600`
2. Add **20px black border** before scaling — critical, without it edge characters get misread (e.g. `"2"→"7"`)
3. Upscale 6×
4. Invert (Tesseract needs **black text on white background**)
5. PSM 7 (single text line) with digit+colon whitelist

**Common OCR failure modes and fixes:**

| Symptom | Cause | Fix |
|---|---|---|
| Returns empty string `''` | No white pixels found, or wrong region | Verify crop with `cv2.imwrite`, check threshold |
| Digits misread (e.g. `"2"→"7"`) | No border padding | 20px border before upscale — already in `ocr.py` |
| Reads wrong screen content | Cursor grabbed focus before `screencapture` | Use `capture_both()` after `focus_game()`; never two separate captures |
| Reads impossible value (e.g. `"90:23:06"`) | OCR inversion missing | Ensure `cv2.bitwise_not()` is applied before Tesseract |
| Parses `None` despite text visible | Regex mismatch or seconds > 59 | Check raw text log `[ocr] raw text from region...` |

### Safety rules for timer-gated collection

**Never collect based on a single OCR read.** Always:

1. Validate the hours value against the known maximum (`hours > max → skip`)
2. Double-confirm with a second fresh capture before proceeding:

```python
# First read >= threshold: re-read to confirm
time.sleep(1.5)
color2, gray2 = capture_both()
confirm_sec = read_duration_from_region(color2, ...)
if confirm_sec is None or confirm_sec < min_sec:
    return "Not confirmed — skipping"
```

---

## 5. Bug Fixing Process

### When the flow does nothing or errors

1. **Check the watcher log first**: `tail -30 logs/watcher.log`
2. **Run the flow manually** with verbose output to see exactly where it stops
3. **Capture the screen** at the moment of failure:

```python
from lastz.input import focus_game
from lastz.screen import capture_both
import cv2
focus_game()
color, _ = capture_both()
cv2.imwrite('/tmp/debug_screen.png', color)
```

4. Look at the screenshot — is a dialog open? Wrong screen? Missing element?

### When template matching fails (low confidence)

- Run confidence check (Section 3)
- If < 0.60: re-crop the template. Common cause: scale mismatch between source screenshot and live game window
- Lower threshold cautiously — going below 0.55 risks false matches

**Scale mismatch diagnosis:**

```python
# Expected physical template size vs actual game window:
import subprocess
result = subprocess.run(['osascript', '-e', '''
  tell application "System Events"
    tell process "Survival.exe"
      get size of window 1
    end tell
  end tell
'''], capture_output=True, text=True)
print(result.stdout)  # logical size; multiply by retina_scale for physical
```

### When OCR reads wrong values

1. Save the exact crop being fed to OCR:

```python
crop = screen_color[ty:ty+th, tx:tx+tw]
cv2.imwrite('/tmp/ocr_crop_debug.png', crop)
```

2. Run Tesseract directly on the saved file with different PSM modes:

```python
import pytesseract, cv2
img = cv2.imread('/tmp/ocr_crop_debug.png', cv2.IMREAD_COLOR)
# Apply same preprocessing as ocr.py, then test:
for psm in [6, 7, 8, 13]:
    t = pytesseract.image_to_string(processed, config=f'--psm {psm} -c tessedit_char_whitelist=0123456789:').strip()
    print(f'PSM{psm}: {repr(t)}')
```

3. If the saved crop reads correctly but the live run doesn't: the game animation was at a bad frame. Use a retry loop or `capture_both()` (not two separate calls).

### Iteration speed

- Edit code → run manual test → observe log → repeat
- Never commit to a threshold or region until you've seen it work correctly 3+ times in real runs
- Keep `scripts/dev/` scripts around; they are the fastest debugging tool

---

## 6. Lessons Learned (Real Examples)

These came from building the Drone Gift (Flow 4) and should inform all future flows.

**1. Use `capture_both()` instead of separate `capture()` + `capture_color()` calls.**
Two separate `screencapture` calls can capture different animation frames. The matched template position from frame 1 can be wrong for the OCR crop in frame 2.

**2. Tesseract requires a border around text.**
Without ~20px of padding around the white-pixel mask, edge characters are misread. `"02:09:54"` was consistently read as `"07:09:54"` until border padding was added.

**3. Invert the mask before Tesseract.**
Tesseract expects black text on white background. A white-on-black mask produces empty or wrong output. Always `cv2.bitwise_not()` the processed image before passing to `pytesseract`.

**4. Never skip collection timing checks even temporarily.**
If OCR fails, the correct behavior is to skip, not to proceed anyway. An early collection wastes hours of accumulated rewards. The flow must return `"OCR unavailable — skipping"` rather than collecting blindly.

**5. Restore game state after every flow.**
If a flow navigates to a different screen/mode (e.g. HQ mode), it must restore the original mode in a `finally` block. Other flows depend on a predictable starting state.

**6. The "mode switcher" button is a toggle, not a one-way button.**
- In HQ → button says **"World"** → clicking goes to Wilderness (`hq_world_button.png`)
- In Wilderness → button says **"Headquarters"** → clicking goes to HQ (`wilderness_hq_button.png`)

**7. Add an hours sanity check for timers that have a known maximum.**
If a timer physically stops at `08:00:00`, any OCR reading with `hours > 8` is a misread. Reject it immediately.

**8. Verify live — don't assume a script works because it runs without errors.**
Take a screenshot after each flow run to confirm the game ended in the right state. The watcher log `Collected (08:10:17)` is only meaningful if the game actually collected.

**9. Pan-based flows need map recentering before each sweep.**
Two consecutive pan sweeps with different camera positions will have overlapping icons at different physical coordinates. Always recenter (`_recenter_map()`) before every sweep so the starting camera position is reproducible. This is the only way to guarantee the cross-scan count comparison is meaningful.

**10. Multi-match template detection needs spatial clustering after a pan sweep.**
When panning the HQ map, the same building icon is often captured in two consecutive pan positions (they overlap). Without `cluster_matches()`, the same building would be OCR'd twice, artificially inflating the `icons_seen` count and corrupting the unanimity check.

**11. Unanimous consensus across all visible icons is stricter than a majority vote.**
For the two-pass state machine to work, every detected icon of a given type must show the same parsed count. If three farmhouses show "1.3K" and one shows "1.2K", the type is `still_filling` — not "mostly full". The "mostly full" false positive risk outweighs the false negative of waiting one more scan cycle.

**12. Never call `_ensure_wilderness()` during an HQ map pan sweep.**
The watcher's `_ensure_wilderness()` will interrupt a pan sweep and navigate away from HQ. The HQ session block in `watcher.py` prevents this by deferring all wilderness flows until the full HQ session is complete.

---

## 7. File Locations Quick Reference

```
lastz/
  config.yaml              ← all tunables
  flows/
    base.py                ← dismiss_overlay(), reset_ui()
    hq_nav.py              ← shared HQ navigation + run_in_hq() context manager
    drone_gift.py          ← Flow 4 (uses hq_nav)
    hq_resources.py        ← Flow 5 — HQ building resource collection
    alliance_gifts.py
  screen.py                ← capture(), capture_both(), physical_to_logical()
  vision.py                ← find_template(), find_all_templates(), cluster_matches()
  ocr.py                   ← read_duration_from_region(), parse_resource_amount()
  input.py                 ← click(), drag(), focus_game(), ensure_game_running()
  watcher.py               ← background daemon (HQ session block)

templates/active/          ← production templates (physical pixels)
templates/archive/         ← old/experimental crops

scripts/dev/               ← diagnostic and extraction scripts
  verify_hq_resource_templates.py
  diagnose_hq_resource_ocr.py
  extract_hq_resource_templates.py

logs/watcher.log           ← live watcher output
logs/hq_resources_state.json  ← two-pass state machine persistence
docs/
  WORKFLOW.md              ← this file
  ADDING_FLOWS.md          ← shorter checklist version
  ARCHITECTURE.md          ← module diagram
  TEMPLATES.md             ← template inventory
  SETUP.md                 ← first-time setup
```
