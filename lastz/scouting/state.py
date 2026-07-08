"""Persistence for scouting session state and intel records."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from lastz.config import logs_dir, scouting_cfg
from lastz.scouting.models import ScoutIntel
from lastz.scouting.registry import already_scouted, mark_scouted_target, print_registry_summary

_INTEL_SCHEMA = 1
_STATE_SCHEMA = 2


def _cfg() -> dict:
    return scouting_cfg()


def state_file() -> Path:
    rel = _cfg().get("state_file", "logs/scouting_state.json")
    name = Path(rel).name
    return logs_dir() / name


def intel_file() -> Path:
    rel = _cfg().get("intel_file", "logs/scouting_intel.json")
    name = Path(rel).name
    return logs_dir() / name


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def load_loop_state() -> dict:
    path = state_file()
    if not path.exists():
        return {
            "schema_version": _STATE_SCHEMA,
            "phase": "home",
            "overview_pan_index": 0,
            "city_index": 0,
            "sector_index": 0,
            "scan_step_index": 0,
            "scouted": {},
        }
    try:
        raw = json.loads(path.read_text())
        if raw.get("schema_version") != _STATE_SCHEMA:
            scouted = raw.get("scouted", {})
            return {
                "schema_version": _STATE_SCHEMA,
                "phase": "home",
                "overview_pan_index": 0,
                "city_index": 0,
                "sector_index": 0,
                "scan_step_index": 0,
                "scouted": scouted,
            }
        raw.setdefault("scouted", {})
        raw.setdefault("phase", "home")
        raw.setdefault("overview_pan_index", 0)
        raw.setdefault("city_index", 0)
        raw.setdefault("sector_index", 0)
        raw.setdefault("scan_step_index", 0)
        return raw
    except Exception as e:
        print(f"[scouting] state corrupt, resetting: {e}")
        return {
            "schema_version": _STATE_SCHEMA,
            "phase": "home",
            "overview_pan_index": 0,
            "city_index": 0,
            "sector_index": 0,
            "scan_step_index": 0,
            "scouted": {},
        }


def save_loop_state(state: dict) -> None:
    state["schema_version"] = _STATE_SCHEMA
    _atomic_write(state_file(), state)


def load_intel() -> dict:
    path = intel_file()
    if not path.exists():
        return {"schema_version": _INTEL_SCHEMA, "players": {}}
    try:
        raw = json.loads(path.read_text())
        if raw.get("schema_version") != _INTEL_SCHEMA:
            return {"schema_version": _INTEL_SCHEMA, "players": {}}
        raw.setdefault("players", {})
        return raw
    except Exception as e:
        print(f"[scouting] intel corrupt, resetting: {e}")
        return {"schema_version": _INTEL_SCHEMA, "players": {}}


def save_intel(intel: dict) -> None:
    intel["schema_version"] = _INTEL_SCHEMA
    _atomic_write(intel_file(), intel)


def record_intel(intel: ScoutIntel) -> None:
    data = load_intel()
    players = data.setdefault("players", {})
    key = intel.display_name.split("]")[-1] if "]" in intel.display_name else intel.display_name
    players[key] = {
        "display_name": intel.display_name,
        "alliance": intel.alliance,
        "hq_level": intel.hq_level,
        "power": intel.power,
        "kills": intel.kills,
        "location": intel.location,
        "food": intel.food,
        "wood": intel.wood,
        "zent": intel.zent,
        "scouted_at": intel.scouted_at,
        "mail_parsed_at": intel.mail_parsed_at,
        "attack_score": intel.attack_score,
        "status": intel.status,
    }
    save_intel(data)


def filter_config_from_yaml() -> "FilterConfig":
    from lastz.scouting.models import FilterConfig

    c = _cfg()
    return FilterConfig(
        own_alliance=str(c.get("own_alliance", "")),
        alliance_blacklist=list(c.get("alliance_blacklist") or []),
        max_hq_level=int(c.get("max_hq_level", 99)),
        max_power=int(c.get("max_power", 999_999_999)),
        rescout_cooldown_sec=int(c.get("rescout_cooldown_sec", 3600)),
        scout_on_ocr_failure=bool(c.get("scout_on_ocr_failure", False)),
    )
