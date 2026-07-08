"""Scouted-target registry — avoid re-scouting the same HQ."""
from __future__ import annotations

import time
from datetime import datetime

from lastz.config import scouting_cfg


def _cfg() -> dict:
    return scouting_cfg()


def scouted_entries(state: dict) -> dict:
    return state.setdefault("scouted", {})


def already_scouted(player_key: str, state: dict) -> bool:
    """Return True if this target should be skipped."""
    entry = scouted_entries(state).get(player_key)
    if entry is None:
        return False

    if _cfg().get("skip_already_scouted", True):
        cooldown = int(_cfg().get("rescout_cooldown_sec", 0))
        if cooldown <= 0:
            return True
        ts = entry.get("scouted_at", entry) if isinstance(entry, dict) else float(entry)
        return (time.time() - float(ts)) < cooldown

    cooldown = int(_cfg().get("rescout_cooldown_sec", 3600))
    ts = entry.get("scouted_at", entry) if isinstance(entry, dict) else float(entry)
    return (time.time() - float(ts)) < cooldown


def mark_scouted_target(
    state: dict,
    *,
    player_key: str,
    display_name: str,
    alliance: str | None = None,
    hq_level: int | None = None,
    power: int | None = None,
    status: str = "dispatched",
) -> None:
    scouted_entries(state)[player_key] = {
        "display_name": display_name,
        "alliance": alliance,
        "hq_level": hq_level,
        "power": power,
        "status": status,
        "scouted_at": time.time(),
    }


def print_registry_summary(state: dict, *, header: str = "Scouted registry") -> None:
    entries = scouted_entries(state)
    print(f"\n[{header}] {len(entries)} target(s) on record:")
    if not entries:
        print("  (empty — no HQs scouted yet in this registry)")
        return
    rows = sorted(
        entries.items(),
        key=lambda kv: float(kv[1].get("scouted_at", 0) if isinstance(kv[1], dict) else kv[1]),
        reverse=True,
    )
    for key, rec in rows[:20]:
        if isinstance(rec, dict):
            when = datetime.fromtimestamp(rec["scouted_at"]).strftime("%Y-%m-%d %H:%M")
            print(
                f"  - {rec.get('display_name', key)} "
                f"lvl={rec.get('hq_level')} power={rec.get('power')} "
                f"status={rec.get('status')} @ {when}"
            )
        else:
            when = datetime.fromtimestamp(float(rec)).strftime("%Y-%m-%d %H:%M")
            print(f"  - {key} @ {when}")
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")
