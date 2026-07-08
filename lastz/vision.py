"""
OpenCV template matching with safety guards.

Template scale is derived from display pixel ratio and refined using HQ
navigation anchors visible on the base map screen.
"""
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

from lastz.config import templates_dir

REF_PIXEL_RATIO = 3024 / 1512  # templates captured on built-in Retina laptop

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


# Only use mode-switcher buttons for scale calibration — always on base map,
# never inside modals (unlike orange_icon or alliance UI).
_CALIBRATION_ANCHORS = ("wilderness_hq_button.png", "hq_world_button.png")
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


def _scale_search_range(expected: float) -> list[float]:
    lo = max(0.30, expected * 0.60)
    hi = min(1.40, expected * 1.50)
    return [round(x, 3) for x in np.arange(lo, hi + 0.001, 0.025)]


def _ensure_scale_calibrated(screen: np.ndarray) -> None:
    global _calibrated_for, _scale_center

    shape = (screen.shape[1], screen.shape[0])
    if _calibrated_for == shape:
        return

    expected = _expected_scale_for_screen(screen)
    best_scale = expected
    best_conf = 0.0

    for tpl_name in _CALIBRATION_ANCHORS:
        tpl_path = templates_dir() / tpl_name
        if not tpl_path.exists():
            continue
        tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            continue
        for scale in _scale_search_range(expected):
            conf = _probe_scale(screen, tpl, scale)
            if conf > best_conf:
                best_conf = conf
                best_scale = scale

    if best_conf >= 0.55:
        _scale_center = best_scale
        print(f"[vision] Auto template scale: {best_scale:.3f} (anchor conf={best_conf:.4f})")
    else:
        _scale_center = expected
        print(f"[vision] Template scale from pixel ratio: {expected:.3f} (anchors below threshold)")

    _calibrated_for = shape


def template_scales() -> list[float]:
    deltas = (-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15)
    return [round(_scale_center + d, 3) for d in deltas]


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

    sh, sw = screen.shape
    search_scales = scales if scales is not None else template_scales()

    best: Match | None = None
    for scale in search_scales:
        scaled_tpl, tw, th = _scaled_template(tpl, scale)
        if th > sh or tw > sw:
            continue

        result = cv2.matchTemplate(screen, scaled_tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if best is None or max_val > best.confidence:
            center_x = max_loc[0] + tw / 2
            center_y = max_loc[1] + th / 2
            best = Match(phys_x=center_x, phys_y=center_y, confidence=max_val)

    if best is None:
        print(f"[vision] '{template_name}' — no valid scale fit for screen ({sw}x{sh})")
        return None

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

    sh, sw = screen.shape
    search_scales = scales if scales is not None else template_scales()

    boxes: list[list] = []
    for scale in search_scales:
        scaled_tpl, tw, th = _scaled_template(tpl, scale)
        if th > sh or tw > sw:
            continue

        result = cv2.matchTemplate(screen, scaled_tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= threshold)
        if len(xs) == 0:
            continue

        confidences = result[ys, xs]
        for x, y, conf in zip(xs.tolist(), ys.tolist(), confidences.tolist()):
            boxes.append([x, y, x + tw, y + th, float(conf)])

    if not boxes:
        return []

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
