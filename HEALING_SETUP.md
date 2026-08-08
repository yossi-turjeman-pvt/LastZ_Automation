# Healing Flow Setup Guide

## Status: 🚧 Ready for Templates

The healing flow code is implemented and integrated into the Help watcher (menu 4).
You now need to capture 4 template images for the flow to work.

## Templates Needed

Capture these templates and save them in `templates/active/`:

### 1. `healing_wounded.png`
- **When**: Troops are wounded and need healing
- **Where**: Left-bottom HUD area (bandage icon with blood drop)
- **Icon state**: Shows red badge or wounded indicator
- **Capture**: Crop tightly around just the icon

### 2. `healing_ask_help.png`
- **When**: After clicking "Heal" button
- **Where**: Same location as healing_wounded (icon changes)
- **Icon state**: Shows "Ask Alliance to speed up"
- **Capture**: Crop tightly around just the icon

### 3. `healing_complete.png`
- **When**: Healing is finished
- **Where**: Same location (icon changes again)
- **Icon state**: Shows "Collect healed troops" or completion indicator
- **Capture**: Crop tightly around just the icon

### 4. `healing_heal_button.png`
- **When**: Healing modal is open
- **Where**: Inside the healing modal (big "Heal" button)
- **Icon state**: The main action button that starts healing
- **Capture**: Crop around the button (include some context)

## How to Capture Templates

1. **Open the game** and navigate to wilderness
2. **Get wounded troops** (if you don't have any)
3. **Click the healing icon** to open the modal
4. **Take screenshots** using macOS built-in capture:
   - `Cmd + Shift + 4` then drag to select area
   - Or use `Cmd + Shift + 5` for more options
5. **Crop tightly** around each UI element
6. **Save as PNG** in `templates/active/`

## Configuration

The healing flow is configured in `config.yaml`:

```yaml
healing:
  enabled: true                # Set to false to disable healing
  batch_size: 50               # Total troops to heal per batch
  check_interval_sec: 5.0      # How often to check for healing (seconds)
  icon_band: [0.75, 1.0, 0.0, 0.20]  # Left-bottom HUD search area

thresholds:
  healing_wounded: 0.72        # Confidence for wounded icon
  healing_ask_help: 0.72       # Confidence for ask help icon
  healing_complete: 0.72       # Confidence for complete icon
  healing_heal_button: 0.75    # Confidence for heal button
```

## How It Works

1. **Runs in parallel** with Help watcher (menu 4)
2. **Prioritizes healing** over help clicks
3. **Checks every 5 seconds** (configurable) for healing icons
4. **Healing cycle**:
   - Detects wounded troops → clicks icon
   - Opens modal → clicks Heal button
   - Asks alliance help → waits
   - Collects when complete → loops if more wounded

5. **Resource failure**: If healing fails (no resources), logs warning and continues help watcher

## Known Limitations (TODOs)

### 1. Batch Size Entry ⚠️
**Current**: Code clicks "Heal" button with whatever value is already set
**TODO**: Implement clicking on number field and typing batch_size (50)

This requires:
- Finding the number input field in the modal
- Clicking it to select
- Typing the batch size value
- Confirming/pressing Enter

### 2. Resource Detection
**Current**: If healing fails, code assumes it's due to lack of resources
**TODO**: More specific detection of failure reasons

### 3. Healing Time Tracking
**Current**: Code just polls for completion icon
**TODO**: Could track expected healing time and reduce polling frequency

## Testing

After capturing templates:

```bash
# 1. Test template matching
python -m lastz.flows.vision_scout  # Check if icons are detected

# 2. Run help watcher with healing
python -m lastz
# Select menu option 4
# Watch logs/healing.log for healing activity
# Watch logs/help_watcher.log for help clicks
```

## Logs

- **Healing activity**: `logs/healing.log`
- **Help watcher**: `logs/help_watcher.log`
- **Debug crashes**: `logs/debug/flow/crash_*.png`

## Next Steps

1. ✅ Code implemented and integrated
2. ⏳ **Capture 4 template images** (you do this)
3. ⏳ Test with real wounded troops
4. ⏳ Implement batch size number field clicking (if needed)
5. ⏳ Fine-tune thresholds if icons aren't detected reliably

---

**Ready to test!** Just need those 4 template images.
