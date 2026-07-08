"""Detect player HQ detail modal vs empty-tile / other popups."""
from __future__ import annotations

import cv2
import numpy as np

from lastz.config import templates_dir, threshold as cfg_threshold
from lastz.ocr import read_text_from_region


def _action_row(color: np.ndarray) -> np.ndarray:
    h, w = color.shape[:2]
    return color[int(h * 0.52) : int(h * 0.72), int(w * 0.30) : int(w * 0.70)]


def _stats_panel(color: np.ndarray) -> np.ndarray:
    h, w = color.shape[:2]
    return color[int(h * 0.30) : int(h * 0.62), int(w * 0.26) : int(w * 0.54)]


def _scout_button_visible(color: np.ndarray) -> bool:
    tpl_path = templates_dir() / "scout_action_btn.png"
    if not tpl_path.exists():
        return False
    tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return False
    row = _action_row(color)
    gray = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY)
    if tpl.shape[0] > gray.shape[0] or tpl.shape[1] > gray.shape[1]:
        return False
    res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
    return float(res.max()) >= cfg_threshold("scout_action_btn") - 0.05


def _reject_popup_text(text: str) -> bool:
    low = text.lower()
    if any(k in low for k in ("teleport", "reinforce", "tyrant", "kill reward", "recommended power", "boomer")):
        return True
    if "march" in low and "power" not in low and "alliance" not in low:
        return True
    return False


def is_city_modal(color: np.ndarray) -> bool:
    """Alliance city panel — not a player HQ."""
    h, w = color.shape[:2]
    panel = color[int(h * 0.28) : int(h * 0.72), int(w * 0.22) : int(w * 0.58)]
    if panel.size == 0:
        return False
    ph, pw = panel.shape[:2]
    text = read_text_from_region(panel, 0, 0, pw, ph).lower()
    markers = (
        "city was initially captured",
        "unitsrecommended",
        "capturebuff",
        "allianceresources",
        "owner [",
        "the city was",
    )
    return any(m in text for m in markers)


def is_player_hq_modal(color: np.ndarray) -> bool:
    """Gate 1: HQ detail panel with Scout action (template or OCR)."""
    if is_city_modal(color):
        return False
    panel = _stats_panel(color)
    if panel.size:
        ph, pw = panel.shape[:2]
        panel_text = read_text_from_region(panel, 0, 0, pw, ph)
        if _reject_popup_text(panel_text):
            return False

    row = _action_row(color)
    if not row.size:
        return False
    row_text = read_text_from_region(row, 0, 0, row.shape[1], row.shape[0]).lower()
    if _reject_popup_text(row_text):
        return False

    has_scout_row = "scout" in row_text or ("team" in row_text and "attack" in row_text)
    return _scout_button_visible(color) or has_scout_row
