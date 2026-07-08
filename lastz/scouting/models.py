"""Data models for scouting automation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ScoutStatus = Literal[
    "dispatched",
    "skipped_own_alliance",
    "skipped_blacklist",
    "skipped_level",
    "skipped_power",
    "skipped_cooldown",
    "ocr_incomplete",
    "intel_complete",
    "dry_run_would_scout",
]


@dataclass
class FilterConfig:
    own_alliance: str
    alliance_blacklist: list[str]
    max_hq_level: int
    max_power: int
    rescout_cooldown_sec: int = 3600
    scout_on_ocr_failure: bool = False


@dataclass
class MapLabel:
    alliance_tag: str | None = None
    player_name: str | None = None
    hq_level: int | None = None
    raw_text: str = ""

    @property
    def display_name(self) -> str:
        if self.alliance_tag and self.player_name:
            return f"[{self.alliance_tag}]{self.player_name}"
        return self.player_name or self.raw_text or "unknown"

    @property
    def key(self) -> str:
        return self.player_name or self.display_name


@dataclass
class ModalFields:
    alliance_tag: str | None = None
    power: int | None = None
    kills: int | None = None
    alliance_raw: str = ""
    power_raw: str = ""
    panel_raw: str = ""
    map_location: str | None = None


@dataclass
class ScoutTarget:
    phys_x: float
    phys_y: float
    confidence: float
    distance_px: float = 0.0


@dataclass
class ScoutIntel:
    display_name: str
    alliance: str | None = None
    hq_level: int | None = None
    power: int | None = None
    kills: int | None = None
    location: str | None = None
    food: int | None = None
    wood: int | None = None
    zent: int | None = None
    scouted_at: float = 0.0
    mail_parsed_at: float | None = None
    attack_score: float | None = None
    status: ScoutStatus = "dispatched"


@dataclass
class SessionStats:
    dispatched: int = 0
    skipped_own_alliance: int = 0
    skipped_blacklist: int = 0
    skipped_level: int = 0
    skipped_power: int = 0
    skipped_cooldown: int = 0
    ocr_incomplete: int = 0
    dry_run_would_scout: int = 0

    def record(self, status: ScoutStatus) -> None:
        attr = status
        if hasattr(self, attr):
            setattr(self, attr, getattr(self, attr) + 1)
