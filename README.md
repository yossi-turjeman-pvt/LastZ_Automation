# LastZ Automation

macOS automation for **LastZ** (`Survival.exe`) that runs a **gifts collection** flow on a timer: HQ Drone Gift (when ≥ 08:00:00) + Battlefield chest + Alliance Gifts (Common + Rare) + Alliance Techs gold donations + **Trucks** (claim + send orange from the upper slot).

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
| 3 | Fix Hebrew (CrossOver bottle) | **One-time bottle setup** (see below) — not part of the gifts flow |
| 4 | Exit | Quit |

Menu **1** and **2** run the **same** flow. There are no separate menus for drone, battlefield, gifts, or techs.

### Fix Hebrew (CrossOver) — run once

Menu **3** is a **one-time setup** for CrossOver users whose in-game Hebrew chat shows as `???` or reversed text. It is **not** something you run every session.

It:

1. Copies Hebrew-capable fonts into the bottle’s `windows/Fonts` folder  
2. Sets `LANG` / `LC_ALL` to `he_IL.UTF-8` in that bottle’s `cxbottle.conf`

**When to run it**

- Once after installing the game in CrossOver, **or**
- Again only if you **recreate** the bottle / wipe bottle fonts or locale

**After running:** fully quit CrossOver (and the game), then relaunch. You do not need menu **3** for normal gifts collection.

Bottle name defaults to `Last Z` via `crossover.bottle_name` in [`config.yaml`](config.yaml). Safe to re-run (idempotent), but unnecessary once chat already looks correct.

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

6. **Trucks** (when `trucks.include_trucks_flow` is true — default)  
   Opens only if the left-HUD truck icon has a **red badge**, or on every **`open_every_n_runs`** gifts run (default **5**). Then: **My Truck** → claim arrived chest → if under **4/4** and the **upper** slot is empty, refresh for **orange** (unless `allow_purple_trucks`) → **Go** → **Escape**. Upper slot en route → leave it.

### What it does **not** collect

These are **out of scope** for the current bot (removed or never part of this slim flow):

- Achievements / quest rewards / daily login calendars  
- Bounties / wanted / hunt boards  
- HQ building floating resources (food, wood, energy, gold, EXP pickups)  
- Mail / inbox claims  
- Scouting / exploration map loops (beyond the single HQ drone idle chest)  
- Alliance Help, Wars, Shop, or other Alliance tiles  
- Lower truck slots (only the **upper** slot is used for sending)  
- Plundering other players’ trucks  

If something is not in the list above, assume it is **not** automated.

## Configuration

Tunables live in [`config.yaml`](config.yaml). See **Configuration flags** below for the full flag reference.

```yaml
watcher:
  alliance_interval_sec: 180
trucks:
  include_trucks_flow: true
  allow_purple_trucks: false
  open_every_n_runs: 5
coordinates:
  dismiss_outside_frac: [0.06, 0.28]
```

## Project layout

```
LastZ_Automation/
├── config.yaml              # Thresholds, intervals, process name, feature flags
├── requirements.txt         # Python deps
├── lastz/                   # Package
│   ├── cli.py               # Interactive menu
│   ├── crossover_hebrew.py  # One-time CrossOver Hebrew/RTL bottle fix
│   ├── watcher.py           # Timed Alliance Gifts loop
│   ├── config.py            # Loads config.yaml
│   ├── input.py             # Focus + click + Escape
│   ├── screen.py            # screencapture + coordinate mapping
│   ├── vision.py            # Template matching (auto scale + window ROI)
│   ├── ocr.py               # Timer OCR for HQ drone gift
│   └── flows/
│       ├── alliance_gifts.py
│       ├── drone_gift.py
│       ├── trucks.py
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
| [docs/FLOWS.md](docs/FLOWS.md) | Collection step-by-step (Drone + Battlefield + Gifts + Techs + Trucks) |

After a failed run, share **`logs/runs.log`** (and any `logs/debug/flow/crash_*.png`). The watcher also writes `logs/watcher.log`.

## Configuration flags

All of these live in [`config.yaml`](config.yaml). Restart / re-run the menu after edits (`reload` happens each process start).

### Game & paths

| Flag | Default | Purpose |
|------|---------|---------|
| `game.process_name` | `Survival.exe` | Process name used to focus the game window |
| `crossover.bottle_name` | `Last Z` | CrossOver bottle for menu **3** Hebrew fix |
| `paths.templates_dir` | `templates/active` | Template image folder |
| `paths.logs_dir` | `logs` | Run / watcher / debug logs |

### Watcher

| Flag | Default | Purpose |
|------|---------|---------|
| `watcher.alliance_interval_sec` | `180` | Seconds between full collection runs in menu **2** |

### HQ Drone Gift

| Flag | Default | Purpose |
|------|---------|---------|
| `drone_gift.min_duration` | `"08:00:00"` | Collect only when Exploration Duration ≥ this |
| `drone_gift.timer_crop_offset` | `[dx,dy,w,h]` | Timer crop relative to chest match (scaled at runtime) |
| `drone_gift.modal_timer_region` | `[x,y,w,h]` | Idle Reward modal timer region (scaled at runtime) |

### Alliance Techs

| Flag | Default | Purpose |
|------|---------|---------|
| `alliance_techs.max_donates` | `20` | Cap on blue Donate clicks per run |

### Trucks

| Flag | Default | Purpose |
|------|---------|---------|
| `trucks.include_trucks_flow` | `true` | `false` = skip trucks entirely (manual picking) |
| `trucks.allow_purple_trucks` | `false` | `false` = refresh for **orange**; `true` = purple OK too |
| `trucks.max_refreshes` | `15` | Safety cap while refreshing (ticket cost `N/1` is allowed; not paid diamonds) |
| `trucks.open_every_n_runs` | `5` | Also open every Nth gifts run (even without a badge). **Badge always opens immediately.** |

### Vision thresholds

| Flag | Typical | Purpose |
|------|---------|---------|
| `thresholds.claim_all` | `0.82` | Claim All button |
| `thresholds.claim_button` | `0.72` | Individual green Claim |
| `thresholds.orange_icon` | `0.82` | Battlefield wilderness chest |
| `thresholds.alliance_shield` | `0.7` | Alliance HUD shield |
| `thresholds.alliance_gifts` | `0.7` | Alliance Gifts tile |
| `thresholds.rare_tab` | `0.78` | Rare tab |
| `thresholds.alliance_techs` | `0.7` | Techs microscope |
| `thresholds.tech_thumbs_up` | `0.78` | Orange recommended-tech mark |
| `thresholds.tech_hex_active` | `0.65` | Lit tech hex fallback |
| `thresholds.donate_blue` | `0.75` | Blue gold Donate |
| `thresholds.hq_world_button` | `0.7` | Leave HQ → Wilderness |
| `thresholds.wilderness_hq_button` | `0.7` | Enter HQ from Wilderness |
| `thresholds.drone_gift_chest` | `0.58` | HQ drone gift chest |
| `thresholds.drone_claim_btn` | `0.55` | Drone Claim |
| `thresholds.drone_collect_btn` | `0.55` | Drone Collect |
| `thresholds.trucks_icon` | `0.72` | Left-HUD trucks icon |
| `thresholds.trucks_my_truck_tab` | `0.65` | My Truck tab |
| `thresholds.trucks_claim_chest` | `0.70` | Arrived-truck claim chest |
| `thresholds.trucks_slot_plus` | `0.70` | Empty slot green `+` |
| `thresholds.trucks_refresh` | `0.70` | Picker refresh |
| `thresholds.trucks_go` | `0.70` | Picker Go |
| `thresholds.trucks_details_back` | `0.70` | Details modal back |

### Coordinates

| Flag | Default | Purpose |
|------|---------|---------|
| `coordinates.dismiss_outside_frac` | `[0.06, 0.28]` | Outside-click dismiss as fractions of the game window `[fx, fy]` |

### Disable trucks only (keep the rest of the flow)

```yaml
trucks:
  include_trucks_flow: false
```

### Allow purple trucks

```yaml
trucks:
  include_trucks_flow: true
  allow_purple_trucks: true
```

## Disclaimer

This tool automates in-game actions. Using automation may violate the game's Terms of Service. Use at your own risk.
