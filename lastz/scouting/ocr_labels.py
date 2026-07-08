"""OCR helpers for map labels and HQ modal fields."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from lastz.ocr import (
    parse_alliance_tag,
    parse_map_hq_label,
    parse_map_location,
    parse_power_value,
    read_text_from_region,
)
from lastz.scouting.models import MapLabel, ModalFields
from lastz.screen import scale_capture_offset


def _crop_from_center(
    color: np.ndarray,
    center_x: float,
    center_y: float,
    offset: list[int],
) -> tuple[int, int, int, int]:
    """Return phys_x, phys_y, phys_w, phys_h from center + [dx, dy, w, h] offset."""
    dx, dy, w, h = [float(v) for v in offset]
    sdx, sdy = scale_capture_offset(dx, dy)
    sw, sh = scale_capture_offset(w, h)
    phys_x = int(center_x + sdx - sw / 2)
    phys_y = int(center_y + sdy - sh / 2)
    return phys_x, phys_y, int(sw), int(sh)


def ocr_map_label_at(
    color: np.ndarray,
    center_x: float,
    center_y: float,
    crop_offset: list[int],
    *,
    debug_dir: Path | None = None,
    debug_prefix: str = "map_label",
) -> MapLabel:
    """OCR the name + level label above/near an enemy HQ icon."""
    px, py, pw, ph = _crop_from_center(color, center_x, center_y, crop_offset)
    raw = read_text_from_region(color, px, py, pw, ph, debug_dir=debug_dir, debug_prefix=debug_prefix)
    parsed = parse_map_hq_label(raw)
    return MapLabel(
        alliance_tag=parsed.get("alliance_tag"),
        player_name=parsed.get("player_name"),
        hq_level=parsed.get("hq_level"),
        raw_text=raw,
    )


def ocr_modal_header(
    color: np.ndarray,
    header_crop: list[int],
    *,
    debug_dir: Path | None = None,
) -> MapLabel:
    """OCR modal title line e.g. [Wrck]PlayerName."""
    if not header_crop or len(header_crop) != 4 or not all(header_crop):
        return MapLabel()
    hx, hy, hw, hh = [int(v) for v in header_crop]
    raw = read_text_from_region(
        color, hx, hy, hw, hh, debug_dir=debug_dir, debug_prefix="modal_header"
    )
    parsed = parse_map_hq_label(raw)
    return MapLabel(
        alliance_tag=parsed.get("alliance_tag"),
        player_name=parsed.get("player_name"),
        hq_level=parsed.get("hq_level"),
        raw_text=raw,
    )


def ocr_modal_fields(
    color: np.ndarray,
    alliance_crop: list[int],
    power_crop: list[int],
    *,
    debug_dir: Path | None = None,
) -> ModalFields:
    """
    OCR Alliance and Power rows from the open HQ detail modal.

    Crops are absolute physical pixels [x, y, w, h] when all values > 0,
    otherwise skipped (returns empty fields).
    """
    alliance_raw = ""
    power_raw = ""
    alliance_tag = None
    power = None

    if alliance_crop and len(alliance_crop) == 4 and all(alliance_crop):
        ax, ay, aw, ah = [int(v) for v in alliance_crop]
        alliance_raw = read_text_from_region(
            color, ax, ay, aw, ah, debug_dir=debug_dir, debug_prefix="modal_alliance"
        )
        alliance_tag = parse_alliance_tag(alliance_raw)

    if power_crop and len(power_crop) == 4 and all(power_crop):
        px, py, pw, ph = [int(v) for v in power_crop]
        power_raw = read_text_from_region(
            color, px, py, pw, ph, debug_dir=debug_dir, debug_prefix="modal_power"
        )
        power = parse_power_value(power_raw)

    panel_raw = ""
    if power is None or (power is not None and power < 1000):
        h, w = color.shape[:2]
        panel = color[int(h * 0.30) : int(h * 0.62), int(w * 0.26) : int(w * 0.54)]
        if panel.size:
            ph, pw = panel.shape[:2]
            panel_raw = read_text_from_region(
                panel, 0, 0, pw, ph, debug_dir=debug_dir, debug_prefix="modal_panel"
            )
            panel_power = parse_power_value(panel_raw)
            if panel_power and (power is None or panel_power > power):
                power = panel_power
                power_raw = panel_raw
            if not alliance_tag:
                alliance_tag = parse_alliance_tag(panel_raw)
                alliance_raw = panel_raw

    map_location = parse_map_location(panel_raw or power_raw or alliance_raw)

    return ModalFields(
        alliance_tag=alliance_tag,
        power=power,
        alliance_raw=alliance_raw,
        power_raw=power_raw,
        panel_raw=panel_raw,
        map_location=map_location,
    )
