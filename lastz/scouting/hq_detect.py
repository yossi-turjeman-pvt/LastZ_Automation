"""
Detect player HQ buildings on the wilderness map.

Visual signature (learned from reference screenshots):
  1. Building cluster — blue/teal or grey metallic roof (not a mob silhouette)
  2. Dark nameplate bar below building — flag icon + player name
  3. White level pill below nameplate — small bright rounded rect with level number

NOT an HQ:
  - Zombie/mob — large red/purple body, black level circle on ground
  - Resource node — small static icon, black level circle
  - Empty tile — flat grass, no building cluster
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from lastz.config import scouting_cfg
from lastz.ocr import parse_map_hq_label, read_text_from_region


@dataclass
class HqCandidate:
    phys_x: int
    phys_y: int
    alliance_tag: str | None
    player_name: str | None
    hq_level: int | None
    confidence: float  # 0-1 score


def _map_roi(color: np.ndarray) -> tuple[np.ndarray, int, int]:
    h, w = color.shape[:2]
    exc = scouting_cfg().get("hud_exclude", {})
    x0 = int(w * float(exc.get("left_frac", 0.06)))
    y0 = int(h * float(exc.get("top_frac", 0.07)))
    x1 = int(w * (1 - float(exc.get("right_frac", 0.18))))
    y1 = int(h * (1 - float(exc.get("bottom_frac", 0.20))))
    return color[y0:y1, x0:x1], x0, y0


def _building_mask(roi: np.ndarray) -> np.ndarray:
    """Pixels belonging to HQ-style buildings (blue/teal roof or grey structure)."""
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (85, 25, 70), (135, 255, 255))
    grey = cv2.inRange(hsv, (0, 0, 90), (180, 45, 210))
    mask = cv2.bitwise_or(blue, grey)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)


def _is_zombie_body(patch: np.ndarray) -> bool:
    """Red/purple flesh in the lower body area — but not if building has blue roof."""
    if patch.size == 0:
        return False
    ph, pw = patch.shape[:2]
    top = patch[: int(ph * 0.55), :]
    hsv_top = cv2.cvtColor(top, cv2.COLOR_BGR2HSV)
    blue_roof = cv2.inRange(hsv_top, (85, 25, 70), (135, 255, 255))
    if float(blue_roof.mean()) > 8:
        return False  # HQ-style building roof present

    lower = patch[int(ph * 0.35) :, :]
    hsv = cv2.cvtColor(lower, cv2.COLOR_BGR2HSV)
    flesh = cv2.inRange(hsv, (0, 40, 50), (18, 255, 255))
    purple = cv2.inRange(hsv, (125, 35, 50), (165, 255, 255))
    return float(cv2.bitwise_or(flesh, purple).mean()) > 22


def _level_badge_kind(patch: np.ndarray) -> str | None:
    """
  Classify level indicator below a map object.
  Returns 'hq' (white pill), 'mob' (black circle), or None.
    """
    if patch.size == 0:
        return None
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]

    # White HQ pill — bright horizontal blob
    bright = (gray > 195).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 3))
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, k)
    for c in cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, bw, bh = cv2.boundingRect(c)
        if 16 <= bw <= 50 and 8 <= bh <= 20 and bw / max(bh, 1) >= 1.4:
            return "hq"

    # Black mob circle — dark blob with bright digit inside
    dark = (gray < 55).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    for c in cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, bw, bh = cv2.boundingRect(c)
        if 14 <= bw <= 36 and 14 <= bh <= 36 and abs(bw - bh) < 10:
            return "mob"
    return None


def _ocr_nameplate(roi: np.ndarray, bx: int, by: int, bw: int, bh: int) -> dict:
    """OCR the nameplate on the lower part of a building cluster."""
    rh, rw = roi.shape[:2]
    y1 = max(0, by + int(bh * 0.45))
    y2 = min(rh, by + bh + 55)
    x1 = max(0, bx - 30)
    x2 = min(rw, bx + bw + 30)
    plate = roi[y1:y2, x1:x2]
    if plate.size == 0 or plate.shape[0] < 12:
        return {}
    text = read_text_from_region(plate, 0, 0, plate.shape[1], plate.shape[0])
    return parse_map_hq_label(text) | {"raw": text}


def find_player_hqs(color: np.ndarray) -> list[HqCandidate]:
    """
    Find player HQ buildings on a wilderness map screenshot.

    Returns candidates sorted by confidence (best first).
    Click point is the building center (between nameplate and roof).
    """
    roi, x0, y0 = _map_roi(color)
    rh, rw = roi.shape[:2]
    mask = _building_mask(roi)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[HqCandidate] = []

    for c in contours:
        bx, by, bw, bh = cv2.boundingRect(c)
        area = bw * bh
        if area < 700 or area > 12000 or bh < 28 or bw < 28:
            continue

        # Full context patch: building + nameplate + level badge
        py1 = max(0, by - 10)
        py2 = min(rh, by + bh + 75)
        px1 = max(0, bx - 50)
        px2 = min(rw, bx + bw + 50)
        patch = roi[py1:py2, px1:px2]

        if _is_zombie_body(patch):
            continue

        # Level badge is in bottom third of context patch
        badge_region = patch[int(patch.shape[0] * 0.55) :, :]
        badge = _level_badge_kind(badge_region)
        if badge != "hq":
            continue

        parsed = _ocr_nameplate(roi, bx, by, bw, bh)
        raw = parsed.get("raw", "")

        # Building must have nameplate signal: dark bar or bracket in OCR
        has_nameplate = "[" in raw or bool(parsed.get("player_name"))
        if not has_nameplate:
            # Check for dark horizontal bar below building
            plate_y1 = min(rh - 1, by + bh)
            plate_y2 = min(rh, plate_y1 + 40)
            plate = roi[plate_y1:plate_y2, max(0, bx - 10) : min(rw, bx + bw + 10)]
            if plate.size:
                plate_gray = cv2.cvtColor(plate, cv2.COLOR_BGR2GRAY)
                has_nameplate = float((plate_gray < 100).mean()) > 0.15

        if not has_nameplate:
            continue

        score = 0.5
        if parsed.get("alliance_tag"):
            score += 0.2
        if parsed.get("player_name"):
            score += 0.15
        if parsed.get("hq_level"):
            score += 0.1
        if "[" in raw:
            score += 0.05

        click_x = x0 + bx + bw // 2
        click_y = y0 + by + bh // 2

        candidates.append(HqCandidate(
            phys_x=click_x,
            phys_y=click_y,
            alliance_tag=parsed.get("alliance_tag"),
            player_name=parsed.get("player_name"),
            hq_level=parsed.get("hq_level"),
            confidence=min(1.0, score),
        ))

    # Deduplicate overlapping detections
    candidates.sort(key=lambda c: -c.confidence)
    uniq: list[HqCandidate] = []
    for cand in candidates:
        if any(
            abs(cand.phys_x - u.phys_x) < 90 and abs(cand.phys_y - u.phys_y) < 70
            for u in uniq
        ):
            continue
        uniq.append(cand)
    return uniq
