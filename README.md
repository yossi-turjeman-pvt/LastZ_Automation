# LastZ Automation

macOS automation for LastZ (Survival.exe) — claims Alliance Gifts, Battle Rewards, collects HQ building resources, and runs a background watcher daemon so you never miss a reward.

## Quick Start

### Prerequisites

- macOS with a Retina display (or set `retina_scale: 1.0` in `config.yaml` for non-Retina)
- Python 3.10+
- Survival.exe running and visible on screen
- Tesseract OCR installed (required for Flows 4 & 5): `brew install tesseract`
- macOS permissions granted (see [docs/SETUP.md](docs/SETUP.md))

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
source .venv/bin/activate   # if not already active
python -m lastz
```

## Menu Options

| # | Name | Description |
|---|------|-------------|
| 1 | Alliance Gifts | Claims Common and Rare gifts from the Alliance Gifts window |
| 2 | Battle Rewards | Detects the orange chest badge and claims Battle Rewards |
| 3 | Drone Gift | Collects the HQ Area Exploration idle reward when timer >= 8h |
| 4 | HQ Resources | Scans all HQ buildings; collects resource types ready at capacity |
| 5 | HQ Resources (Dry Run) | Same scan but logs would-be clicks without executing them |
| 6 | Full Loop | Runs all flows in sequence |
| 7 | Watcher | Starts the background daemon (HQ Resources every 2.5 min, Drone Gift every 5 min) |
| 8 | Exit | Quit |

## Project Structure

```
LastZ_Automation/
├── lastz/              ← Python package (all production code)
│   ├── config.py       ← Config loader (reads config.yaml)
│   ├── input.py        ← click(), drag(), focus_game()
│   ├── screen.py       ← screencapture + Retina scaling
│   ├── vision.py       ← Template matching (single + multi + cluster)
│   ├── ocr.py          ← Timer and resource count OCR
│   ├── watcher.py      ← Background daemon (HQ session batching)
│   ├── cli.py          ← Interactive menu
│   └── flows/          ← One file per game flow
│       ├── hq_nav.py   ← Shared HQ ↔ Wilderness navigation
│       └── hq_resources.py ← Flow 5 — building resource collection
├── templates/
│   ├── active/         ← Templates used by production flows
│   └── archive/        ← Intermediate R&D crops (reference only)
├── scripts/
│   ├── dev/            ← Reusable template-authoring and diagnostic tools
│   └── archive/        ← One-off experiments (kept for reference)
├── tests/              ← Unit + verification tests
├── logs/               ← watcher.log, hq_resources_state.json (gitignored)
├── docs/               ← Full documentation
└── config.yaml         ← All tunables (coordinates, thresholds, intervals)
```

## Configuration

All coordinates, thresholds, and timing are in `config.yaml`. Edit this file to tune the automation without touching flow code.

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/SETUP.md](docs/SETUP.md) | macOS permissions, display requirements, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the input/vision pipeline works, Retina scaling |
| [docs/FLOWS.md](docs/FLOWS.md) | Step-by-step walkthrough of each flow |
| [docs/TEMPLATES.md](docs/TEMPLATES.md) | Active templates, how they were made, how to add new ones |
| [docs/ADDING_FLOWS.md](docs/ADDING_FLOWS.md) | Playbook for adding new game flows (e.g. HQ Patrol) |

## Disclaimer

This tool automates in-game actions. Using automation software may violate the game's Terms of Service. Use at your own risk.
