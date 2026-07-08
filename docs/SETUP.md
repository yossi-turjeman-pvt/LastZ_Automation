# Setup Guide

## 1. System Requirements

- macOS 12 (Monterey) or later
- Python 3.10+
- Retina display (2560×1600 or higher). If you have a non-Retina display, set `retina_scale: 1.0` in `config.yaml`.
- Survival.exe must be running, visible, and not minimised when you trigger a flow.

## 2. Python Dependencies

From the project root:

```bash
pip install -r requirements.txt
```

This installs: `opencv-python`, `numpy`, `Pillow`, `PyYAML`, `pytesseract`.

### Tesseract OCR (required for Flow 4 — Drone Gift, and Flow 5 — HQ Resources)

`pytesseract` is a Python wrapper around the Tesseract OCR engine. Install the engine itself with Homebrew:

```bash
brew install tesseract
```

Flow 4 uses OCR to read the `HH:MM:SS` exploration timer. Flow 5 uses OCR to read resource count labels ("1.3K", "291", etc.) from the floating building badges. If Tesseract is not installed, both flows will skip collection safely rather than crashing.

## 3. macOS Permissions

The automation uses two system APIs that require explicit permission grants.

### Accessibility (for mouse clicks)

The script sends synthetic mouse events via CoreGraphics. macOS blocks this unless the calling process has Accessibility permission.

1. Open **System Settings → Privacy & Security → Accessibility**
2. Click the **+** button and add your terminal app (Terminal, iTerm2, or the app you use to run Python)
3. Make sure the toggle is **on**

### Screen Recording (for screencapture)

The script captures the screen with `screencapture -x`. macOS requires Screen Recording permission for this.

1. Open **System Settings → Privacy & Security → Screen Recording**
2. Add your terminal app and toggle it **on**
3. Restart your terminal after granting this permission

## 4. Verify Your Setup

Run a quick sanity check before using the automation for the first time:

```bash
python -m lastz
```

Choose option **1** (Alliance Gifts). Watch the game window — the Alliance menu should open and the automation should navigate to the Gifts window. If nothing happens:

- Check that the game window is visible and not behind other windows
- Check that the process name in `config.yaml` matches what appears in Activity Monitor (default: `Survival.exe`)
- Check that both Accessibility and Screen Recording permissions are granted for your terminal

## 5. Display Calibration

The automation uses fixed logical coordinates (e.g. the Alliance menu button is at `[1480, 757]`). These were calibrated on a specific screen layout. If buttons are not being hit:

1. Capture a screenshot: `screencapture -x /tmp/test.png`
2. Open it in Preview and hover over the button you want to calibrate
3. Note the pixel coordinates shown in the status bar (these are physical pixels)
4. Divide by `retina_scale` (default `2.0`) to get the logical coordinate
5. Update `config.yaml` under `coordinates:`

## 6. Calibrating HQ Resource Templates (Flow 5)

After first install, run the verification script to confirm template confidence on your display:

```bash
python3 scripts/dev/verify_hq_resource_templates.py
```

If confidence is below 0.60 for icons that are clearly visible, re-extract the templates from a live screenshot:

```bash
screencapture -x ~/Downloads/hq_ref.png   # while game is in HQ with icons visible
# Edit CROPS in scripts/dev/extract_hq_resource_templates.py with new coordinates
python3 scripts/dev/extract_hq_resource_templates.py
```

If OCR reads wrong values, run the diagnosis script:

```bash
python3 scripts/dev/diagnose_hq_resource_ocr.py
```

Review the `logs/debug/hq_resources/*_proc.png` images and adjust `count_crop_offset` in `config.yaml`.

## 7. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Game window does not focus | Wrong process name | Check Activity Monitor for the exact process name and update `config.yaml` |
| Clicks land in wrong spot | Retina scale mismatch | Adjust `retina_scale` in `config.yaml` or recalibrate coordinates |
| Template match confidence very low | Game UI changed or wrong resolution | Recapture and re-crop the template (see `docs/TEMPLATES.md`) |
| HQ Resources never collects | Low template confidence or OCR failures | Run verify and diagnose scripts; check `logs/hq_resources_state.json` |
| HQ Resources collects too early | Confirm interval too short | Raise `watcher.hq_resources_confirm_sec` in `config.yaml` |
| OpenCV assertion error in watcher | Template file larger than screen image | This is guarded in `lastz/vision.py`; check that the template file is not corrupted |
| No Screen Recording permission dialog | Terminal was never shown the dialog | Grant permission manually via System Settings |
