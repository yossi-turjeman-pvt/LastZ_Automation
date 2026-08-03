"""
OpenCV template matching with full-dynamic scale and game-window ROI.

Scale is discovered every run from on-screen anchors (no per-machine calibration).
Matching is restricted to the game window region so desktop chrome cannot win.
"""
import json
import threading
import time
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

from lastz.config import logs_dir, templates_dir

REF_PIXEL_RATIO = 3024 / 1512  # templates captured on built-in Retina laptop

_SCALE_LO = 0.35
_SCALE_HI = 1.25
_SCALE_STEP = 0.025
_ACCEPT_CONF = 0.70
# A single-anchor match at/above this confidence is trusted outright, no
# sanity-check against history needed — this is what real UI anchors score
# (historically ~0.94-0.97 on a clean wilderness/base screen).
_STRONG_CONF = 0.90
_LOCAL_DELTA = 0.20
_LOCAL_STEP = 0.025
# How close a *weak* (0.70-0.90 conf) reading must be to the last known-good
# scale to be trusted; otherwise it's likely a false peak on an occluded/
# modal screen and we fall back to last-good instead.
_WEAK_AGREE_DELTA = 0.05
# Cached scale is re-probed (single scale, all anchors) before being trusted
# on a live frame; below this confidence the cache is treated as poisoned.
_CACHE_REVALIDATE_CONF = 0.55
_LAST_GOOD_TTL_SEC = 7 * 24 * 60 * 60

# Multi-anchor set for always-on scale discovery
_CALIBRATION_ANCHORS = (
    "wilderness_hq_button.png",
    "hq_world_button.png",
    "alliance_shield_clean.png",
    "orange_icon_no_badge.png",
)


class Match(NamedTuple):
    phys_x: float
    phys_y: float
    confidence: float


class MatchWithBBox(NamedTuple):
    phys_x: float
    phys_y: float
    phys_w: int
    phys_h: int
    confidence: float


# Thread-local — the heli-BR-monitor background thread (watcher.py starts it
# via helicopter.start_heli_monitor(), see lastz/flows/helicopter.py) calls
# ensure_template_scale()/find_template() on its own WINDOW-shaped captures
# concurrently with the main flow thread's DISPLAY-shaped captures. These
# used to be plain module globals shared by both threads: one thread's
# calibration for its own capture shape would stomp the other's
# _calibrated_for/_scale_center mid-flow (same bug class fixed for
# lastz/screen.py's capture state — see that module's docstring). Concretely
# this could make find_template()/find_all_templates() build their scale
# search band around the WRONG resolution's scale center right after the
# background thread calibrates in between _ensure_scale_calibrated() and
# template_scales() in the main thread — a plausible cause of intermittent,
# hard-to-reproduce match misses (e.g. HQ navigation failing only when run
# inside the watcher, never standalone). _scale_center default of 1.0 below
# is kept as the pre-calibration fallback for a thread that hasn't
# calibrated yet, not as shared mutable state.
_local = threading.local()
_calibrated_for: tuple[int, int] | None = None
_scale_center: float = 1.0


def _get_scale_center() -> float:
    return getattr(_local, "scale_center", _scale_center)

# Disk cache so short-lived one-off scripts (debug/VERIFY steps) don't each pay
# the ~25s anchor-scan cost. In-process runs (the real flow) never touch disk —
# the in-memory _calibrated_for check above always wins within one process.
#
# TTL is long (24h, not just a few minutes) because the cache key already
# includes the capture `shape` (resolution) — any real change that would
# invalidate a cached scale (different window size, different display,
# different capture resolution) changes that key and forces a fresh
# calibration regardless of TTL. The TTL only guards against the rarer case
# of the same-resolution capture rendering UI at a different scale (e.g. an
# in-game zoom/DPI change with no resolution change) — a real but uncommon
# risk, and a stale scale degrades matching rather than breaking it outright
# (thresholds/soft-retries elsewhere still catch bad matches). 24h trades a
# small amount of that risk for eliminating the ~25s recalibration cost on
# every poll of a long-running monitor loop.
_SCALE_CACHE_TTL_SEC = 24 * 60 * 60


def _scale_cache_path() -> Path:
    return logs_dir() / ".template_scale_cache.json"


def _shape_key(shape: tuple[int, int]) -> str:
    return f"{int(shape[0])}x{int(shape[1])}"


def _load_cached_scale(shape: tuple[int, int]) -> float | None:
    """
    Multi-entry cache keyed by capture shape.

    Not a single-slot cache: the passive BR detector captures the game
    WINDOW (one resolution) while the interactive flow captures the full
    DISPLAY (a different resolution) — a single-slot cache meant every
    switch between the two overwrote the other's entry, guaranteeing a
    ~25s recalibration on every flow start. Each shape now gets its own
    slot so both stay warm independently.
    """
    try:
        path = _scale_cache_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        entries = data.get("entries") if isinstance(data, dict) else None
        if entries is None:
            return None
        entry = entries.get(_shape_key(shape))
        if entry is None:
            return None
        if time.time() - float(entry.get("ts", 0)) > _SCALE_CACHE_TTL_SEC:
            return None
        return float(entry["scale"])
    except Exception:
        return None


def _save_cached_scale(shape: tuple[int, int], scale: float) -> None:
    try:
        path = _scale_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                if isinstance(loaded, dict) and isinstance(loaded.get("entries"), dict):
                    data = loaded
            except Exception:
                data = {}
        entries = data.setdefault("entries", {})
        entries[_shape_key(shape)] = {"scale": scale, "ts": time.time()}
        path.write_text(json.dumps(data))
    except Exception:
        pass


def _load_last_good_scale() -> float | None:
    """
    Most recent scale that was confirmed by a STRONG single-anchor match
    (conf >= _STRONG_CONF). Used as the sanity anchor for weak/ambiguous
    calibrations instead of the pixel-ratio `expected` estimate, which has
    been observed to be off by a large margin on some displays (the exact
    failure mode that let a false 0.375 peak get accepted as "close enough"
    to a wrong expected value, then cached for 24h — see incident 2026-07-30).
    """
    try:
        path = _scale_cache_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        entry = data.get("last_good") if isinstance(data, dict) else None
        if not entry:
            return None
        if time.time() - float(entry.get("ts", 0)) > _LAST_GOOD_TTL_SEC:
            return None
        return float(entry["scale"])
    except Exception:
        return None


def _save_last_good_scale(scale: float, conf: float) -> None:
    try:
        path = _scale_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
        data["last_good"] = {"scale": scale, "conf": conf, "ts": time.time()}
        path.write_text(json.dumps(data))
    except Exception:
        pass


def _revalidate_cached_scale(roi: np.ndarray, scale: float) -> bool:
    """
    Cheap single-scale re-probe of the calibration anchors against the
    *current* frame before trusting a disk-cached scale. A poisoned cache
    entry (wrong scale) will not match any real anchor at that scale, so
    this catches stale/bad cache without paying the full ~20s recalibration
    cost on every run — only on a cache miss/mismatch.
    """
    for tpl_name in _CALIBRATION_ANCHORS:
        tpl_path = templates_dir() / tpl_name
        if not tpl_path.exists():
            continue
        tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            continue
        if _probe_scale(roi, tpl, scale) >= _CACHE_REVALIDATE_CONF:
            return True
    return False


def _scaled_template(tpl: np.ndarray, scale: float) -> tuple[np.ndarray, int, int]:
    th, tw = tpl.shape
    sw = max(1, int(round(tw * scale)))
    sh = max(1, int(round(th * scale)))
    if scale == 1.0:
        return tpl, tw, th
    return cv2.resize(tpl, (sw, sh), interpolation=cv2.INTER_AREA), sw, sh


def _probe_scale(screen: np.ndarray, tpl: np.ndarray, scale: float) -> float:
    sh, sw = screen.shape
    scaled_tpl, tw, th = _scaled_template(tpl, scale)
    if th > sh or tw > sw:
        return 0.0
    result = cv2.matchTemplate(screen, scaled_tpl, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(result)[1])


def _expected_scale_for_screen(screen: np.ndarray) -> float:
    from lastz.screen import active_display_bounds

    cap_w = screen.shape[1]
    _, _, dw, _ = active_display_bounds()
    if dw <= 0:
        return 1.0
    return (cap_w / dw) / REF_PIXEL_RATIO


def _full_scale_band() -> list[float]:
    return [round(x, 3) for x in np.arange(_SCALE_LO, _SCALE_HI + 0.001, _SCALE_STEP)]


def _local_scale_band(center: float) -> list[float]:
    lo = max(_SCALE_LO, center - _LOCAL_DELTA)
    hi = min(_SCALE_HI, center + _LOCAL_DELTA)
    return [round(x, 3) for x in np.arange(lo, hi + 0.001, _LOCAL_STEP)]


def _clamp_scale(scale: float) -> float:
    return float(max(_SCALE_LO, min(_SCALE_HI, scale)))


def game_window_roi(screen: np.ndarray) -> tuple[np.ndarray, int, int]:
    """
    Crop the capture to the game window in capture-pixel space.

    Returns (roi_image, origin_x, origin_y). On failure, returns the full screen
    with origin (0, 0).
    """
    from lastz.screen import active_display_bounds, get_game_window_bounds

    sh, sw = screen.shape[:2]
    try:
        wx, wy, ww, wh = get_game_window_bounds()
        dx, dy, dw, dh = active_display_bounds()
        if dw <= 0 or dh <= 0 or ww <= 0 or wh <= 0:
            return screen, 0, 0

        # Logical window → capture pixels on the active display
        x0 = int(round((wx - dx) * sw / dw))
        y0 = int(round((wy - dy) * sh / dh))
        x1 = int(round((wx - dx + ww) * sw / dw))
        y1 = int(round((wy - dy + wh) * sh / dh))

        x0 = max(0, min(sw - 1, x0))
        y0 = max(0, min(sh - 1, y0))
        x1 = max(x0 + 1, min(sw, x1))
        y1 = max(y0 + 1, min(sh, y1))

        roi = screen[y0:y1, x0:x1]
        if roi.size == 0:
            return screen, 0, 0
        return roi, x0, y0
    except Exception:
        return screen, 0, 0


def _ensure_scale_calibrated(screen: np.ndarray) -> None:
    shape = (screen.shape[1], screen.shape[0])
    if getattr(_local, "calibrated_for", None) == shape:
        return

    roi, _, _ = game_window_roi(screen)

    cached = _load_cached_scale(shape)
    if cached is not None:
        if _revalidate_cached_scale(roi, cached):
            _local.scale_center = cached
            _local.calibrated_for = shape
            print(f"[vision] Template scale from disk cache: {cached:.3f}")
            return
        print(
            f"[vision] Disk-cached scale {cached:.3f} failed re-validation on "
            f"live frame (no anchor >= {_CACHE_REVALIDATE_CONF}) — recalibrating."
        )

    t0 = time.perf_counter()
    expected = _clamp_scale(_expected_scale_for_screen(screen))
    last_good = _load_last_good_scale()
    best_scale = last_good if last_good is not None else expected
    best_conf = 0.0
    best_anchor = ""

    for tpl_name in _CALIBRATION_ANCHORS:
        tpl_path = templates_dir() / tpl_name
        if not tpl_path.exists():
            continue
        tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            continue
        for scale in _full_scale_band():
            conf = _probe_scale(roi, tpl, scale)
            if conf > best_conf:
                best_conf = conf
                best_scale = scale
                best_anchor = tpl_name

    ms = (time.perf_counter() - t0) * 1000.0
    fallback = last_good if last_good is not None else expected
    fallback_label = "last-good" if last_good is not None else "expected"

    if best_conf >= _STRONG_CONF:
        # Strong single-anchor lock — trust it outright and remember it as
        # the new sanity anchor for future weak/ambiguous calibrations.
        new_scale = _clamp_scale(best_scale)
        print(
            f"[vision] Auto template scale: {new_scale:.3f} "
            f"(anchor={best_anchor} conf={best_conf:.4f}) ms={ms:.0f}"
        )
        _save_last_good_scale(new_scale, best_conf)
        _save_cached_scale(shape, new_scale)
    elif best_conf >= _ACCEPT_CONF:
        # Weak lock (e.g. a modal/popup partially hiding HUD anchors can
        # invent a bogus peak). Only trust it if it agrees with the last
        # confirmed-good scale; otherwise a wrong peak here would silently
        # get cached for hours (the 2026-07-30 0.375 incident). The old
        # pixel-ratio "expected" check was not reliable enough on its own —
        # it was itself off from the true scale on this display, which is
        # exactly how the bad peak slipped through last time.
        if last_good is not None and abs(best_scale - last_good) <= _WEAK_AGREE_DELTA:
            new_scale = _clamp_scale(best_scale)
            print(
                f"[vision] Auto template scale: {new_scale:.3f} "
                f"(weak anchor={best_anchor} conf={best_conf:.4f}, "
                f"confirmed by last-good) ms={ms:.0f}"
            )
            _save_cached_scale(shape, new_scale)
        else:
            new_scale = _clamp_scale(fallback)
            print(
                f"[vision] Auto template scale: {new_scale:.3f} "
                f"({fallback_label}; rejected dubious {best_scale:.3f} "
                f"anchor={best_anchor} conf={best_conf:.4f}) ms={ms:.0f}"
            )
            # Do not persist a rejected/dubious reading.
    else:
        new_scale = _clamp_scale(fallback)
        print(
            f"[vision] WARN: weak anchors (best conf={best_conf:.4f}). "
            f"Using {fallback_label} scale {new_scale:.3f}. "
            f"Keep game on wilderness/base map, fully visible on one display. "
            f"ms={ms:.0f}"
        )

    _local.scale_center = new_scale
    _local.calibrated_for = shape


def current_template_scale() -> float:
    """Return the last calibrated template scale center (1.0 if not yet calibrated)."""
    return float(_get_scale_center())


def ensure_template_scale(screen: np.ndarray) -> None:
    """Calibrate template scale from a full (or game-ROI) capture."""
    _ensure_scale_calibrated(screen)


def template_scales() -> list[float]:
    # Read once so this thread's search band is built from a single,
    # consistent scale — not two reads straddling another thread's
    # concurrent calibration (see _local's docstring above).
    center = _get_scale_center()
    # Always include 1.0 so a stuck bad center still finds Retina templates.
    scales = set(_local_scale_band(center))
    scales.add(1.0)
    scales.add(round(center, 3))
    return sorted(scales)


def _match_at_scales(
    search: np.ndarray,
    tpl: np.ndarray,
    scales: list[float],
) -> Match | None:
    sh, sw = search.shape[:2]
    best: Match | None = None
    for scale in scales:
        scaled_tpl, tw, th = _scaled_template(tpl, scale)
        if th > sh or tw > sw:
            continue
        result = cv2.matchTemplate(search, scaled_tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if best is None or max_val > best.confidence:
            best = Match(
                phys_x=max_loc[0] + tw / 2.0,
                phys_y=max_loc[1] + th / 2.0,
                confidence=float(max_val),
            )
    return best


def find_template_local(
    image: np.ndarray,
    template_name: str,
    threshold: float,
    *,
    template_path: Path | None = None,
    scales: list[float] | None = None,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> Match | None:
    """
    Match a template on a pre-cropped image (no game-window ROI, no logging).

    Returns Match in caller coordinates: (origin + local center). Use after a
    full capture has calibrated template scale, or pass explicit scales.
    """
    tpl_path = template_path or (templates_dir() / template_name)
    if not tpl_path.exists():
        return None
    tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return None

    search_scales = scales if scales is not None else template_scales()
    best = _match_at_scales(image, tpl, search_scales)
    if best is None or best.confidence < threshold:
        return None
    return Match(
        phys_x=best.phys_x + origin_x,
        phys_y=best.phys_y + origin_y,
        confidence=best.confidence,
    )


def find_template(
    screen: np.ndarray,
    template_name: str,
    threshold: float,
    *,
    template_path: Path | None = None,
    scales: list[float] | None = None,
) -> Match | None:
    t0 = time.perf_counter()
    _ensure_scale_calibrated(screen)

    tpl_path = template_path or (templates_dir() / template_name)
    if not tpl_path.exists():
        print(f"[vision] Template not found: {tpl_path}")
        return None

    tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        print(f"[vision] Could not load template image: {tpl_path}")
        return None

    roi, ox, oy = game_window_roi(screen)
    search_scales = scales if scales is not None else template_scales()

    best = _match_at_scales(roi, tpl, search_scales)

    # Full-band only on a *near miss* (local peak close to threshold).
    # Blind full-band on every miss costs ~10–34s on ultrawide — skip it.
    refined = False
    if scales is None and best is not None and best.confidence < threshold:
        near = max(0.55, threshold - 0.15)
        if best.confidence >= near:
            coarse = _match_at_scales(roi, tpl, _full_scale_band())
            if coarse is not None and coarse.confidence > best.confidence:
                best = coarse
                refined = True

    ms = (time.perf_counter() - t0) * 1000.0
    if best is None:
        sh, sw = roi.shape[:2]
        print(
            f"[vision] '{template_name}' — no valid scale fit for ROI "
            f"({sw}x{sh}) ms={ms:.0f}"
        )
        return None

    # Remap ROI-local center → full capture coordinates
    best = Match(
        phys_x=best.phys_x + ox,
        phys_y=best.phys_y + oy,
        confidence=best.confidence,
    )

    refine_bit = " refined=full_band" if refined else ""
    print(
        f"[vision] '{template_name}' match confidence = {best.confidence:.4f} "
        f"(threshold {threshold}){refine_bit} ms={ms:.0f}"
    )

    if best.confidence < threshold:
        return None

    return best


def find_any(
    screen: np.ndarray,
    template_names: list[str],
    threshold: float,
) -> Match | None:
    for name in template_names:
        m = find_template(screen, name, threshold)
        if m is not None:
            return m
    return None


def click_template(
    template_name: str,
    threshold: float,
    *,
    template_path: Path | None = None,
    label: str | None = None,
) -> Match | None:
    """Find a template on the current screen and click its center. Returns the match."""
    from lastz.input import click
    from lastz.screen import capture, physical_to_logical

    screen = capture()
    match = find_template(screen, template_name, threshold, template_path=template_path)
    if match is None:
        return None
    lx, ly = physical_to_logical(match.phys_x, match.phys_y)
    name = label or template_name
    print(f"-> Clicking {name} at logical ({lx:.0f}, {ly:.0f}) [conf={match.confidence:.4f}]")
    click(lx, ly)
    return match


def find_all_templates(
    screen: np.ndarray,
    template_name: str,
    threshold: float,
    *,
    template_path: Path | None = None,
    nms_iou: float = 0.3,
    exclude_regions: list[tuple[int, int, int, int]] | None = None,
    scales: list[float] | None = None,
) -> list[MatchWithBBox]:
    t0 = time.perf_counter()
    _ensure_scale_calibrated(screen)

    tpl_path = template_path or (templates_dir() / template_name)
    if not tpl_path.exists():
        print(f"[vision] Template not found: {tpl_path}")
        return []

    tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        print(f"[vision] Could not load template: {tpl_path}")
        return []

    roi, ox, oy = game_window_roi(screen)
    sh, sw = roi.shape[:2]
    search_scales = scales if scales is not None else template_scales()

    boxes: list[list] = []
    for scale in search_scales:
        scaled_tpl, tw, th = _scaled_template(tpl, scale)
        if th > sh or tw > sw:
            continue

        result = cv2.matchTemplate(roi, scaled_tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= threshold)
        if len(xs) == 0:
            continue

        confidences = result[ys, xs]
        for x, y, conf in zip(xs.tolist(), ys.tolist(), confidences.tolist()):
            # Store in full-capture coordinates
            boxes.append([x + ox, y + oy, x + ox + tw, y + oy + th, float(conf)])
            # Cap raw peaks — blurry templates can explode to hundreds of hits
            if len(boxes) >= 80:
                break
        if len(boxes) >= 80:
            break

    if not boxes:
        ms = (time.perf_counter() - t0) * 1000.0
        print(
            f"[vision] '{template_name}' all-match: 0 found "
            f"(threshold {threshold}) ms={ms:.0f}"
        )
        return []

    if len(boxes) > 40:
        # Keep highest-confidence peaks before NMS when a template is too generic
        boxes.sort(key=lambda b: b[4], reverse=True)
        boxes = boxes[:40]
        print(f"[vision] '{template_name}' capped multi-match peaks to 40 (was many)")

    boxes = _nms(boxes, nms_iou)

    matches = []
    for x1, y1, x2, y2, conf in boxes:
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0

        if exclude_regions:
            if any(ex1 <= cx <= ex2 and ey1 <= cy <= ey2 for ex1, ey1, ex2, ey2 in exclude_regions):
                continue

        matches.append(
            MatchWithBBox(
                phys_x=cx,
                phys_y=cy,
                phys_w=int(x2 - x1),
                phys_h=int(y2 - y1),
                confidence=conf,
            )
        )

    matches.sort(key=lambda m: m.confidence, reverse=True)
    ms = (time.perf_counter() - t0) * 1000.0
    print(
        f"[vision] '{template_name}' all-match: {len(matches)} found "
        f"(threshold {threshold}) ms={ms:.0f}"
    )
    return matches


def _nms(boxes: list[list], iou_threshold: float) -> list[list]:
    if not boxes:
        return []
    boxes_sorted = sorted(boxes, key=lambda b: b[4], reverse=True)
    kept = []
    while boxes_sorted:
        current = boxes_sorted.pop(0)
        kept.append(current)
        boxes_sorted = [
            b for b in boxes_sorted
            if _iou(current, b) < iou_threshold
        ]
    return kept


def _iou(a: list, b: list) -> float:
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def cluster_matches(
    matches: list[MatchWithBBox],
    radius_px: float = 60.0,
) -> list[MatchWithBBox]:
    if not matches:
        return []
    remaining = list(matches)
    clustered: list[MatchWithBBox] = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        still_remaining = []
        for m in remaining:
            dist = ((m.phys_x - seed.phys_x) ** 2 + (m.phys_y - seed.phys_y) ** 2) ** 0.5
            if dist <= radius_px:
                cluster.append(m)
            else:
                still_remaining.append(m)
        remaining = still_remaining
        best = max(cluster, key=lambda m: m.confidence)
        clustered.append(best)
    return clustered
