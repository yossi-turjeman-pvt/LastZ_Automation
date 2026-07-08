# Scouting Flow — Authoritative Spec (v1)

## Goal
Continuous wilderness scouting loop: find **enemy player HQs**, filter by level/power/alliance, dispatch up to **3 scout drones**, record targets in registry.

## Map zoom level
**Strategic zoom** — player HQs appear as small **house icons** (blue/grey/green/purple) with a **white level number** directly underneath.

### Valid target (player HQ)
- House-shaped icon above white level digit
- Click opens modal with: **Power**, **Alliance**, **Scout / Team Up / Attack** buttons
- Alliance tag in modal must NOT be `VLNZ` or blacklist

### Invalid (never scout)
| Object | Visual | Popup if clicked |
|--------|--------|------------------|
| Z creep | Circle with **Z**, black level badge | N/A |
| Resource node | Food/wood/electricity/**crate** icon, level below | Gather/march |
| Empty tile | No house icon | **Teleport / March** only |
| Alliance boss | Large unit + timer | Boss/reinforce UI |
| Own alliance city | `[VLNZ]` cluster at home | Own/allied content |

## Navigation loop
1. Ensure wilderness mode
2. `depart_home_city()` — zoom out to house-icon level (`ensure_house_zoom`)
3. For each sector: large pan → 6 small scan pans
4. After each scout attempt: `ensure_house_zoom()` to restore strategic view

## Target discovery (ordered)
1. **Find house icons** via template match (`house_*.png`) — NOT bare white-digit scan
2. Sort by distance to map center (prefer closer)
3. Pre-filter: level OCR ≤ `max_hq_level` when readable

## Per-target pipeline (strict gate)
```
FOR each candidate (closest first):
  IF registry has target: SKIP
  CLICK house icon
  WAIT settle
  GATE 1: scout_action_btn template visible OR OCR "Scout" in action row
  IF FAIL: dismiss, next candidate (do NOT count as scouted)
  GATE 2: modal OCR — alliance not own/blacklist, power ≤ max_power
  IF FAIL: dismiss, next candidate
  IF dry_run: log "would scout", dismiss, STOP after 1 success
  ELSE: click Scout, mark registry, continue until idle drones filled
```

## Drone slots
- Max parallel: 3
- If `drone_slot_busy` matches > 6 on screen → template unusable, assume 3 idle
- Else count busy in **right sidebar ROI only** (x > 82% width)

## Dry run definition
Full navigation + click + modal gates 1–2 pass. **Does not** click Scout. Stops after first verified enemy HQ.

## Success criteria
- Live run dispatches ≥1 scout to non-blacklisted enemy
- Registry entry written with alliance + power
- No more than 3 dismissals per candidate before panning to new sector
