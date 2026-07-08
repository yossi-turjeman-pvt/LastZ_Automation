# Templates Reference

## Active Templates

These files in `templates/active/` are the only ones loaded by production flows. All other images in `templates/archive/` are intermediate R&D crops kept for reference.

| Filename | Used by | Threshold | What it matches |
|----------|---------|-----------|-----------------|
| `claim_all_button_clean.png` | Alliance Gifts (Common tab) | 0.82 | Green "Claim All" button at the bottom of the Common gifts list |
| `universal_claim_all_button.png` | Alliance Gifts (Common tab), Battle Rewards | 0.82 | The same green Claim All button — a tighter crop that works across both windows |
| `claim_button_clean.png` | Alliance Gifts (Common + Rare individual claim) | 0.85 | Individual blue "Claim" button next to a single gift item |
| `orange_icon_no_badge.png` | Battle Rewards detection | 0.82 | The orange chest icon without its dynamic badge number, so the match is stable regardless of the badge count |
| `hq_drone_gift_chest.png` | Drone Gift detection | 0.65 | Golden circular badge on the HQ building; lower threshold because a timer countdown is rendered on the badge |
| `drone_claim_btn.png` | Drone Gift | 0.80 | Green "Claim" button in the Area Exploration screen |
| `drone_collect_btn.png` | Drone Gift | 0.80 | Green "Collect" button in the Idle Reward modal |
| `hq_world_button.png` | Drone Gift — HQ mode detection | 0.70 | **Mode switcher — HQ face.** Shows "World" label when player is in HQ base. Clicking it goes to wilderness. Presence of this button = we are in HQ. |
| `wilderness_hq_button.png` | Drone Gift — wilderness→HQ navigation | 0.85 | **Mode switcher — Wilderness face.** Shows "Headquarters" label when player is in wilderness. Clicking it navigates to HQ base. |
| `hq_resource_food.png` | HQ Resource Collection (Flow 5) | 0.65 | Food badge on farmhouse buildings; inner meat/tin-can symbol only (excludes count label) |
| `hq_resource_wood.png` | HQ Resource Collection (Flow 5) | 0.75 | Wood badge on lumberyard buildings; inner log-bundle symbol |
| `hq_resource_energy.png` | HQ Resource Collection (Flow 5) | 0.65 | Energy badge on smelting plant buildings; inner lightning-bolt symbol |
| `hq_resource_gold.png` | HQ Resource Collection (Flow 5) | 0.65 | Gold badge on residence buildings; inner Z-coin symbol |
| `wilderness_enemy_hq.png` | Scouting (Flow 6) | 0.65 | Enemy HQ building on wilderness world map |
| `scout_action_btn.png` | Scouting (Flow 6) | 0.70 | Scout icon in enemy HQ detail modal |
| `drone_slot_idle.png` | Scouting (Flow 6) | 0.70 | Idle scout drone slot indicator |
| `drone_slot_busy.png` | Scouting (Flow 6) | 0.70 | In-use scout drone slot indicator |

> **Scouting templates** are produced by `scripts/dev/calibrate_scouting_flow.py`. Verify with `scripts/dev/verify_scouting_templates.py`.

> **Mode Switcher** (bottom-right corner): one physical button, two states.
> `hq_world_button` visible → you are **in HQ**. `wilderness_hq_button` visible → you are **in wilderness**.
> Any flow needing HQ mode should use `lastz/flows/hq_nav.py` — both Drone Gift and HQ Resources import from there.

> **HQ Resource Badge Templates**: These templates match the INNER SYMBOL only (not the numeric count).
> This keeps matching stable as the count changes while buildings fill.  Use a lower threshold
> (0.65–0.75) since the small badge has limited stable pixel area.  Tune with
> `scripts/dev/verify_hq_resource_templates.py`.
>
> **Important:** The initial reference screenshot contained red annotation arrows drawn on top of
> the icons.  The extract script strips those red pixels before saving, but for best results
> re-capture from a **clean live screenshot** (no arrows) and re-run
> `scripts/dev/extract_hq_resource_templates.py`.

## Template Lineage

How each active template was produced:

| Template | Source script | Source image |
|----------|--------------|--------------|
| `claim_all_button_clean.png` | `scripts/dev/find_green_button.py` or `scripts/dev/extract_claim_all_template.py` | `templates/archive/common_bottom.png` |
| `universal_claim_all_button.png` | `scripts/dev/extract_universal_claim_all.py` | `templates/archive/battle_rewards_bottom.png` |
| `claim_button_clean.png` | `scripts/dev/extract_claim_button_template.py` | `templates/archive/rare_list.png` |
| `orange_icon_no_badge.png` | `scripts/dev/crop_orange_icon_no_badge.py` | `templates/archive/orange_badge_icon_clean.png` |
| `hq_drone_gift_chest.png` | `scripts/dev/extract_drone_gift_templates.py` | `assets/5.1-*.png` |
| `drone_claim_btn.png` | `scripts/dev/extract_drone_gift_templates.py` | `assets/6.1-*.png` |
| `drone_collect_btn.png` | `scripts/dev/extract_drone_gift_templates.py` | `assets/7.1-*.png` |
| `hq_world_button.png` | `scripts/dev/extract_drone_gift_templates.py` | `assets/5.1-*.png` |
| `wilderness_hq_button.png` | captured live with `screencapture -x` from wilderness mode | live game screenshot |
| `hq_resource_food.png` | `scripts/dev/extract_hq_resource_templates.py` | `assets/8-e305994f-*.png` |
| `hq_resource_wood.png` | `scripts/dev/extract_hq_resource_templates.py` | `assets/8-e305994f-*.png` |
| `hq_resource_energy.png` | `scripts/dev/extract_hq_resource_templates.py` | `assets/8-e305994f-*.png` |
| `hq_resource_gold.png` | `scripts/dev/extract_hq_resource_templates.py` | `assets/8-e305994f-*.png` |

## How to Create a New Template

### 1. Capture a reference screenshot

With the game window showing the UI element you want to match, capture the full screen:

```bash
screencapture -x /tmp/reference.png
```

Open the image in Preview to find the pixel bounding box of the element (hover to see coordinates in the status bar).

### 2. Write a crop script in `scripts/dev/`

Create a small Python script (e.g. `scripts/dev/crop_new_element.py`) using Pillow:

```python
from PIL import Image

im = Image.open("/tmp/reference.png")
# Crop tightly around the element; avoid dynamic parts (text, badge numbers)
# Box format: (left, upper, right, lower) in physical pixels
box = (left, upper, right, lower)
im.crop(box).save("templates/active/new_element.png")
print("Template saved.")
```

### 3. Test the match

Use `scripts/dev/find_template.py` or a quick one-off script:

```python
import cv2, subprocess

subprocess.run(["screencapture", "-x", "/tmp/screen.png"])
screen = cv2.imread("/tmp/screen.png", cv2.IMREAD_GRAYSCALE)
template = cv2.imread("templates/active/new_element.png", cv2.IMREAD_GRAYSCALE)

result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
_, max_val, _, max_loc = cv2.minMaxLoc(result)
print(f"Confidence: {max_val:.4f}  Location: {max_loc}")
```

A confidence above 0.85 when the element is present, and below 0.5 when absent, is a good target.

### 4. Add to config.yaml

If you are using a new threshold, add it under `thresholds:` in `config.yaml`.

### 5. Use in a flow

```python
from lastz.vision import find_template
from lastz.screen import capture

screen = capture()
match = find_template(screen, "new_element.png", threshold=0.85)
if match is not None:
    lx, ly = match.phys_x / 2, match.phys_y / 2
    click(lx, ly)
```

## Tips

- **Crop tightly** — include only the stable part of the element. Exclude surrounding backgrounds, dynamic badges, scrollbars.
- **Avoid text** in templates unless you want to match that exact string. Icon-only crops are more robust.
- **Retina coordinates**: all physical pixel values are 2× the logical click coordinates. A screenshot pixel at `(1512, 300)` is clicked at logical `(756, 150)`.
- **Threshold guidance**: start at `0.85`. If you get false negatives (element present but not matched), lower to `0.82`. If you get false positives, raise to `0.90`.
