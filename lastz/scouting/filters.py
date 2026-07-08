"""Target eligibility filters for scouting."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lastz.ocr import is_blacklisted
from lastz.scouting.models import FilterConfig, MapLabel, ModalFields, ScoutStatus

FilterStage = Literal["map", "modal"]


@dataclass
class FilterDecision:
    allowed: bool
    status: ScoutStatus | None = None
    reason: str = ""


def _normalize_tag(tag: str | None) -> str | None:
    return tag.upper() if tag else None


def evaluate_map_label(label: MapLabel, cfg: FilterConfig) -> FilterDecision:
    """Pre-filter using map label OCR before opening the HQ modal."""
    own = cfg.own_alliance.upper() if cfg.own_alliance else ""
    tag = _normalize_tag(label.alliance_tag)

    if own and tag == own:
        return FilterDecision(False, "skipped_own_alliance", f"own alliance [{tag}]")

    if is_blacklisted(tag, cfg.alliance_blacklist):
        return FilterDecision(False, "skipped_blacklist", f"blacklisted [{tag}]")

    if label.hq_level is not None and label.hq_level > cfg.max_hq_level:
        return FilterDecision(
            False,
            "skipped_level",
            f"level {label.hq_level} > max {cfg.max_hq_level}",
        )

    return FilterDecision(True)


def evaluate_modal(modal: ModalFields, cfg: FilterConfig) -> FilterDecision:
    """Authoritative filter using modal Alliance + Power before Scout click."""
    own = cfg.own_alliance.upper() if cfg.own_alliance else ""
    tag = _normalize_tag(modal.alliance_tag)

    if own and tag == own:
        return FilterDecision(False, "skipped_own_alliance", f"modal own alliance [{tag}]")

    if is_blacklisted(tag, cfg.alliance_blacklist):
        return FilterDecision(False, "skipped_blacklist", f"modal blacklisted [{tag}]")

    if modal.power is not None and modal.power > cfg.max_power:
        return FilterDecision(
            False,
            "skipped_power",
            f"power {modal.power} > max {cfg.max_power}",
        )

    if modal.power is None and not cfg.scout_on_ocr_failure:
        return FilterDecision(False, "ocr_incomplete", "Power unreadable in modal")

    return FilterDecision(True)
