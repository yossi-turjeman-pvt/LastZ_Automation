"""
Flow 5 — HQ Resource Collection (Farmhouses, Lumberyards, Smelting Plants, Residences).

Collects the resources that accumulate in the four production building types.
Each building type produces a floating circular badge icon above the building
once it starts filling; clicking any one icon for a given resource type instantly
collects all production for that type.

Collection is gated behind two full sweeps with unanimous consensus so slow-
filling buildings are not triggered early.

Steps
-----
  0. Ensure game is running; focus window
  1. Navigate to HQ if in wilderness mode
  2. Reset UI — dismiss any open panels
  3. Recenter the HQ map (reverse swipes to return to default camera position)
  4. Full pan sweep: for each pan position
     a. Capture (both color + gray on the same frame)
     b. find_all_templates() × 4 resource types, with HUD exclusion mask
     c. Accumulate matches across pan positions
  5. Cluster all matches per type (deduplicate cross-pan overlaps)
  6. OCR the count badge below each icon cluster center
  7. Within-scan aggregation: unanimous consensus check per type
  8. Compare against stored state (pass 1 vs pass 2)
  9. For types that pass two-scan gating: click best-confidence icon (instant collect)
  10. Re-scan to verify icons cleared; reset state for collected types
  11. Restore wilderness if started there

Returns a human-readable status string (used by watcher for logging):
  "Collected: food, gold"
  "Pass 1 stored: wood=1.2K (5 icons)"
  "Still filling: energy"
  "OCR incomplete: gold — skipping"
  "No icons visible"
"""
import json
import os
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

from lastz.config import load_config, logs_dir, threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.flows.hq_nav import is_hq_mode, navigate_to_hq, run_in_hq
from lastz.input import click, drag, ensure_game_running, focus_game
from lastz.ocr import read_resource_count_from_region
from lastz.screen import capture_both, physical_to_logical, scale_ref_logical_delta, window_click
from lastz.vision import MatchWithBBox, cluster_matches, find_all_templates

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

RESOURCE_TYPES = ("food", "wood", "energy", "gold", "exp")

_TEMPLATE_MAP = {
    "food":   "hq_resource_food.png",
    "wood":   "hq_resource_wood.png",
    "energy": "hq_resource_energy.png",
    "gold":   "hq_resource_gold.png",
    "exp":    "hq_resource_exp.png",
}


def _cfg() -> dict:
    return load_config().get("hq_resources", {})


def _watcher_cfg() -> dict:
    return load_config().get("watcher", {})


def _state_file() -> Path:
    p = logs_dir() / _cfg().get("state_file", "hq_resources_state.json").split("/")[-1]
    return p


def _min_icons() -> int:
    return int(_cfg().get("min_icons_per_type", 2))


def _dedupe_radius() -> float:
    return float(_cfg().get("dedupe_radius_px", 80))


def _pan_swipes() -> list[list[float]]:
    raw = _cfg().get("pan_swipes", [[0, -200], [200, 0], [0, 200], [-200, 0]])
    scaled = []
    for dx, dy in raw:
        sdx, sdy = scale_ref_logical_delta(float(dx), float(dy))
        scaled.append([sdx, sdy])
    return scaled


def _pan_origin() -> tuple[float, float]:
    o = _cfg().get("map_drag_origin", [0.500, 0.458])
    return window_click(float(o[0]), float(o[1]))


def _pan_settle() -> float:
    return float(_cfg().get("pan_settle_sec", 1.0))


def _hud_exclude_regions(screen_h: int, screen_w: int) -> list[tuple[int, int, int, int]]:
    """Return list of (x1, y1, x2, y2) physical-pixel HUD exclusion rectangles."""
    exc = _cfg().get("hud_exclude", {})
    top_frac    = float(exc.get("top_frac",    0.08))
    bottom_frac = float(exc.get("bottom_frac", 0.12))
    left_frac   = float(exc.get("left_frac",   0.02))
    right_frac  = float(exc.get("right_frac",  0.07))
    return [
        (0,         0,         screen_w, int(screen_h * top_frac)),
        (0,         int(screen_h * (1 - bottom_frac)), screen_w, screen_h),
        (0,         0,         int(screen_w * left_frac),  screen_h),
        (int(screen_w * (1 - right_frac)), 0, screen_w, screen_h),
    ]


def _count_crop_offset(res_type: str) -> list[int]:
    offsets = _cfg().get("count_crop_offset", {})
    return offsets.get(res_type, [-45, 22, 90, 30])


def _confirm_interval() -> float:
    return float(_watcher_cfg().get("hq_resources_confirm_sec", 180))


# ---------------------------------------------------------------------------
# State file — persists two-pass observations across watcher cycles
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = 1


class TypeState(NamedTuple):
    consensus_count: int
    consensus_raw: str
    scan_id: int
    icons_seen: int
    all_visible_agreed: bool
    pan_positions_completed: int
    ts: float
    last_collect_at: float | None


def _load_state() -> dict:
    path = _state_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        if raw.get("schema_version") != _SCHEMA_VERSION:
            return {}
        return raw.get("types", {})
    except Exception as e:
        print(f"[hq_resources] State file corrupt, resetting: {e}")
        return {}


def _save_state(types: dict, last_full_sweep_at: float) -> None:
    """Atomically write state JSON."""
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": _SCHEMA_VERSION,
        "last_full_sweep_at": last_full_sweep_at,
        "types": types,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _clear_type_state(types: dict, res_type: str) -> None:
    types.pop(res_type, None)


# ---------------------------------------------------------------------------
# Pan + scan
# ---------------------------------------------------------------------------

class IconObservation(NamedTuple):
    """One template match OCR'd on the same frame where it was detected."""
    match: MatchWithBBox
    count: int | None
    raw: str
    pan_step: int


def _find_all_for_type(
    gray,
    res_type: str,
    exclude_regions: list[tuple[int, int, int, int]],
    *,
    max_matches: int = 6,
) -> list[MatchWithBBox]:
    """Find icons for a resource type, stepping down threshold if needed."""
    tname = _TEMPLATE_MAP[res_type]
    primary = cfg_threshold(f"hq_resource_{res_type}")
    floor = max(0.62, primary - 0.12)
    for thresh in (primary, max(floor, primary - 0.06), floor):
        found = find_all_templates(gray, tname, thresh, exclude_regions=exclude_regions)
        if found:
            found.sort(key=lambda m: m.confidence, reverse=True)
            return found[:max_matches]
    return []


def _ocr_at_match(color, match: MatchWithBBox, res_type: str) -> tuple[int | None, str]:
    """OCR the count label below an icon on the frame where it was detected."""
    rx = max(0, int(match.phys_x - match.phys_w / 2) - 8)
    ry = max(0, int(match.phys_y - match.phys_h / 2))
    rw = match.phys_w + 16
    rh = match.phys_h
    # Count text sits below the circular badge — OCR the lower portion only.
    label_y = ry + int(rh * 0.58)
    label_h = max(30, rh - int(rh * 0.58) + 18)
    sh, sw = color.shape[:2]
    label_h = min(label_h, sh - label_y)
    rw = min(rw, sw - rx)
    if label_h <= 0 or rw <= 0:
        return None, ""
    return read_resource_count_from_region(color, rx, label_y, rw, label_h)


def _plausible_count(value: int | None, raw: str) -> bool:
    """Reject obvious OCR garbage before it poisons the consensus logic."""
    if value is None or value <= 0:
        return False
    if value > 50_000_000:
        return False
    raw_u = raw.upper().strip()
    if any(s in raw_u for s in ("K", "M", "B")):
        return True
    # Plain integers without suffix — only accept typical badge range.
    return 100 <= value <= 500_000


def _recenter_map() -> None:
    """Execute the reverse pan sequence to return the camera to its default position."""
    swipes = _pan_swipes()
    ox, oy = _pan_origin()
    settle = _pan_settle()
    reverse = list(reversed(swipes))
    for dx, dy in reverse:
        # Drag in the OPPOSITE direction to undo the original swipe
        drag(ox, oy, ox - dx, oy - dy)
        time.sleep(settle)


def _full_pan_sweep(pan_grid: list[list[int]]) -> dict[str, list[IconObservation]]:
    """
    Pan across the HQ map; OCR each icon on the same frame it was detected.

    Match coordinates are only valid on the frame where they were captured.
    OCR must happen inline — not after recentering the map.
    """
    ox, oy = _pan_origin()
    settle = _pan_settle()
    positions: list[tuple[float, float]] = [(ox, oy)]
    cx, cy = ox, oy
    for dx, dy in pan_grid:
        cx += dx
        cy += dy
        positions.append((cx, cy))

    observations: dict[str, list[IconObservation]] = {t: [] for t in RESOURCE_TYPES}

    for step_i, (tx, ty) in enumerate(positions):
        if step_i > 0:
            prev = positions[step_i - 1]
            drag(prev[0], prev[1], tx, ty)
            time.sleep(settle)

        color, gray = capture_both()
        sh, sw = gray.shape
        excl = _hud_exclude_regions(sh, sw)

        for res_type in RESOURCE_TYPES:
            found = _find_all_for_type(gray, res_type, excl)
            for m in found:
                count, raw = _ocr_at_match(color, m, res_type)
                observations[res_type].append(
                    IconObservation(match=m, count=count, raw=raw, pan_step=step_i)
                )
            if found:
                print(f"  [pan {step_i}] {res_type}: {len(found)} icon(s) found")

    for res_type, obs in observations.items():
        if obs:
            print(f"  [{res_type}] {len(obs)} observation(s) across pan sweep")

    return observations


# ---------------------------------------------------------------------------
# Per-type OCR and within-scan consensus
# ---------------------------------------------------------------------------

class ScanResult(NamedTuple):
    status: str        # "consensus" | "icon_ready" | "still_filling" | "ocr_incomplete" | "no_icons"
    count: int | None  # parsed integer (None if not "consensus")
    raw: str           # best raw OCR text
    icons_seen: int
    best_match: MatchWithBBox | None
    max_conf: float = 0.0


def _scan_from_observations(observations: list[IconObservation]) -> ScanResult:
    """Aggregate inline OCR observations into a per-type scan result."""
    if not observations:
        return ScanResult("no_icons", None, "", 0, None, 0.0)

    radius = _dedupe_radius()
    matches = [o.match for o in observations]
    clustered_matches = cluster_matches(matches, radius_px=radius)
    icons_seen = len(clustered_matches)
    best_match = max(clustered_matches, key=lambda m: m.confidence)
    max_conf = best_match.confidence

    plausible: list[tuple[int, str, MatchWithBBox]] = []
    raw_texts: list[str] = []

    for cm in clustered_matches:
        nearby = [
            o for o in observations
            if ((o.match.phys_x - cm.phys_x) ** 2 + (o.match.phys_y - cm.phys_y) ** 2) ** 0.5
            <= radius
        ]
        valid = [o for o in nearby if _plausible_count(o.count, o.raw)]
        if valid:
            best_o = max(valid, key=lambda o: o.match.confidence)
            plausible.append((best_o.count, best_o.raw, best_o.match))
            raw_texts.append(best_o.raw)
        else:
            nearest = min(
                nearby,
                key=lambda o: (o.match.phys_x - cm.phys_x) ** 2 + (o.match.phys_y - cm.phys_y) ** 2,
            )
            if nearest.raw:
                raw_texts.append(nearest.raw)

    if not plausible:
        if max_conf >= 0.62:
            return ScanResult(
                "icon_ready",
                None,
                " / ".join(raw_texts) if raw_texts else "",
                icons_seen,
                best_match,
                max_conf,
            )
        return ScanResult(
            "ocr_incomplete",
            None,
            " / ".join(raw_texts) if raw_texts else "",
            icons_seen,
            best_match,
            max_conf,
        )

    counts = [p[0] for p in plausible]
    from collections import Counter
    mode_count, freq = Counter(counts).most_common(1)[0]

    if len(set(counts)) > 1 and freq < max(2, len(counts) // 2):
        return ScanResult(
            "still_filling",
            None,
            " / ".join(str(c) for c in counts),
            icons_seen,
            best_match,
            max_conf,
        )

    mode_raw = next(raw for c, raw, _ in plausible if c == mode_count)
    return ScanResult("consensus", mode_count, mode_raw, icons_seen, best_match, max_conf)


def _find_live_icon(res_type: str) -> MatchWithBBox | None:
    """Re-detect an icon on the current screen (after map recenter) for clicking."""
    color, gray = capture_both()
    sh, sw = gray.shape
    excl = _hud_exclude_regions(sh, sw)
    found = _find_all_for_type(gray, res_type, excl)
    if not found:
        return None
    return max(found, key=lambda m: m.confidence)


def _find_icon_for_click(res_type: str) -> MatchWithBBox | None:
    """Find a clickable icon at the default camera view, panning if needed."""
    live = _find_live_icon(res_type)
    if live is not None:
        return live

    print(f"  [{res_type}] not at origin — pan-searching...")
    ox, oy = _pan_origin()
    settle = _pan_settle()
    positions: list[tuple[float, float]] = [(ox, oy)]
    cx, cy = ox, oy
    for dx, dy in _pan_swipes():
        cx += dx
        cy += dy
        positions.append((cx, cy))

    for step_i, (tx, ty) in enumerate(positions):
        if step_i > 0:
            prev = positions[step_i - 1]
            drag(prev[0], prev[1], tx, ty)
            time.sleep(settle)
        color, gray = capture_both()
        sh, sw = gray.shape
        excl = _hud_exclude_regions(sh, sw)
        found = _find_all_for_type(gray, res_type, excl)
        if found:
            best = max(found, key=lambda m: m.confidence)
            print(f"  [{res_type}] found at pan step {step_i} conf={best.confidence:.3f}")
            return best

    print(f"  [{res_type}] pan-search exhausted — recentering map")
    _recenter_map()
    time.sleep(0.5)
    return None


def _ocr_scan_result(
    color: "np.ndarray",  # type: ignore[name-defined]
    matches: list[MatchWithBBox],
    res_type: str,
) -> ScanResult:
    """Legacy helper — OCR matches on a provided frame (used by verify)."""
    if not matches:
        return ScanResult("no_icons", None, "", 0, None)

    observations = []
    for m in matches:
        count, raw = _ocr_at_match(color, m, res_type)
        observations.append(IconObservation(match=m, count=count, raw=raw, pan_step=0))
    return _scan_from_observations(observations)

def _passes_gating(current: ScanResult, stored: dict | None, scan_id: int, pan_steps: int) -> bool:
    """
    Return True only if this type is ready to collect.

    Two paths:
      A) OCR consensus — same parsed count on both passes.
      B) Icon presence — high-confidence icons visible on both passes (OCR optional).
    """
    if stored is None:
        return False
    if stored.get("pan_positions_completed", 0) < pan_steps:
        return False
    min_icons = _min_icons()
    if current.icons_seen < min_icons or stored.get("icons_seen", 0) < min_icons:
        return False

    # Path A — OCR count agreement
    if current.status == "consensus" and current.count is not None:
        if not stored.get("all_visible_agreed"):
            return False
        if stored.get("consensus_count") != current.count:
            return False
        if current.count > stored.get("consensus_count", 0):
            return False
        return True

    # Path B — stable icon presence when OCR is unreliable
    if current.status in ("consensus", "icon_ready") and current.best_match is not None:
        if current.max_conf < 0.62 or stored.get("max_conf", 0) < 0.62:
            return False
        # If OCR worked on pass 1 with consensus, require same count on pass 2
        if stored.get("consensus_count") is not None and current.status == "consensus":
            if stored.get("consensus_count") != current.count:
                return False
        # Icon count should be in same ballpark (pan overlap varies)
        prev_icons = stored.get("icons_seen", 0)
        if prev_icons > 0:
            ratio = current.icons_seen / prev_icons
            if ratio < 0.4 or ratio > 2.5:
                return False
        return True

    return False


# ---------------------------------------------------------------------------
# Post-collect verification
# ---------------------------------------------------------------------------

def _verify_collected(res_type: str, icons_before: int) -> bool:
    """
    After clicking, re-scan to confirm icons have cleared or count dropped.
    One click collects all production for a type — accept success liberally.
    """
    time.sleep(1.5)
    color, gray = capture_both()
    sh, sw = gray.shape
    excl = _hud_exclude_regions(sh, sw)
    matches = _find_all_for_type(gray, res_type, excl)
    if not matches:
        print(f"  [{res_type}] post-collect verify: icons gone ✓")
        return True

    if len(matches) < icons_before:
        print(f"  [{res_type}] post-collect verify: {len(matches)} icon(s) (was {icons_before}) ✓")
        return True

    m = max(matches, key=lambda m: m.confidence)
    count, _ = _ocr_at_match(color, m, res_type)
    print(f"  [{res_type}] post-collect verify: {len(matches)} icon(s) visible, count={count} — assuming collected")
    return True


# ---------------------------------------------------------------------------
# Main flow entry point
# ---------------------------------------------------------------------------

def run_hq_resources_flow(*, dry_run: bool = False) -> str:
    ensure_game_running()
    focus_game()

    # Step 1 — determine current mode
    color, gray = capture_both()
    started_in_wilderness = not is_hq_mode(gray)

    if started_in_wilderness:
        print("-> Not in HQ mode — navigating to Headquarters...")
        if not navigate_to_hq(gray):
            return "Not in HQ mode — Headquarters button not found"
        color, gray = capture_both()
        if not is_hq_mode(gray):
            return "Navigation failed — still not in HQ mode"
        print("-> Now in HQ mode.")

    with run_in_hq(restore_wilderness=started_in_wilderness):
        return _collect_resources(dry_run=dry_run)


def _type_state(
    sr: ScanResult,
    pan_steps: int,
    now: float,
    stored: dict | None,
    *,
    consensus_count: int | None,
    all_visible_agreed: bool,
) -> dict:
    return {
        "consensus_count": consensus_count,
        "consensus_raw": sr.raw,
        "scan_id": id(sr),
        "icons_seen": sr.icons_seen,
        "all_visible_agreed": all_visible_agreed,
        "pan_positions_completed": pan_steps,
        "max_conf": sr.max_conf,
        "ts": now,
        "last_collect_at": stored.get("last_collect_at") if stored else None,
    }


def _collect_resources(*, dry_run: bool) -> str:
    # Step 2 — reset UI
    reset_ui(clicks=2, delay=1.0)

    # Step 3 — recenter map
    print("-> Recentering HQ map...")
    _recenter_map()
    time.sleep(0.5)

    # Step 4+5 — pan sweep with inline OCR
    pan_grid = _pan_swipes()
    print(f"-> Starting pan sweep ({len(pan_grid)+1} positions)...")
    observations = _full_pan_sweep(pan_grid)
    pan_steps = len(pan_grid) + 1

    # Return map to origin before clicking
    print("-> Recentering HQ map before collect...")
    _recenter_map()
    time.sleep(0.5)

    # Step 6+7 — aggregate OCR observations per type
    scan_results: dict[str, ScanResult] = {}
    for res_type in RESOURCE_TYPES:
        sr = _scan_from_observations(observations[res_type])
        scan_results[res_type] = sr
        print(f"  [{res_type}] scan: status={sr.status} count={sr.count} "
              f"icons={sr.icons_seen} raw={repr(sr.raw)}")

    # Step 8 — load state, evaluate gating, decide
    stored_state = _load_state()
    now = time.time()
    confirm_interval = _confirm_interval()

    types_to_collect: list[str] = []
    status_parts: list[str] = []
    new_state: dict = {}

    for res_type in RESOURCE_TYPES:
        sr = scan_results[res_type]
        stored = stored_state.get(res_type)

        if sr.status == "no_icons":
            # No visible icons — keep stored state unchanged; do not collect
            if stored:
                new_state[res_type] = stored
            continue

        if sr.status == "ocr_incomplete":
            status_parts.append(f"OCR incomplete: {res_type}")
            if stored:
                new_state[res_type] = stored
            continue

        if sr.status == "still_filling":
            status_parts.append(f"still filling: {res_type}={sr.raw}")
            new_state[res_type] = _type_state(
                sr, pan_steps, now, stored,
                consensus_count=None, all_visible_agreed=False,
            )
            continue

        # status == "consensus" or "icon_ready"
        elapsed = now - (stored.get("ts", 0) if stored else 0)
        ready = _passes_gating(sr, stored, id(sr), pan_steps) and elapsed >= confirm_interval

        label = sr.raw or f"{sr.icons_seen} icons"
        if sr.status == "icon_ready":
            label = f"icons({sr.icons_seen}@{sr.max_conf:.2f})"

        if ready:
            types_to_collect.append(res_type)
            status_parts.append(f"{res_type}={label}")
        else:
            reason = ""
            if not stored:
                reason = "pass 1 stored"
            elif (
                sr.status == "consensus"
                and stored.get("consensus_count") is not None
                and sr.count is not None
                and stored.get("consensus_count") != sr.count
            ):
                reason = f"count changed ({stored.get('consensus_count')} → {sr.count})"
            elif elapsed < confirm_interval:
                remaining = int(confirm_interval - elapsed)
                reason = f"confirm in ~{remaining}s"
            else:
                reason = "not ready"
            status_parts.append(f"{reason}: {res_type}={label}")

        new_state[res_type] = _type_state(
            sr, pan_steps, now, stored,
            consensus_count=sr.count if sr.status == "consensus" else None,
            all_visible_agreed=sr.status == "consensus",
        )

    # Step 9 — click ready types (pan-search if not visible at origin)
    collected: list[str] = []
    for res_type in types_to_collect:
        sr = scan_results[res_type]
        icons_before = sr.icons_seen
        live = _find_icon_for_click(res_type)
        if live is None:
            print(f"  [{res_type}] icon not found for click — skipping")
            status_parts.append(f"not visible: {res_type}")
            continue

        lx, ly = physical_to_logical(live.phys_x, live.phys_y)
        if dry_run:
            print(f"  [{res_type}] DRY RUN — would click at logical ({lx:.0f}, {ly:.0f})")
            collected.append(f"{res_type}(dry)")
            continue

        print(f"  [{res_type}] Clicking icon at logical ({lx:.0f}, {ly:.0f}) "
              f"[conf={live.confidence:.3f}]...")
        click(lx, ly)
        time.sleep(1.5)

        # Step 10 — verify + reset state
        verified = _verify_collected(res_type, icons_before)
        if verified:
            _clear_type_state(new_state, res_type)
            new_state[res_type] = {
                "consensus_count": None,
                "consensus_raw": "",
                "scan_id": 0,
                "icons_seen": 0,
                "all_visible_agreed": False,
                "pan_positions_completed": 0,
                "ts": now,
                "last_collect_at": now,
            }
            collected.append(res_type)
        else:
            print(f"  [{res_type}] collect not verified — state NOT cleared")
            status_parts.append(f"unverified: {res_type}")

    # Save updated state
    _save_state(new_state, now)

    # Build return status
    if collected:
        dry_tag = " (dry run)" if dry_run else ""
        return f"Collected: {', '.join(collected)}{dry_tag}"
    if not status_parts:
        return "No icons visible"
    return " | ".join(status_parts)
