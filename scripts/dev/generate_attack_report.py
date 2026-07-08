#!/usr/bin/env python3
"""
Generate attack-priority report from scouting intel JSON (v2).

Reads logs/scouting_intel.json and ranks players with mail data.

    python3 scripts/dev/generate_attack_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from lastz.scouting.models import ScoutIntel
from lastz.scouting.scoring import compute_attack_score, compute_modal_priority
from lastz.scouting.state import intel_file, load_intel


def main() -> None:
    path = intel_file()
    if not path.exists():
        print(f"No intel file at {path}")
        print("Run the Scouting flow first, then parse scout mail (v2).")
        sys.exit(0)

    data = load_intel()
    players = data.get("players", {})
    if not players:
        print("Intel file is empty.")
        sys.exit(0)

    rows: list[tuple[float, str, ScoutIntel]] = []
    no_mail = 0

    for key, rec in players.items():
        intel = ScoutIntel(
            display_name=rec.get("display_name", key),
            alliance=rec.get("alliance"),
            hq_level=rec.get("hq_level"),
            power=rec.get("power"),
            food=rec.get("food"),
            wood=rec.get("wood"),
            zent=rec.get("zent"),
            location=rec.get("location"),
            status=rec.get("status", "dispatched"),
        )
        score = compute_attack_score(intel)
        if score is None:
            score = compute_modal_priority(intel)
        if score is None:
            no_mail += 1
            continue
        rows.append((score, key, intel))

    if not rows:
        print(f"{len(players)} player(s) in intel; {no_mail} without mail resource data yet.")
        print("v2 mail parsing will populate food/wood/zent for ranking.")
        sys.exit(0)

    rows.sort(key=lambda r: r[0], reverse=True)
    print(f"{'Rank':<5} {'Player':<22} {'Power':>8} {'Lvl':>4} {'Food':>8} {'Wood':>8} {'Zent':>8} {'Score':>6}")
    print("-" * 85)
    for rank, (score, key, intel) in enumerate(rows, 1):
        print(
            f"{rank:<5} {intel.display_name[:22]:<22} "
            f"{(intel.power or 0):>8} {(intel.hq_level or 0):>4} "
            f"{(intel.food or 0):>8} {(intel.wood or 0):>8} {(intel.zent or 0):>8} "
            f"{score:>6.2f}"
        )


if __name__ == "__main__":
    main()
