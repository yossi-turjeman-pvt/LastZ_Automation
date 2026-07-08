# Adding New Flows

This is the playbook for adding a new game automation flow.  HQ Patrol and HQ Resource Collection (Flow 5) are used as concrete examples.

## Checklist

1. [ ] Capture reference screenshots
2. [ ] Create/run a dev script to crop templates
3. [ ] Add templates to `templates/active/`
4. [ ] Create `lastz/flows/<flow_name>.py`
5. [ ] Register the flow in `lastz/cli.py`
6. [ ] Optionally add the flow to the watcher
7. [ ] Add a verification test in `tests/`

---

## Step 1: Capture Reference Screenshots

Open the game to each screen state involved in the flow. Capture each one:

```bash
screencapture -x ~/Downloads/flow_step1.png
screencapture -x ~/Downloads/flow_step2.png
# etc.
```

Name them descriptively. Open in Preview to identify bounding boxes.

---

## Step 2: Create a Crop Script in `scripts/dev/`

Create `scripts/dev/extract_hq_patrol_templates.py` (already exists — see that file for the pattern).

The script should:
- Load each reference screenshot
- Crop tightly around each UI element to match
- Save each crop to `templates/active/<name>.png`

Run it and verify the output images look correct.

---

## Step 3: Add Templates to `templates/active/`

Move (or confirm the script saved) the cropped templates to `templates/active/`. Update `docs/TEMPLATES.md` with the new rows.

Add any new thresholds to `config.yaml`:

```yaml
thresholds:
  patrol_claim_btn: 0.85
  patrol_golden_chest: 0.82
```

---

## Step 4: Create the Flow File

Create `lastz/flows/hq_patrol.py`:

```python
"""
Flow N — HQ Patrol (Car Lane Rewards).

Steps:
  1. Focus game and reset UI
  2. Open the HQ / Patrol screen
  3. Detect golden chest on the car lane
  4. Click Claim button
  5. Dismiss the Idle Reward modal (Collect)
  6. Close the patrol screen
"""
import time

from lastz.config import coord, threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.input import click, focus_game
from lastz.screen import capture
from lastz.vision import find_template


def run_hq_patrol_flow() -> None:
    focus_game()

    print("Resetting UI...")
    reset_ui(clicks=2, delay=1.0)

    # TODO: Open patrol screen — add coordinate to config.yaml
    # patrol_x, patrol_y = coord("patrol_button")
    # click(patrol_x, patrol_y)
    # time.sleep(2.0)

    screen = capture()
    chest = find_template(screen, "patrol_golden_chest.png", cfg_threshold("patrol_golden_chest"))
    if chest is None:
        print("-> No patrol golden chest found.")
        dismiss_overlay()
        return

    lx, ly = chest.phys_x / 2, chest.phys_y / 2
    print(f"-> Found patrol chest at ({lx:.1f}, {ly:.1f}). Clicking Claim...")
    click(lx, ly)
    time.sleep(1.5)

    screen2 = capture()
    collect = find_template(screen2, "patrol_collect_btn.png", cfg_threshold("patrol_claim_btn"))
    if collect is not None:
        clx, cly = collect.phys_x / 2, collect.phys_y / 2
        print(f"-> Clicking Collect at ({clx:.1f}, {cly:.1f})...")
        click(clx, cly)
        time.sleep(1.5)

    dismiss_overlay()
    print("HQ Patrol flow complete!")
```

---

## Step 5: Register in `lastz/cli.py`

Open `lastz/cli.py`. In `_header()`, add the new menu line:

```python
print(" 6. [Flow N]     HQ Patrol (Car Lane Rewards)")
```

In `main()`, add the handler:

```python
elif choice == "6":
    print("\n>>> Launching HQ Patrol Flow...")
    from lastz.flows.hq_patrol import run_hq_patrol_flow
    run_hq_patrol_flow()
    print(">>> HQ Patrol Flow finished!\n")
```

Also update the "Enter your choice (1-N)" prompt and the Exit option number.

---

## Step 6: Add to Watcher (Optional)

If the flow should run automatically, open `lastz/watcher.py` and add a trigger condition inside the loop — either on a schedule like alliance gifts, or on a detection condition like battle rewards.

**Important for HQ-mode flows:** Do not add HQ-mode flows to the wilderness phase of the watcher loop. Instead, add them to the HQ session block (see `_run_hq_session()` in `lastz/watcher.py`). This prevents the watcher from navigating away from HQ mid-sweep. The HQ Resources flow (Flow 5) is the worked example.

---

## Step 7: Add a Verification Test

Add a function to `tests/test_flow_verification.py` (or create a new test file) that runs the flow once and checks the final screen state is clean:

```python
def verify_hq_patrol():
    from lastz.flows.hq_patrol import run_hq_patrol_flow
    run_hq_patrol_flow()
    state = _capture_and_state("patrol_final")
    assert state == "MAIN_BASE_MAP_CLEAN", f"Unexpected state: {state}"
    print(f"HQ Patrol verification: {state}")
```

---

## Code Pattern Reference

Every flow follows the same structure:

```python
from lastz.config import coord, threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.input import click, focus_game
from lastz.screen import capture
from lastz.vision import find_template

def run_my_flow() -> None:
    focus_game()
    reset_ui()

    screen = capture()
    match = find_template(screen, "my_element.png", cfg_threshold("my_threshold"))
    if match is None:
        print("-> Element not found, skipping.")
        return

    lx, ly = match.phys_x / 2, match.phys_y / 2
    click(lx, ly)
    time.sleep(1.5)

    dismiss_overlay()
    print("Flow complete!")
```

The shared modules handle all the boilerplate: window focus, screencapture, OpenCV matching, Retina scaling, and click events.

## HQ Resource Collection — Worked Example (Flow 5)

Flow 5 demonstrates the most complex flow patterns in the project. Use it as a reference when building:
- **Multi-instance template matching** — `find_all_templates()` + `cluster_matches()`
- **Map panning** — `drag()` with a configurable pan grid
- **Resource-count OCR** — `read_resource_count_from_region()` + `parse_resource_amount()`
- **Two-pass state machine** — `logs/hq_resources_state.json`, `_passes_gating()`
- **Post-action verification** — re-scan after collecting to confirm success
- **HQ navigation sharing** — `lastz/flows/hq_nav.py` is imported by both Flow 4 and Flow 5

See `lastz/flows/hq_resources.py` for the complete implementation and inline comments.
