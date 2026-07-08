"""Grid OCR scan for map labels at HQ zoom and city zoom."""
from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

from lastz.config import scouting_cfg
from lastz.ocr import parse_alliance_tag, parse_city_label, parse_map_hq_label, read_text_from_region


@dataclass
class MapTextHit:
    text: str
    alliance_tag: str | None
    name: str | None
    level: int | None
    phys_x: int
    phys_y: int
    kind: str  # "hq" | "city"


def _hud_mask(shape: tuple[int, int]) -> tuple[int, int, int, int]:
    h, w = shape
    exc = scouting_cfg().get("hud_exclude", {})
    return (
        int(w * float(exc.get("left_frac", 0.08))),
        int(h * float(exc.get("top_frac", 0.10))),
        int(w * (1 - float(exc.get("right_frac", 0.10)))),
        int(h * (1 - float(exc.get("bottom_frac", 0.14)))),
    )


def _ocr_patch(color_patch: np.ndarray) -> str:
    try:
        import pytesseract
    except ImportError:
        return ""
    up = cv2.resize(color_patch, (color_patch.shape[1] * 3, color_patch.shape[0] * 3))
    gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    return pytesseract.image_to_string(
        bw,
        config="--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]():., ",
    ).strip()


def _valid_city(tag: str | None, name: str | None, text: str) -> bool:
    if "[" not in text or not tag or len(tag) < 2:
        return False
    if not name or len(name) < 3:
        return False
    if name.isdigit():
        return False
    return True


def _valid_hq(tag: str | None, name: str | None, text: str) -> bool:
    if "[" not in text or not tag or len(tag) < 2:
        return False
    if not name or len(name) < 3:
        return False
    return True


def scan_map_labels(
    color: np.ndarray,
    *,
    kind: str = "hq",
    strict: bool = True,
    region: str | None = None,
) -> list[MapTextHit]:
    """
    Tile-scan the map area for alliance tags and levels.

    kind="hq"   — player HQ labels: [TAG]Player + level
    kind="city" — strategic zoom: [TAG]CityName + city level
    """
    h, w = color.shape[:2]
    x0, y0, x1, y1 = _hud_mask((h, w))
    if region == "hq_cluster":
        reg = scouting_cfg().get("hq_cluster_scan", {})
        x0 = int(w * float(reg.get("left_frac", 0.05)))
        y0 = int(h * float(reg.get("top_frac", 0.10)))
        x1 = int(w * float(reg.get("right_frac", 0.48)))
        y1 = int(h * float(reg.get("bottom_frac", 0.58)))
    roi = color[y0:y1, x0:x1]

    scan = scouting_cfg().get("scan", {})
    if kind == "hq":
        tile = int(scan.get("hq_ocr_tile_px", scan.get("ocr_tile_px", 200)))
        stride = int(scan.get("hq_ocr_stride_px", scan.get("ocr_stride_px", 100)))
    else:
        tile = int(scan.get("ocr_tile_px", 320))
        stride = int(scan.get("ocr_stride_px", tile // 2))

    hits: list[MapTextHit] = []
    rh, rw = roi.shape[:2]
    for ty in range(0, max(1, rh - tile), stride):
        for tx in range(0, max(1, rw - tile), stride):
            patch = roi[ty : ty + tile, tx : tx + tile]
            text = _ocr_patch(patch)
            if "[" not in text and not re.search(r"\b\d{1,3}\b", text):
                continue

            if kind == "city":
                parsed = parse_city_label(text)
                if parsed.get("is_empty"):
                    continue
                tag = parsed.get("alliance_tag")
                name = parsed.get("city_name")
                level = parsed.get("city_level")
            else:
                parsed = parse_map_hq_label(text)
                tag = parsed.get("alliance_tag")
                name = parsed.get("player_name")
                level = parsed.get("hq_level")

            if not tag and not name:
                continue
            if strict and kind == "city" and not _valid_city(tag, name, text):
                continue
            if strict and kind == "hq" and not _valid_hq(tag, name, text):
                continue
            if tag and len(tag) < 2:
                continue
            if name and len(name) < 3 and name.isdigit():
                continue

            cx = x0 + tx + tile // 2
            cy = y0 + ty + tile // 2
            hits.append(MapTextHit(text, tag, name, level, cx, cy, kind))

    # dedupe nearby
    uniq: list[MapTextHit] = []
    for hit in hits:
        if any(
            abs(hit.phys_x - u.phys_x) < 120 and abs(hit.phys_y - u.phys_y) < 80
            for u in uniq
        ):
            continue
        uniq.append(hit)
    return uniq
