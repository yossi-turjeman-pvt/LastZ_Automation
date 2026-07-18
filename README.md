# LastZ Automation

macOS automation for **LastZ** (`Survival.exe`) that claims **Alliance Gifts** (Common + Rare) on a timer.

It works at the OS level only: screen capture + synthetic mouse clicks. It does not modify game files or talk to game servers.

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
| 1 | Claim Alliance Gifts (once) | One full Common + Rare claim pass |
| 2 | Watcher loop | Repeats Alliance Gifts every `alliance_interval_sec` (default **180s**) |
| 3 | Exit | Quit |

## Configuration

All tunables live in [`config.yaml`](config.yaml):

| Key | Purpose |
|-----|---------|
| `game.process_name` | Process to focus (default `Survival.exe`) |
| `paths.templates_dir` | Template folder (default `templates/active`) |
| `watcher.alliance_interval_sec` | Seconds between watcher claim runs |
| `thresholds.*` | OpenCV match confidence cutoffs |
| `coordinates.dismiss_outside` | Window-relative click used to close overlays |

Example:

```yaml
watcher:
  alliance_interval_sec: 180
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
│   ├── vision.py            # Template matching
│   └── flows/
│       ├── alliance_gifts.py
│       └── base.py
├── templates/active/        # Templates used by the bot (required)
├── docs/                    # Setup + architecture + flow notes
└── tests/                   # Unit / verification helpers
```

Production templates are only under **`templates/active/`**. Other PNGs under `templates/` (if present) are leftovers and are not used at runtime.

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/SETUP.md](docs/SETUP.md) | Permissions, install checks, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How capture / vision / clicks work |
| [docs/FLOWS.md](docs/FLOWS.md) | Alliance Gifts step-by-step |

## Disclaimer

This tool automates in-game actions. Using automation may violate the game's Terms of Service. Use at your own risk.
