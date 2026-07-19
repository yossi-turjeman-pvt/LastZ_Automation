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
from typing import Literal

import cv2
import numpy as np

from lastz.config import threshold as cfg_threshold
from lastz.config import trucks_cfg
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

_TRADE_RE = re.compile(r"(\d)\s*/\s*4")
_run_counter = 0  # process-lifetime gifts-run count for open_every_n_runs


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


def _upper_plus(gray: np.ndarray, color: np.ndarray) -> Match | None:
    """Uppermost empty-slot green + on My Truck highway."""
    thr = cfg_threshold("trucks_slot_plus")
    h, w = gray.shape[:2]
    matches = find_all_templates(gray, "trucks_slot_plus.png", thr)
    in_band = [
        m
        for m in matches
        if 0.12 <= m.phys_y / h <= 0.72 and 0.28 <= m.phys_x / w <= 0.72
    ]
    if not in_band:
        # HSV fallback for green +
        y0, y1 = int(0.12 * h), int(0.72 * h)
        x0, x1 = int(0.28 * w), int(0.72 * w)
        roi = color[y0:y1, x0:x1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(hsv, (40, 100, 100), (90, 255, 255))
        green = cv2.morphologyEx(green, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, stats, cents = cv2.connectedComponentsWithStats(green, 8)
        blobs: list[Match] = []
        for i in range(1, n):
            a = int(stats[i, cv2.CC_STAT_AREA])
            bw = int(stats[i, cv2.CC_STAT_WIDTH])
            bh = int(stats[i, cv2.CC_STAT_HEIGHT])
            if not (120 <= a <= 10000 and 15 <= bw <= 120 and 15 <= bh <= 120):
                continue
            cx = float(cents[i][0] + x0)
            cy = float(cents[i][1] + y0)
            blobs.append(Match(phys_x=cx, phys_y=cy, confidence=0.80))
        in_band = blobs
    if not in_band:
        return None
    in_band.sort(key=lambda m: m.phys_y)
    return in_band[0]


def _detect_picker_color(color: np.ndarray) -> TruckColor:
    """Classify truck art on the picker modal as orange / purple / other."""
    h, w = color.shape[:2]
    roi = color[int(0.08 * h) : int(0.38 * h), int(0.28 * w) : int(0.72 * w)]
    if roi.size == 0:
        return "unknown"
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 80, 100), (28, 255, 255))
    purple = cv2.inRange(hsv, (120, 60, 60), (170, 255, 255))
    o_px = int(cv2.countNonZero(orange))
    p_px = int(cv2.countNonZero(purple))
    print(f"[Trucks] picker color pixels orange={o_px} purple={p_px}")
    if o_px < 800 and p_px < 800:
        return "other"
    if o_px >= p_px * 1.15 and o_px >= 800:
        return "orange"
    if p_px > o_px and p_px >= 800:
        return "purple"
    return "other"


def _find_go(gray: np.ndarray) -> Match | None:
    thr = cfg_threshold("trucks_go")
    h, w = gray.shape[:2]
    m = find_template(gray, "trucks_go.png", thr)
    if m is not None and m.phys_y / h >= 0.65:
        return m
    # Wide orange rect fallback
    color, _ = capture_both()
    y0, y1 = int(0.68 * h), int(0.90 * h)
    x0, x1 = int(0.30 * w), int(0.70 * w)
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
        print("[Trucks] Tips modal — Confirm (allow_purple_trucks)")
        _click_match(confirm, "trucks_tips_confirm", "tips_confirm")
        time.sleep(1.5)
        return "accepted"

    print("[Trucks] Tips modal — dismiss (want orange, not purple)")
    dismiss_overlay(delay=1.2)
    return "dismissed"


def _refresh_until_wanted(allow_purple: bool, max_refreshes: int) -> TruckColor:
    color, _ = capture_both()
    kind = _detect_picker_color(color)
    if kind == "orange" or (allow_purple and kind == "purple"):
        return kind

    for i in range(max_refreshes):
        print(f"[Trucks] Refresh {i + 1}/{max_refreshes} (have {kind}, want orange)")
        if not _click_refresh():
            print("[Trucks] Refresh button not found — stopping refresh loop")
            break
        tips = _handle_tips_modal(allow_purple)
        color, _ = capture_both()
        kind = _detect_picker_color(color)
        if tips == "accepted" and allow_purple:
            return "purple" if kind == "unknown" else kind
        if kind == "orange":
            return "orange"
        if allow_purple and kind == "purple":
            return "purple"

    # Out of refreshes / tickets — send whatever is shown (better low than nothing)
    color, _ = capture_both()
    return _detect_picker_color(color)


def _send_upper_truck(allow_purple: bool, max_refreshes: int) -> str:
    color, gray = capture_both()
    plus = _upper_plus(gray, color)
    if plus is None:
        return "skipped: upper slot busy (en route or occupied)"

    _click_match(plus, "trucks_slot_plus_upper", "trucks_slot_plus.png")
    time.sleep(2.0)

    kind = _refresh_until_wanted(allow_purple, max_refreshes)
    print(f"[Trucks] Sending truck color={kind}")

    _, gray2 = capture_both()
    go = _find_go(gray2)
    if go is None:
        _exit_trucks()
        return "failed: Go button not found"
    _click_match(go, "trucks_go", "trucks_go.png")
    time.sleep(2.2)
    return f"sent:{kind}"


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
