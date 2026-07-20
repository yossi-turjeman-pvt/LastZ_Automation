"""
Trucks flow — claim arrived trucks and send an orange truck from the upper slot.

Runs at the end of menu 1 / watcher (after Alliance Techs) when
`trucks.include_trucks_flow` is true. Opens when the left-HUD icon has a
red badge, or every `open_every_n_runs` gifts runs in this process
(default 5). Exit via Escape.
"""
from __future__ import annotations

import re
import time
from typing import Literal, NamedTuple

import cv2
import numpy as np

from lastz.config import threshold as cfg_threshold
from lastz.config import trucks_cfg
from lastz.debug_match import debug_dir
from lastz.flows.base import dismiss_overlay, ensure_wilderness
from lastz.input import click, press_escape
from lastz.runlog import log, log_click, log_skip, log_step
from lastz.screen import capture_both, physical_to_logical
from lastz.vision import Match, find_all_templates, find_template

try:
    import pytesseract
except ImportError:
    pytesseract = None  # type: ignore

TruckColor = Literal["orange", "purple", "other", "unknown"]
SlotKind = Literal["empty", "occupied"]


class ColorSample(NamedTuple):
    """Picker color classification + raw pixel counts for runs.log."""

    kind: TruckColor
    orange_px: int
    purple_px: int
    green_px: int


_TRADE_RE = re.compile(r"(\d)\s*/\s*4")
_run_counter = 0  # process-lifetime gifts-run count for open_every_n_runs

# Merge markers within this Y-frac into one track/slot row
_SLOT_Y_MERGE = 0.055
# Highway scan — find ALL tracks here (not a "upper only" lock)
_DEFAULT_HIGHWAY_BAND = [0.10, 0.78, 0.28, 0.72]


def _click_match(m: Match, label: str, template: str) -> None:
    lx, ly = physical_to_logical(m.phys_x, m.phys_y)
    log_click(
        label,
        template=template,
        conf=m.confidence,
        logical_xy=(lx, ly),
        phys_xy=(m.phys_x, m.phys_y),
    )
    click(lx, ly)


def _exit_trucks(*, delay: float = 1.5) -> None:
    print("[Trucks] Escape to close Trucks UI...")
    press_escape()
    time.sleep(delay)


def _bump_run_counter() -> int:
    """Increment in-process gifts-run counter; return new value (1-based)."""
    global _run_counter
    _run_counter += 1
    return _run_counter


def _find_trucks_icon(gray: np.ndarray) -> Match | None:
    thr = cfg_threshold("trucks_icon")
    h, w = gray.shape[:2]
    m = find_template(gray, "trucks_icon.png", thr)
    if m is None:
        m = find_template(gray, "trucks_icon.png", max(0.55, thr - 0.12))
    if m is None:
        return None
    if m.phys_x / w > 0.15:
        print(f"[Trucks] trucks_icon rejected (xf={m.phys_x / w:.2f} not left HUD)")
        return None
    return m


def _icon_has_red_badge(color: np.ndarray, icon: Match) -> bool:
    """True if a red notification badge sits on the trucks icon (top-right)."""
    h, w = color.shape[:2]
    # Badge is near the icon's upper-right; search a pad around the match center
    pad = max(40, int(0.035 * h))
    cx, cy = int(icon.phys_x), int(icon.phys_y)
    x0 = max(0, cx - pad // 2)
    x1 = min(w, cx + pad)
    y0 = max(0, cy - pad)
    y1 = min(h, cy + pad // 2)
    roi = color[y0:y1, x0:x1]
    if roi.size == 0:
        return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, (0, 100, 100), (12, 255, 255))
    m2 = cv2.inRange(hsv, (168, 100, 100), (180, 255, 255))
    red = cv2.bitwise_or(m1, m2)
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(red, 8)
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        if 15 <= a <= 800 and 6 <= bw <= 45 and 6 <= bh <= 45:
            return True
    return False


def _should_open_trucks(color: np.ndarray, gray: np.ndarray) -> tuple[bool, str]:
    """
    Open when left-HUD icon has a red badge, or every Nth gifts run.

    Returns (should_open, reason).
    """
    cfg = trucks_cfg()
    n_every = cfg["open_every_n_runs"]
    run_i = _bump_run_counter()
    cadence_hit = (run_i % n_every) == 0

    icon = _find_trucks_icon(gray)
    has_badge = bool(icon and _icon_has_red_badge(color, icon))

    print(
        f"[Trucks] gate run={run_i} every_n={n_every} "
        f"badge={has_badge} cadence={cadence_hit}"
    )
    if has_badge:
        return True, "badge"
    if cadence_hit:
        return True, f"cadence every_{n_every} (run {run_i})"
    return False, f"no_badge and run {run_i} not multiple of {n_every}"


def _open_trucks() -> bool:
    color, gray = capture_both()
    m = _find_trucks_icon(gray)
    if m is None:
        return False
    _click_match(m, "trucks_icon", "trucks_icon.png")
    time.sleep(2.0)
    return True


def _switch_my_truck() -> bool:
    thr = cfg_threshold("trucks_my_truck_tab")
    color, gray = capture_both()
    h, w = gray.shape[:2]
    m = find_template(gray, "trucks_my_truck_tab.png", thr)
    if m is not None and m.phys_y / h >= 0.80 and m.phys_x / w >= 0.45:
        _click_match(m, "trucks_my_truck_tab", "trucks_my_truck_tab.png")
        time.sleep(1.8)
        return True

    # Fallback: right half of bottom tab bar (Others' is left / My Truck is right)
    print("[Trucks] My Truck tab template miss — clicking right half of bottom bar")
    lx, ly = physical_to_logical(0.72 * w, 0.93 * h)
    log_click("trucks_my_truck_tab_fallback", logical_xy=(lx, ly), phys_xy=(0.72 * w, 0.93 * h))
    click(lx, ly)
    time.sleep(1.8)
    return True


def _claim_arrived() -> int:
    """Claim golden chests on My Truck; return number claimed."""
    thr = cfg_threshold("trucks_claim_chest")
    claimed = 0
    for _ in range(4):
        color, gray = capture_both()
        h, w = gray.shape[:2]
        m = find_template(gray, "trucks_claim_chest.png", thr)
        if m is None:
            break
        if not (0.15 <= m.phys_y / h <= 0.60 and 0.25 <= m.phys_x / w <= 0.75):
            print(
                f"[Trucks] claim_chest rejected "
                f"(xf={m.phys_x / w:.2f} yf={m.phys_y / h:.2f})"
            )
            break
        _click_match(m, "trucks_claim_chest", "trucks_claim_chest.png")
        time.sleep(1.8)
        print("[Trucks] Dismissing claim rewards...")
        dismiss_overlay(delay=1.4)
        # Details page may remain — back arrow or Escape once into My Truck
        color2, gray2 = capture_both()
        back = find_template(gray2, "trucks_details_back.png", cfg_threshold("trucks_details_back"))
        if back is not None and 0.70 <= back.phys_y / gray2.shape[0] <= 0.92:
            _click_match(back, "trucks_details_back", "trucks_details_back.png")
            time.sleep(1.5)
        claimed += 1
    return claimed


def _read_trade_count(color: np.ndarray) -> int | None:
    """Parse Today's Trade Count N/4 from the top-left banner. None if OCR fails."""
    if pytesseract is None:
        return None
    h, w = color.shape[:2]
    crop = color[int(0.02 * h) : int(0.12 * h), int(0.02 * w) : int(0.40 * w)]
    if crop.size == 0:
        return None
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(g, 160, 255, cv2.THRESH_BINARY)
    bw = cv2.resize(bw, (bw.shape[1] * 3, bw.shape[0] * 3), interpolation=cv2.INTER_NEAREST)
    try:
        text = pytesseract.image_to_string(bw, config="--psm 6")
    except Exception as exc:
        print(f"[Trucks] trade OCR error: {exc}")
        return None
    m = _TRADE_RE.search(text.replace(" ", ""))
    if not m:
        m = _TRADE_RE.search(text)
    if not m:
        print(f"[Trucks] trade OCR unmatched: {text!r}")
        return None
    return int(m.group(1))


def _highway_band() -> tuple[float, float, float, float]:
    """Wide band to discover every truck track/slot (yf0, yf1, xf0, xf1)."""
    band = trucks_cfg().get("highway_band") or list(_DEFAULT_HIGHWAY_BAND)
    return float(band[0]), float(band[1]), float(band[2]), float(band[3])


class SlotTrack(NamedTuple):
    """One My-Truck highway row (empty + or occupied truck/chest)."""

    kind: SlotKind
    phys_x: float
    phys_y: float
    confidence: float
    source: str  # plus | chest | truck_blob


def _in_highway(m: Match, h: int, w: int, band: tuple[float, float, float, float]) -> bool:
    yf0, yf1, xf0, xf1 = band
    return yf0 <= m.phys_y / h <= yf1 and xf0 <= m.phys_x / w <= xf1


def _find_empty_pluses(gray: np.ndarray, color: np.ndarray) -> list[SlotTrack]:
    """All green + empty slots on the highway (any row)."""
    thr = cfg_threshold("trucks_slot_plus")
    h, w = gray.shape[:2]
    band = _highway_band()
    yf0, yf1, xf0, xf1 = band
    out: list[SlotTrack] = []
    for m in find_all_templates(gray, "trucks_slot_plus.png", thr):
        if _in_highway(m, h, w, band):
            out.append(
                SlotTrack("empty", m.phys_x, m.phys_y, m.confidence, "plus")
            )
    if out:
        return out

    # HSV fallback for green + across the full highway
    y0, y1 = int(yf0 * h), int(yf1 * h)
    x0, x1 = int(xf0 * w), int(xf1 * w)
    roi = color[y0:y1, x0:x1]
    if roi.size == 0:
        return []
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (40, 100, 100), (90, 255, 255))
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, cents = cv2.connectedComponentsWithStats(green, 8)
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        if not (120 <= a <= 10000 and 15 <= bw <= 120 and 15 <= bh <= 120):
            continue
        cx = float(cents[i][0] + x0)
        cy = float(cents[i][1] + y0)
        out.append(SlotTrack("empty", cx, cy, 0.80, "plus_hsv"))
    return out


def _find_occupied_tracks(gray: np.ndarray, color: np.ndarray) -> list[SlotTrack]:
    """
    Occupied tracks: arrived claim chests + en-route truck-colored blobs.

    Needed so the upper row is still recognized when it has no +.
    """
    h, w = gray.shape[:2]
    band = _highway_band()
    yf0, yf1, xf0, xf1 = band
    out: list[SlotTrack] = []

    chest_thr = cfg_threshold("trucks_claim_chest")
    for m in find_all_templates(gray, "trucks_claim_chest.png", max(0.55, chest_thr - 0.10)):
        if _in_highway(m, h, w, band):
            out.append(
                SlotTrack("occupied", m.phys_x, m.phys_y, m.confidence, "chest")
            )

    # En-route trucks: saturated non-green blobs in the highway column
    y0, y1 = int(yf0 * h), int(yf1 * h)
    x0, x1 = int(xf0 * w), int(xf1 * w)
    roi = color[y0:y1, x0:x1]
    if roi.size == 0:
        return out
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Truck paint (orange / purple / cyan-ish / warm) — exclude pure green +
    warm = cv2.inRange(hsv, (0, 60, 70), (35, 255, 255))
    purple = cv2.inRange(hsv, (115, 50, 50), (170, 255, 255))
    paint = cv2.bitwise_or(warm, purple)
    green_plus = cv2.inRange(hsv, (40, 100, 100), (90, 255, 255))
    paint = cv2.bitwise_and(paint, cv2.bitwise_not(green_plus))
    paint = cv2.morphologyEx(paint, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    paint = cv2.morphologyEx(paint, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, stats, cents = cv2.connectedComponentsWithStats(paint, 8)
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        # Truck-sized, not tiny UI chrome / not huge panels
        if not (800 <= a <= 80000 and 25 <= bw <= 280 and 20 <= bh <= 200):
            continue
        cx = float(cents[i][0] + x0)
        cy = float(cents[i][1] + y0)
        out.append(SlotTrack("occupied", cx, cy, 0.75, "truck_blob"))
    return out


def _cluster_tracks(marks: list[SlotTrack], h: int) -> list[SlotTrack]:
    """Merge nearby Y markers into one track; empty wins over occupied if both."""
    if not marks:
        return []
    ordered = sorted(marks, key=lambda s: s.phys_y)
    clusters: list[list[SlotTrack]] = [[ordered[0]]]
    for m in ordered[1:]:
        prev = clusters[-1][0]
        if abs(m.phys_y - prev.phys_y) / h <= _SLOT_Y_MERGE:
            clusters[-1].append(m)
        else:
            clusters.append([m])

    tracks: list[SlotTrack] = []
    for group in clusters:
        empties = [g for g in group if g.kind == "empty"]
        if empties:
            best = max(empties, key=lambda g: g.confidence)
            tracks.append(best)
        else:
            best = max(group, key=lambda g: g.confidence)
            tracks.append(best)
    return tracks


def _discover_all_tracks(gray: np.ndarray, color: np.ndarray) -> list[SlotTrack]:
    """
    Recognize every highway track/slot on screen (empty + occupied), top→bottom.

    Strategy: see ALL rows, then callers use only the uppermost.
    """
    h = gray.shape[0]
    marks = _find_empty_pluses(gray, color) + _find_occupied_tracks(gray, color)
    tracks = _cluster_tracks(marks, h)
    if not tracks:
        log("[Trucks] track discovery: none found on highway")
        return []
    detail = ", ".join(
        f"#{i + 1}:{t.kind}/{t.source}@yf={t.phys_y / h:.3f}"
        for i, t in enumerate(tracks)
    )
    log(f"[Trucks] track discovery: {len(tracks)} track(s) → {detail}")
    return tracks


def _upper_plus(gray: np.ndarray, color: np.ndarray) -> Match | None:
    """
    One-truck rule: discover all tracks, then use ONLY the uppermost.

    - Uppermost empty → return that +
    - Uppermost occupied (en route / chest) → skip (do not click lower +)
    """
    tracks = _discover_all_tracks(gray, color)
    if not tracks:
        return None

    upper = tracks[0]
    h = gray.shape[0]
    if upper.kind != "empty":
        lower_empty = sum(1 for t in tracks[1:] if t.kind == "empty")
        log(
            f"[Trucks] upper track OCCUPIED "
            f"({upper.source} yf={upper.phys_y / h:.3f}) — "
            f"leave it (ignoring {lower_empty} lower empty +)"
        )
        return None

    if len(tracks) > 1:
        log(
            f"[Trucks] using UPPER track only "
            f"(yf={upper.phys_y / h:.3f}); "
            f"{len(tracks) - 1} lower track(s) ignored"
        )
    else:
        log(f"[Trucks] upper track empty + yf={upper.phys_y / h:.3f}")

    return Match(phys_x=upper.phys_x, phys_y=upper.phys_y, confidence=upper.confidence)


def _is_wanted_color(kind: TruckColor, allow_purple: bool) -> bool:
    return kind == "orange" or (allow_purple and kind == "purple")


def _picker_roi_box(h: int, w: int) -> tuple[int, int, int, int]:
    """Pixel box (y0,y1,x0,x1) used for picker color classification."""
    return (
        int(0.10 * h),
        int(0.36 * h),
        int(0.32 * w),
        int(0.68 * w),
    )


def _sample_picker_color(color: np.ndarray) -> ColorSample:
    """
    Classify truck art on the picker modal as orange / purple / other.

    Conservative on purpose: gray/green trucks with a few gold accents must
    NOT count as orange. Green body pixels veto an orange call.
    """
    h, w = color.shape[:2]
    y0, y1, x0, x1 = _picker_roi_box(h, w)
    roi = color[y0:y1, x0:x1]
    if roi.size == 0:
        return ColorSample("unknown", 0, 0, 0)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Slightly tighter orange (skip pale sand / weak yellow accents)
    orange = cv2.inRange(hsv, (6, 110, 120), (26, 255, 255))
    purple = cv2.inRange(hsv, (120, 70, 70), (170, 255, 255))
    green = cv2.inRange(hsv, (40, 70, 70), (95, 255, 255))
    o_px = int(cv2.countNonZero(orange))
    p_px = int(cv2.countNonZero(purple))
    g_px = int(cv2.countNonZero(green))

    # Green body dominates → gray-green / green truck, never "orange"
    if g_px >= 1500 and g_px >= o_px * 0.75:
        return ColorSample("other", o_px, p_px, g_px)

    min_px = 2500  # was 800 — gold stars alone used to false-trigger
    if o_px < min_px and p_px < min_px:
        return ColorSample("other", o_px, p_px, g_px)
    if o_px >= min_px and o_px >= p_px * 1.3 and o_px >= max(g_px * 2.0, 1):
        return ColorSample("orange", o_px, p_px, g_px)
    if p_px >= min_px and p_px > o_px and p_px >= g_px:
        return ColorSample("purple", o_px, p_px, g_px)
    return ColorSample("other", o_px, p_px, g_px)


def _detect_picker_color(color: np.ndarray) -> TruckColor:
    """Back-compat wrapper — prefer `_sample_picker_color` + `_log_color_round`."""
    return _sample_picker_color(color).kind


def _save_color_verify(
    color: np.ndarray,
    sample: ColorSample,
    *,
    round_i: int,
    phase: str,
) -> str | None:
    """
    Save ROI crop + HSV mask strip so a human can VERIFY the label.

    Returns relative path string for runs.log, or None if disabled/failed.
    """
    if not trucks_cfg().get("save_color_debug", True):
        return None
    try:
        import datetime

        h, w = color.shape[:2]
        y0, y1, x0, x1 = _picker_roi_box(h, w)
        roi = color[y0:y1, x0:x1].copy()
        if roi.size == 0:
            return None

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        o_m = cv2.inRange(hsv, (6, 110, 120), (26, 255, 255))
        p_m = cv2.inRange(hsv, (120, 70, 70), (170, 255, 255))
        g_m = cv2.inRange(hsv, (40, 70, 70), (95, 255, 255))
        # Stack: ROI | orange-mask | purple-mask | green-mask
        o_bgr = cv2.cvtColor(o_m, cv2.COLOR_GRAY2BGR)
        p_bgr = cv2.cvtColor(p_m, cv2.COLOR_GRAY2BGR)
        g_bgr = cv2.cvtColor(g_m, cv2.COLOR_GRAY2BGR)
        # Tint masks for readability
        o_bgr[:, :, 0] = 0
        o_bgr[:, :, 1] = np.minimum(o_bgr[:, :, 1] + 40, 255)
        p_bgr[:, :, 1] = 0
        g_bgr[:, :, 2] = 0
        strip = np.hstack([roi, o_bgr, p_bgr, g_bgr])
        label = (
            f"{sample.kind}  o={sample.orange_px} p={sample.purple_px} "
            f"g={sample.green_px}  [{phase} r{round_i}]"
        )
        cv2.putText(
            strip,
            label,
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        # Annotated full frame (scaled) — confirms ROI is on the truck art
        ann = color.copy()
        cv2.rectangle(ann, (x0, y0), (x1, y1), (0, 255, 255), 3)
        cv2.putText(
            ann,
            f"class={sample.kind}",
            (x0, max(30, y0 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        ann_small = cv2.resize(ann, (ann.shape[1] // 2, ann.shape[0] // 2))

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_dir = debug_dir("trucks", "color")
        base = f"{stamp}_r{round_i}_{phase}_{sample.kind}"
        crop_path = out_dir / f"{base}_verify.png"
        full_path = out_dir / f"{base}_frame.png"
        cv2.imwrite(str(crop_path), strip)
        cv2.imwrite(str(full_path), ann_small)
        return f"logs/debug/trucks/color/{crop_path.name}"
    except Exception as exc:
        log(f"[Trucks] color verify save failed: {exc}")
        return None


def _log_color_round(
    sample: ColorSample,
    color: np.ndarray,
    *,
    round_i: int,
    max_refreshes: int,
    phase: str,
    allow_purple: bool,
    tips: str = "none",
) -> str:
    """
    One runs.log line per color check + verify crop on disk.

    Returns decision: accept | refresh | abort_exhausted
    """
    wanted = _is_wanted_color(sample.kind, allow_purple)
    if wanted:
        decision = "accept"
    elif phase.startswith("exhausted"):
        decision = "abort_exhausted"
    else:
        decision = "refresh"
    verify_path = _save_color_verify(color, sample, round_i=round_i, phase=phase)
    path_bit = f" verify={verify_path}" if verify_path else ""
    log(
        f"[Trucks] color round={round_i}/{max_refreshes} phase={phase} "
        f"result={sample.kind} orange_px={sample.orange_px} "
        f"purple_px={sample.purple_px} green_px={sample.green_px} "
        f"tips={tips} decision={decision}{path_bit}"
    )
    return decision


def _find_go(gray: np.ndarray) -> Match | None:
    """
    Real Go is high-confidence near the bottom center.

    Overnight failures used conf~0.837 at a shifted XY — reject weak matches.
    """
    thr = max(cfg_threshold("trucks_go"), 0.92)
    h, w = gray.shape[:2]
    m = find_template(gray, "trucks_go.png", thr)
    if m is not None and m.phys_y / h >= 0.78 and 0.35 <= m.phys_x / w <= 0.65:
        return m
    if m is not None:
        log(
            f"[Trucks] Go template rejected "
            f"(conf={m.confidence:.3f} yf={m.phys_y / h:.3f} xf={m.phys_x / w:.3f}; "
            f"need conf>={thr:.2f} yf>=0.78)"
        )
    # Wide orange rect fallback — still require bottom band
    color, _ = capture_both()
    y0, y1 = int(0.78 * h), int(0.92 * h)
    x0, x1 = int(0.35 * w), int(0.65 * w)
    roi = color[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 100, 120), (25, 255, 255))
    orange = cv2.morphologyEx(orange, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, stats, cents = cv2.connectedComponentsWithStats(orange, 8)
    best: Match | None = None
    best_a = 0
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        if a < 2000 or bw / max(bh, 1) < 2.0:
            continue
        if a > best_a:
            best_a = a
            best = Match(
                phys_x=float(cents[i][0] + x0),
                phys_y=float(cents[i][1] + y0),
                confidence=0.85,
            )
    return best


def _click_refresh() -> bool:
    thr = cfg_threshold("trucks_refresh")
    color, gray = capture_both()
    h, w = gray.shape[:2]
    m = find_template(gray, "trucks_refresh.png", thr)
    if m is not None and 0.20 <= m.phys_y / h <= 0.60 and m.phys_x / w >= 0.45:
        _click_match(m, "trucks_refresh", "trucks_refresh.png")
        time.sleep(2.0)
        return True
    # Orange circular fallback mid-right of picker
    y0, y1 = int(0.22 * h), int(0.55 * h)
    x0, x1 = int(0.50 * w), int(0.78 * w)
    roi = color[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 120, 120), (25, 255, 255))
    orange = cv2.morphologyEx(orange, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, cents = cv2.connectedComponentsWithStats(orange, 8)
    best = None
    best_score = 0.0
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        if a < 400 or bw < 25 or bh < 25 or a > 25000:
            continue
        circ = min(bw, bh) / max(bw, bh)
        if circ < 0.7:
            continue
        score = circ * min(a, 5000)
        if score > best_score:
            best_score = score
            best = Match(
                phys_x=float(cents[i][0] + x0),
                phys_y=float(cents[i][1] + y0),
                confidence=0.80,
            )
    if best is None:
        return False
    _click_match(best, "trucks_refresh_hsv", "trucks_refresh.png")
    time.sleep(2.0)
    return True


def _handle_tips_modal(allow_purple: bool) -> str:
    """
    After refresh, a Tips modal may ask to keep a purple high-quality truck.

    Returns: 'accepted' | 'dismissed' | 'none'
    """
    color, gray = capture_both()
    h, w = color.shape[:2]
    # Look for Confirm-like wide orange button in mid modal (not Go at bottom)
    y0, y1 = int(0.45 * h), int(0.75 * h)
    x0, x1 = int(0.30 * w), int(0.70 * w)
    roi = color[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 100, 120), (25, 255, 255))
    orange = cv2.morphologyEx(orange, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, _, stats, cents = cv2.connectedComponentsWithStats(orange, 8)
    confirm = None
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        if a < 1500 or bw / max(bh, 1) < 1.8:
            continue
        confirm = Match(
            phys_x=float(cents[i][0] + x0),
            phys_y=float(cents[i][1] + y0),
            confidence=0.80,
        )
        break
    # Also require "Tips" / unusual layout — if Go is still the bottom button and
    # no mid Confirm, treat as no Tips.
    go = find_template(gray, "trucks_go.png", cfg_threshold("trucks_go"))
    if confirm is None:
        return "none"
    if go is not None and abs(confirm.phys_y - go.phys_y) < 40:
        return "none"  # that was Go, not Tips Confirm

    if allow_purple:
        log("[Trucks] Tips modal — Confirm (allow_purple_trucks)")
        _click_match(confirm, "trucks_tips_confirm", "tips_confirm")
        time.sleep(1.5)
        return "accepted"

    log("[Trucks] Tips modal — dismiss (want orange, not purple)")
    dismiss_overlay(delay=1.2)
    return "dismissed"


def _refresh_until_wanted(allow_purple: bool, max_refreshes: int) -> TruckColor:
    """
    Refresh until orange (or purple if allowed). Logs color every round.

    Returns the last classified color — caller MUST refuse Go unless wanted.
    """
    color, _ = capture_both()
    sample = _sample_picker_color(color)
    _log_color_round(
        sample,
        color,
        round_i=0,
        max_refreshes=max_refreshes,
        phase="initial",
        allow_purple=allow_purple,
    )
    if _is_wanted_color(sample.kind, allow_purple):
        return sample.kind

    for i in range(max_refreshes):
        round_i = i + 1
        if not _click_refresh():
            log(
                f"[Trucks] color round={round_i}/{max_refreshes} "
                f"phase=refresh_click_failed decision=stop_no_refresh_btn "
                f"(last_result={sample.kind})"
            )
            break
        tips = _handle_tips_modal(allow_purple)
        color, _ = capture_both()
        sample = _sample_picker_color(color)
        _log_color_round(
            sample,
            color,
            round_i=round_i,
            max_refreshes=max_refreshes,
            phase=f"after_refresh_{round_i}",
            allow_purple=allow_purple,
            tips=tips,
        )
        if tips == "accepted" and allow_purple:
            return "purple" if sample.kind == "unknown" else sample.kind
        if _is_wanted_color(sample.kind, allow_purple):
            return sample.kind

    # Out of refreshes / tickets — DO NOT send junk (caller aborts)
    color, _ = capture_both()
    sample = _sample_picker_color(color)
    _log_color_round(
        sample,
        color,
        round_i=max_refreshes,
        max_refreshes=max_refreshes,
        phase="exhausted",
        allow_purple=allow_purple,
    )
    return sample.kind


def _send_upper_truck(allow_purple: bool, max_refreshes: int) -> str:
    """Send at most one truck, and only from the upper slot."""
    color, gray = capture_both()
    plus = _upper_plus(gray, color)
    if plus is None:
        log_skip("trucks_upper_busy", detail="one truck at a time — lower slots ignored")
        return "skipped: upper slot busy (one truck at a time)"

    _click_match(plus, "trucks_slot_plus_upper", "trucks_slot_plus.png")
    time.sleep(2.0)

    kind = _refresh_until_wanted(allow_purple, max_refreshes)
    if not _is_wanted_color(kind, allow_purple):
        log(f"[Trucks] REFUSING Go — color={kind} (want orange only)")
        _exit_trucks()
        return f"aborted: color={kind} (not orange)"

    # Re-check color right before Go (UI can change; never trust a stale label)
    color_final, gray2 = capture_both()
    sample_final = _sample_picker_color(color_final)
    _log_color_round(
        sample_final,
        color_final,
        round_i=-1,
        max_refreshes=max_refreshes,
        phase="pre_go_recheck",
        allow_purple=allow_purple,
    )
    if not _is_wanted_color(sample_final.kind, allow_purple):
        log(f"[Trucks] REFUSING Go — pre-click recheck color={sample_final.kind}")
        _exit_trucks()
        return f"aborted: recheck color={sample_final.kind} (not orange)"

    log(f"[Trucks] Sending truck color={sample_final.kind}")
    go = _find_go(gray2)
    if go is None:
        _exit_trucks()
        return "failed: Go button not found"
    # Hard floor — never accept the ~0.837 false Go that logged fake sends
    if go.confidence < 0.92:
        log(f"[Trucks] REFUSING Go — weak conf={go.confidence:.3f} (need >=0.92)")
        _exit_trucks()
        return f"aborted: weak Go conf={go.confidence:.3f}"
    _click_match(go, "trucks_go", "trucks_go.png")
    time.sleep(2.2)
    return f"sent:{sample_final.kind}"


def run_trucks_flow() -> str:
    """
    Claim arrived trucks and optionally send one from the upper slot.

    Opens only when the left-HUD icon has a red badge, or every
    `open_every_n_runs` gifts runs. Returns a short status string for logging.
    """
    cfg = trucks_cfg()
    if not cfg["include_trucks_flow"]:
        log_skip("trucks_disabled")
        return "skipped: include_trucks_flow=false"

    allow_purple = cfg["allow_purple_trucks"]
    max_refreshes = cfg["max_refreshes"]
    n_every = cfg["open_every_n_runs"]
    print(
        f"[Trucks] include=true allow_purple={allow_purple} "
        f"max_refreshes={max_refreshes} open_every_n={n_every}"
    )

    ensure_wilderness()

    color, gray = capture_both()
    should_open, gate_reason = _should_open_trucks(color, gray)
    if not should_open:
        log_skip("trucks_gate", detail=gate_reason)
        return f"skipped: {gate_reason}"

    print(f"[Trucks] opening ({gate_reason})")
    if not _open_trucks():
        log_skip("trucks_icon_not_found")
        return "skipped: trucks icon"

    if not _switch_my_truck():
        _exit_trucks()
        return "failed: My Truck tab"

    claimed = _claim_arrived()
    print(f"[Trucks] claimed={claimed}")

    color, gray = capture_both()
    trade_n = _read_trade_count(color)
    print(f"[Trucks] trade count={trade_n}/4" if trade_n is not None else "[Trucks] trade count=OCR miss")

    if trade_n is not None and trade_n >= 4:
        _exit_trucks()
        return f"claimed={claimed}; day full 4/4"

    send_status = _send_upper_truck(allow_purple, max_refreshes)
    _exit_trucks()
    return f"claimed={claimed}; {send_status}"
