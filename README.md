# LastZ Automation

macOS automation for **LastZ** (`Survival.exe`) that runs a **gifts collection** flow on a timer: HQ Drone Gift (when ≥ 08:00:00) + Battlefield chest + Alliance Gifts (Common + Rare) + Alliance Techs gold donations.

Vision uses **spatial bands** so high-confidence false positives (map help thumbs, Wars chrome, wrong shield hits) are rejected. Observe-only scout (no Claim/Donate): `python -m lastz.flows.vision_scout`.

It works at the OS level only: screen capture + synthetic mouse clicks. It does not modify game files or talk to game servers.

**Full dynamic clicks:** template scale is auto-detected from the live game window each run. Action clicks use match centers; dismiss uses fractions of the current window size. No per-machine calibration step.

HQ drone timers use **OCR** (`pytesseract` + system Tesseract). See [docs/SETUP.md](docs/SETUP.md).

## Quick Start

### Prerequisites

- macOS 12+ (Monterey or later)
- Python 3.10+
- LastZ running and visible (`Survival.exe` — native or via CrossOver / Wine)
- macOS **Accessibility** and **Screen Recording** permissions for your terminal (see [docs/SETUP.md](docs/SETUP.md))

### Install

```bash
git clone <your-repo-url> LastZ_Automation
cd LastZ_Automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
source .venv/bin/activate
python -m lastz
```

Equivalent entry points:

```bash
python lastz_auto_master.py   # same as python -m lastz
python lastz_watcher.py       # start the watcher loop directly
```

## Menu

| # | Option | What it does |
|---|--------|----------------|
| 1 | Claim Alliance Gifts (once) | Runs the full collection sequence once (see below) |
| 2 | Watcher loop | Repeats that same sequence every `alliance_interval_sec` (default **180s**) |
| 3 | Fix Hebrew (CrossOver bottle) | Copies Hebrew fonts into the bottle + sets `LANG`/`LC_ALL=he_IL.UTF-8` (fixes `???` / RTL chat under CrossOver). Bottle name: `crossover.bottle_name` in `config.yaml`. Restart CrossOver after running. |
| 4 | Exit | Quit |

Menu **1** and **2** run the **same** flow. There are no separate menus for drone, battlefield, gifts, or techs.

### What menu 1 / 2 collects

In order:

1. **HQ Drone Gift (Area Exploration idle reward)**  
   Goes to Headquarters, reads the timer under the gift chest, and collects only if duration ≥ `drone_gift.min_duration` (default **08:00:00**). Then returns to Wilderness. Skips if the chest is missing (cooldown), the timer is lower, or OCR fails.

2. **Battlefield Gifts**  
   If the orange wilderness chest icon is visible, opens it and Claim All. Skips if the icon is not on screen.

3. **Alliance Gifts — Common**  
   Opens Alliance → Alliance Gifts → Common tab. Uses **Claim All** when present (one outside click to clear the reward popup), otherwise individual green **Claim** buttons.

4. **Alliance Gifts — Rare**  
   Switches to the Rare tab and claims the same way (Claim All if present, else green Claims).

5. **Alliance Techs — gold Donate**  
   Opens Alliance Techs, picks a recommended tech (orange thumbs-up) or a lit hex, then clicks the **blue** Donate button until it is no longer blue / available (capped by `alliance_techs.max_donates`).

### What it does **not** collect

These are **out of scope** for the current bot (removed or never part of this slim flow):

- Achievements / quest rewards / daily login calendars  
- Bounties / wanted / hunt boards  
- HQ building floating resources (food, wood, energy, gold, EXP pickups)  
- Mail / inbox claims  
- Scouting / exploration map loops (beyond the single HQ drone idle chest)  
- Alliance Help, Wars, Shop, or other Alliance tiles  

If something is not in the list above, assume it is **not** automated.

## Configuration

All tunables live in [`config.yaml`](config.yaml):

| Key | Purpose |
|-----|---------|
| `game.process_name` | Process to focus (default `Survival.exe`) |
| `paths.templates_dir` | Template folder (default `templates/active`) |
| `watcher.alliance_interval_sec` | Seconds between watcher claim runs |
| `drone_gift.min_duration` | Collect HQ drone only at/above this timer (default `08:00:00`) |
| `thresholds.*` | OpenCV match confidence cutoffs |
| `coordinates.dismiss_outside_frac` | Dismiss click as fractions of game window `[fx, fy]` |

Example:

```yaml
watcher:
  alliance_interval_sec: 180
coordinates:
  dismiss_outside_frac: [0.06, 0.28]
```

## Project layout

```
LastZ_Automation/
├── config.yaml              # Thresholds, intervals, process name
├── requirements.txt         # Python deps
├── lastz/                   # Package
│   ├── cli.py               # Interactive menu
│   ├── watcher.py           # Timed Alliance Gifts loop
│   ├── config.py            # Loads config.yaml
│   ├── input.py             # Focus + click
│   ├── screen.py            # screencapture + coordinate mapping
│   ├── vision.py            # Template matching (auto scale + window ROI)
│   ├── ocr.py               # Timer OCR for HQ drone gift
│   └── flows/
│       ├── alliance_gifts.py
│       ├── drone_gift.py
│       ├── hq_nav.py
│       └── base.py
├── templates/active/        # Templates used by the bot (required)
├── docs/                    # Setup + architecture + flow notes
└── tests/                   # Unit / verification helpers
```

Production templates are only under **`templates/active/`**.

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/SETUP.md](docs/SETUP.md) | Permissions, install checks, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How capture / vision / clicks work |
| [docs/FLOWS.md](docs/FLOWS.md) | Collection step-by-step (Drone + Battlefield + Gifts + Techs) |

After a failed run, share **`logs/runs.log`** (and any `logs/debug/flow/crash_*.png`). The watcher also writes `logs/watcher.log`.

## Disclaimer

This tool automates in-game actions. Using automation may violate the game's Terms of Service. Use at your own risk.
