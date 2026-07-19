# Setup Guide

## 1. System requirements

- macOS 12 (Monterey) or later
- Python 3.10+
- LastZ (`Survival.exe`) running, visible, and not minimized
- Game may run natively or through CrossOver / Wine — the process name must still match `config.yaml` (default `Survival.exe`)

No per-machine calibration step is required. Scale and clicks adapt from the live game window automatically.

**OCR (HQ drone gift timer):** install Tesseract on macOS:

```bash
brew install tesseract
pip install pytesseract   # also listed in requirements.txt
```

Without Tesseract, drone gift collection skips safely when the timer cannot be read.

## 2. Install Python dependencies

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

This installs: `opencv-python`, `numpy`, `Pillow`, `PyYAML`, `pytesseract`.

## 3. macOS permissions

### Accessibility (mouse clicks)

The bot posts synthetic mouse events via CoreGraphics.

1. Open **System Settings → Privacy & Security → Accessibility**
2. Add your terminal app (Terminal, iTerm2, Cursor, etc.)
3. Ensure the toggle is **on**

### Screen Recording (`screencapture`)

1. Open **System Settings → Privacy & Security → Screen Recording**
2. Add the same terminal app and toggle it **on**
3. Quit and reopen the terminal after granting permission

## 4. Verify setup

With the game visible on the **wilderness / base map** (no modal open), fully on one display:

```bash
source .venv/bin/activate
python -m lastz
```

Choose **1** (Claim Alliance Gifts once). You should see:

1. A log line like `[vision] Auto template scale: … (anchor=… conf=…)`
2. UI reset clicks
3. HQ Drone Gift — collect if Exploration Duration ≥ `08:00:00` (otherwise skipped); then return to Wilderness
4. Battlefield Gifts chest claimed if the wilderness icon is present (otherwise skipped)
5. Alliance menu open
6. Alliance Gifts open
7. Common tab claim (Claim All when available)
8. Rare tab claim
9. Alliance Techs blue Donate (if available)
10. Outside clicks to close Gifts / Techs / Alliance

If nothing happens:

- Confirm `Survival.exe` appears in Activity Monitor (or update `game.process_name` in `config.yaml`)
- Confirm the game window is frontmost and not covered / split across monitors
- Re-check Accessibility + Screen Recording for the exact app launching Python

## 5. Display / template matching (full dynamic)

Navigation is **template-based** inside the **game window ROI**:

1. Capture the display that contains the game
2. Discover template scale from on-screen anchors (HQ/wilderness switchers, Alliance shield, optional Battlefield chest)
3. Match UI templates at that scale (with a full-band refine if needed)
4. Click match centers mapped through the live window bounds
5. Dismiss overlays at `coordinates.dismiss_outside_frac` of the window

If match confidence is consistently low:

1. Leave the game on the wilderness/base map (no modal open)
2. Keep the window fully visible on a single display
3. Confirm templates in `templates/active/` still look like the on-screen buttons
4. Re-crop replacements at the same filenames if the game UI changed
5. Tune thresholds in `config.yaml` under `thresholds:`

Check the console for `[vision] Auto template scale` and per-template confidence lines.

## 6. Watcher loop

Menu option **2** (or `python lastz_watcher.py`) runs the gifts flow every `watcher.alliance_interval_sec` seconds (default 180). Logs append to `logs/watcher.log` (gitignored).

Stop with `Ctrl+C`.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `GameNotRunningError` / won't focus | Wrong process name | Check Activity Monitor; update `game.process_name` |
| Clicks miss buttons | Weak scale / window not fully visible | Wilderness map, one display; look for `WARN: weak anchors` in the log |
| Alliance / Gifts not found | Template mismatch | Recapture `alliance_shield_clean.png` / `alliance_gifts_precise.png` into `templates/active/` |
| Rare tab claims click footer/back | Claim Y cutoff too low or too high | List Claims use `CLAIM_MAX_Y_FRAC=0.82` + green HSV; footer matches are ignored |
| Screen capture fails / blank | Missing Screen Recording permission | Grant permission and restart terminal |
| Clicks do nothing | Missing Accessibility permission | Grant permission and restart terminal |
| Wrong display captured | Multi-monitor / game on secondary | Move game fully onto one screen |
