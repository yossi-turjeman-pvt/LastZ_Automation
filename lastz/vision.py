"""
OpenCV template matching with full-dynamic scale and game-window ROI.

Scale is discovered every run from on-screen anchors (no per-machine calibration).
Matching is restricted to the game window region so desktop chrome cannot win.
"""
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

from lastz.config import templates_dir

REF_PIXEL_RATIO = 3024 / 1512  # templates captured on built-in Retina laptop

_SCALE_LO = 0.35
_SCALE_HI = 1.25
_SCALE_STEP = 0.025
_ACCEPT_CONF = 0.70
_LOCAL_DELTA = 0.20
_LOCAL_STEP = 0.025

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


_calibrated_for: tuple[int, int] | None = None
_scale_center: float = 1.0


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
    global _calibrated_for, _scale_center

    shape = (screen.shape[1], screen.shape[0])
    if _calibrated_for == shape:
        return

    roi, _, _ = game_window_roi(screen)
    expected = _clamp_scale(_expected_scale_for_screen(screen))
    best_scale = expected
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

    if best_conf >= _ACCEPT_CONF:
        # Modals hide HUD anchors and can invent a bogus scale peak (e.g. 0.40).
        # Prefer the pixel-ratio expectation unless the anchor is clearly strong.
        if abs(best_scale - expected) > 0.15 and best_conf < 0.92:
            _scale_center = expected
            print(
                f"[vision] Auto template scale: {_scale_center:.3f} "
                f"(expected; rejected dubious {best_scale:.3f} "
                f"anchor={best_anchor} conf={best_conf:.4f})"
            )
        else:
            _scale_center = _clamp_scale(best_scale)
            print(
                f"[vision] Auto template scale: {_scale_center:.3f} "
                f"(anchor={best_anchor} conf={best_conf:.4f})"
            )
    else:
        _scale_center = expected
        print(
            f"[vision] WARN: weak anchors (best conf={best_conf:.4f}). "
            f"Using pixel-ratio scale {_scale_center:.3f}. "
            f"Keep game on wilderness/base map, fully visible on one display."
        )

    _calibrated_for = shape


def current_template_scale() -> float:
    """Return the last calibrated template scale center (1.0 if not yet calibrated)."""
    return float(_scale_center)


def ensure_template_scale(screen: np.ndarray) -> None:
    """Calibrate template scale from a full (or game-ROI) capture."""
    _ensure_scale_calibrated(screen)


def template_scales() -> list[float]:
    # Always include 1.0 so a stuck bad center still finds Retina templates.
    scales = set(_local_scale_band(_scale_center))
    scales.add(1.0)
    scales.add(round(_scale_center, 3))
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

    # Coarse full-band re-search if local band misses (stuck scale lock).
    needs_refine = (best is None or best.confidence < threshold) and scales is None
    if needs_refine:
        coarse = _match_at_scales(roi, tpl, _full_scale_band())
        if coarse is not None and (best is None or coarse.confidence > best.confidence):
            best = coarse
            print(
                f"[vision] '{template_name}' refined via full scale band "
                f"(conf={best.confidence:.4f})"
            )

    if best is None:
        sh, sw = roi.shape[:2]
        print(f"[vision] '{template_name}' — no valid scale fit for ROI ({sw}x{sh})")
        return None

    # Remap ROI-local center → full capture coordinates
    best = Match(
        phys_x=best.phys_x + ox,
        phys_y=best.phys_y + oy,
        confidence=best.confidence,
    )

    print(f"[vision] '{template_name}' match confidence = {best.confidence:.4f} (threshold {threshold})")

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

    if not boxes and scales is None:
        # Coarse full-band pass for multi-match (e.g. claim buttons)
        for scale in _full_scale_band():
            scaled_tpl, tw, th = _scaled_template(tpl, scale)
            if th > sh or tw > sw:
                continue
            result = cv2.matchTemplate(roi, scaled_tpl, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(result >= threshold)
            if len(xs) == 0:
                continue
            confidences = result[ys, xs]
            for x, y, conf in zip(xs.tolist(), ys.tolist(), confidences.tolist()):
                boxes.append([x + ox, y + oy, x + ox + tw, y + oy + th, float(conf)])
                if len(boxes) >= 80:
                    break
            if len(boxes) >= 80:
                break

    if not boxes:
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
    print(f"[vision] '{template_name}' all-match: {len(matches)} found (threshold {threshold})")
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
