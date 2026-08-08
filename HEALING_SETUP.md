# Healing Flow Setup Guide

## Status: ✅ Implemented

The healing flow is fully implemented and integrated into the Help watcher (menu 4):
templates are captured, batch-size entry is automated and OCR-verified, and
multiple troop types' completion icons are detected.

## Templates

All captured, in `templates/active/`:

### 1. `healing_wounded.png`
- **When**: Troops are wounded and need healing
- **Where**: Left-bottom HUD area (bandage icon with red badge)

### 2. `healing_ask_help.png`
- **When**: After clicking "Heal" in the modal
- **Where**: Same HUD slot as healing_wounded (icon changes to a handshake icon)

### 3. `healing_complete.png`, `healing_complete_2.png`, `healing_complete_3.png`
- **When**: A healing batch finishes
- **Where**: Same HUD slot again - each troop type (Destroyer / Charge Knight /
  Mercenary) shows its own portrait as the "done, collect" icon, not one
  shared icon. `check_and_collect_healing()` checks every `healing_complete*.png`
  file found under `templates/active/` (via `_complete_icon_names()`), so
  adding a 4th troop type later is a template drop-in, no code change needed.

### 4. `healing_heal_button.png`
- **Where**: Inside the Hospital modal - the blue "Heal" button

### 5. `healing_minus_button.png`, `healing_plus_button.png`
- **Where**: Inside the Hospital modal - the "-"/"+" steppers next to the
  topmost troop row's quantity field. Used to set the batch size (see below).

## Configuration

The healing flow is configured in `config.yaml`:

```yaml
healing:
  enabled: true                # Set to false to disable healing
  batch_size: 50                # Total troops to heal per batch
  check_interval_sec: 5.0       # How often to check for healing (seconds)
  icon_band: [0.75, 1.0, 0.0, 0.20]  # Left-bottom HUD search area

thresholds:
  healing_wounded: 0.72
  healing_ask_help: 0.72
  healing_complete: 0.58        # lower than the others - the icon has a
                                # pulsing "done" animation that live-observed
                                # dips genuine matches to ~0.65
  healing_heal_button: 0.75
  healing_minus_button: 0.72
  healing_plus_button: 0.75
```

## How It Works

1. **Runs in parallel** with Help watcher (menu 4), prioritized over help clicks
   (see `lastz/flows/help_watcher.py`'s comment on why this isn't backgrounded
   to a thread).
2. **Checks every 5 seconds** (configurable) for healing icons.
3. **Healing cycle** (`check_and_heal_once`):
   - Detects wounded troops → clicks icon → opens Hospital modal
   - Sets the topmost troop row's quantity to `batch_size`, via the +/-
     steppers (the field is a game-rendered widget, not a native text
     input, so typing/paste doesn't work) - see "Batch size entry" below
   - Clicks Heal → clicks the ask-alliance-help icon that appears afterward
4. **Collection** (`check_and_collect_healing`): polls for any of the
   troop-portrait "done" icons and collects when found, looping back to
   check for more wounded troops.
5. **Safety**: if the batch size can't be set and verified, the cycle
   aborts (closes the modal, retries next poll) rather than clicking Heal
   with an unverified/guessed quantity.

## Batch size entry

Since the quantity field doesn't accept typing, batch size is set by
clicking the +/- steppers, with the result verified via OCR rather than
trusted:

1. Rapid-click "-" an initial amount (`batch_size + margin`), covering the
   common case where the leftover value from a prior run is close to
   `batch_size`.
2. OCR-read the field (`lastz/ocr.py`'s `read_stepper_number`, tuned for
   this field's dark-digits-on-flat-gray-background look, distinct from
   `read_ui_text`'s white-outlined-label heuristic).
3. If not yet 0, click "-" more and re-read, up to a bounded number of
   rounds.
4. If it's still not verified at 0 (or tesseract is unavailable), the cycle
   aborts safely rather than proceeding with an unverified quantity.
5. Once verified at 0, click "+" exactly `batch_size` times.

## Known Limitations

1. **Resource detection**: if healing fails to start, the code assumes it's
   likely due to insufficient resources (food/wood) since that's the most
   common cause - it doesn't distinguish other failure reasons.
2. **Healing time tracking**: the code just polls for the completion icon
   every `check_interval_sec` rather than tracking the modal's displayed
   duration and reducing polling frequency while waiting.

## Testing

```bash
# Unit tests (no live game needed)
pytest tests/test_healing.py -v

# Live: run help watcher with healing
python -m lastz
# Select menu option 4
# Watch logs/healing.log for healing activity
# Watch logs/help_watcher.log for help clicks
```

## Logs

- **Healing activity**: `logs/healing.log`
- **Help watcher**: `logs/help_watcher.log`
- **Debug crashes**: `logs/debug/flow/crash_*.png`
