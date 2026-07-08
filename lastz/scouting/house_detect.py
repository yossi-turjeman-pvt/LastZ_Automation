"""
Detect player HQ house icons at strategic (zoomed-out) map level.

Algorithm (agreed spec):
  1. Template-match house silhouettes (house_*.png) — NOT bare white digits
  2. NMS dedupe; read level digit below each match
  3. Reject level > max_hq_level from config
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from lastz.config import scouting_cfg, templates_dir

_HOUSE_TEMPLATES: dict[str, float] = {
    "house_blue.png": 0.68,
    "house_grey.png": 0.68,
    "house_grey2.png": 0.72,
    "house_purple.png": 0.74,
}


def _template_thresholds() -> dict[str, float]:
    cfg = scouting_cfg()
    overrides = cfg.get("house_icon_thresholds") or {}
    out = dict(_HOUSE_TEMPLATES)
    for name, val in overrides.items():
        key = name if name.endswith(".png") else f"house_{name}.png"
        out[key] = float(val)
    if "house_icon_threshold" in cfg:
        floor = float(cfg["house_icon_threshold"])
        out = {k: max(v, floor) for k, v in out.items()}
    return out


@dataclass
class HouseHq:
    phys_x: int
    phys_y: int
    hq_level: int | None
    confidence: float
    color: str | None = None


def _map_roi(color: np.ndarray) -> tuple[np.ndarray, np.ndarray, int, int]:
    h, w = color.shape[:2]
    exc = scouting_cfg().get("hud_exclude", {})
    x0 = int(w * float(exc.get("left_frac", 0.08)))
    y0 = int(h * float(exc.get("top_frac", 0.10)))
    x1 = int(w * (1 - float(exc.get("right_frac", 0.10))))
    y1 = int(h * (1 - float(exc.get("bottom_frac", 0.14))))
    roi = color[y0:y1, x0:x1]
    return roi, cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), x0, y0


def _quick_level(gray_patch: np.ndarray) -> int | None:
    if gray_patch.size == 0:
        return None
    up = cv2.resize(gray_patch, (max(20, gray_patch.shape[1] * 5), max(20, gray_patch.shape[0] * 5)))
    _, bw = cv2.threshold(up, 170, 255, cv2.THRESH_BINARY)
    try:
        import pytesseract
        text = pytesseract.image_to_string(
            bw, config="--psm 7 -c tessedit_char_whitelist=0123456789"
        ).strip()
    except ImportError:
        return None
    m = re.search(r"\d{1,3}", text)
    return int(m.group()) if m else None


def _nms(points: list[tuple[int, int, float, str]], radius: int) -> list[tuple[int, int, float, str]]:
    points = sorted(points, key=lambda p: -p[2])
    kept: list[tuple[int, int, float, str]] = []
    for x, y, score, tag in points:
        if any(abs(x - kx) < radius and abs(y - ky) < radius for kx, ky, _, _ in kept):
            continue
        kept.append((x, y, score, tag))
    return kept


def _level_below(gray: np.ndarray, cx: int, cy: int, th: int) -> int | None:
    """Read HQ level in patch just below house icon center."""
    h, w = gray.shape[:2]
    y1 = min(h - 1, cy + th // 2)
    y2 = min(h, y1 + 22)
    x1 = max(0, cx - 12)
    x2 = min(w, cx + 12)
    return _quick_level(gray[y1:y2, x1:x2])


def find_house_hqs(color: np.ndarray) -> list[HouseHq]:
    """Find player HQ house icons. Click point = house icon center."""
    roi, gray, x0, y0 = _map_roi(color)
    thresh_map = _template_thresholds()
    max_lvl = int(scouting_cfg().get("max_hq_level", 99))

    raw_hits: list[tuple[int, int, float, str]] = []
    for tpl_name, thresh in thresh_map.items():
        tpl_path = templates_dir() / tpl_name
        if not tpl_path.exists():
            continue
        tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
        if tpl is None or tpl.shape[0] > gray.shape[0] or tpl.shape[1] > gray.shape[1]:
            continue
        tag = tpl_name.replace("house_", "").replace(".png", "")
        res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        th, tw = tpl.shape[:2]
        for py, px in zip(*np.where(res >= thresh)):
            cx = x0 + px + tw // 2
            cy = y0 + py + th // 2
            raw_hits.append((cx, cy, float(res[py, px]), tag))

    candidates: list[HouseHq] = []
    for cx, cy, score, tag in _nms(raw_hits, radius=26):
        candidates.append(HouseHq(cx, cy, None, min(1.0, score), tag))

    candidates.sort(key=lambda c: -c.confidence)
    return candidates
