# Setup Guide

## 1. System requirements

- macOS 12 (Monterey) or later
- Python 3.10+
- LastZ (`Survival.exe`) running, visible, and not minimized
- Game may run natively or through CrossOver / Wine — the process name must still match `config.yaml` (default `Survival.exe`)

No Tesseract / OCR install is required. Alliance Gifts uses template matching only.

## 2. Install Python dependencies

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

This installs: `opencv-python`, `numpy`, `Pillow`, `PyYAML`.

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

With the game visible on screen:

```bash
source .venv/bin/activate
python -m lastz
```

Choose **1** (Claim Alliance Gifts once). You should see:

1. UI reset clicks
2. Alliance menu open
3. Alliance Gifts open
4. Common tab claim (Claim All when available)
5. Rare tab claim
6. Two outside clicks to close Gifts, then Alliance

If nothing happens:

- Confirm `Survival.exe` appears in Activity Monitor (or update `game.process_name` in `config.yaml`)
- Confirm the game window is frontmost and not covered
- Re-check Accessibility + Screen Recording for the exact app launching Python

## 5. Display / template matching

Navigation is **template-based**, not fixed absolute coordinates. On first match, `lastz/vision.py` auto-calibrates template scale using the HQ ↔ Wilderness map buttons (`wilderness_hq_button.png` / `hq_world_button.png`).

If match confidence is consistently low:

1. Leave the game on the wilderness/base map (no modal open)
2. Confirm those two anchor templates still look like the on-screen buttons
3. Re-crop replacements into `templates/active/` at the same filenames if the UI changed
4. Tune thresholds in `config.yaml` under `thresholds:`

The only fixed click offset is `coordinates.dismiss_outside` — a logical offset from the **game window top-left**, used to dismiss overlays by clicking empty map area.

## 6. Watcher loop

Menu option **2** (or `python lastz_watcher.py`) runs Alliance Gifts every `watcher.alliance_interval_sec` seconds (default 180). Logs append to `logs/watcher.log` (gitignored).

Stop with `Ctrl+C`.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `GameNotRunningError` / won't focus | Wrong process name | Check Activity Monitor; update `game.process_name` |
| Clicks miss buttons | Scale / window layout mismatch | Keep game full-visible; let auto-scale run on wilderness map; re-crop templates if UI changed |
| Alliance / Gifts not found | Template mismatch | Recapture `alliance_shield_clean.png` / `alliance_gifts_precise.png` into `templates/active/` |
| Rare tab claims click footer/back | Older code without footer filter | Current code ignores claim matches below 52% screen height; update to latest |
| Screen capture fails / blank | Missing Screen Recording permission | Grant permission and restart terminal |
| Clicks do nothing | Missing Accessibility permission | Grant permission and restart terminal |
