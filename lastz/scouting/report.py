"""Scouting intel reports and attack-priority ranking."""
from __future__ import annotations

import time
from pathlib import Path

from lastz.config import logs_dir, scouting_cfg
from lastz.scouting.models import ScoutIntel
from lastz.scouting.scoring import compute_attack_score, compute_modal_priority
from lastz.scouting.state import intel_file, load_intel, load_loop_state


def report_path() -> Path:
    rel = scouting_cfg().get("report_file", "logs/scouting_report.md")
    return logs_dir() / Path(rel).name


def _intel_rows() -> list[tuple[float | None, ScoutIntel]]:
    data = load_intel()
    rows: list[tuple[float | None, ScoutIntel]] = []
    for key, rec in data.get("players", {}).items():
        intel = ScoutIntel(
            display_name=rec.get("display_name", key),
            alliance=rec.get("alliance"),
            hq_level=rec.get("hq_level"),
            power=rec.get("power"),
            kills=rec.get("kills"),
            location=rec.get("location"),
            food=rec.get("food"),
            wood=rec.get("wood"),
            zent=rec.get("zent"),
            scouted_at=rec.get("scouted_at", 0),
            mail_parsed_at=rec.get("mail_parsed_at"),
            attack_score=rec.get("attack_score"),
            status=rec.get("status", "dispatched"),
        )
        mail_score = compute_attack_score(intel)
        score = mail_score if mail_score is not None else compute_modal_priority(intel)
        rows.append((score, intel))
    rows.sort(key=lambda r: (r[0] is not None, r[0] or 0), reverse=True)
    return rows


def write_scouting_report() -> Path:
    """Write markdown attack-priority report from scouting intel."""
    rows = _intel_rows()
    state = load_loop_state()
    scouted_registry = state.get("scouted", {})
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Scouting Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Intel records: {len(rows)} | Registry: {len(scouted_registry)}",
        "",
        "## Best attack targets",
        "",
        "| Rank | Player | Alliance | Lvl | Power | Location | Score | Notes |",
        "|------|--------|----------|-----|-------|----------|-------|-------|",
    ]

    if not rows:
        lines.append("| — | *(no scouts dispatched yet)* | | | | | | |")
    else:
        for rank, (score, intel) in enumerate(rows[:25], 1):
            notes = []
            if intel.food or intel.wood or intel.zent:
                notes.append(f"res F{intel.food or 0} W{intel.wood or 0} Z{intel.zent or 0}")
            elif intel.status == "dispatched":
                notes.append("awaiting mail")
            score_s = f"{score:.0f}" if score is not None else "—"
            lines += [
                f"| {rank} | {intel.display_name} | {intel.alliance or '—'} | "
                f"{intel.hq_level or '—'} | {intel.power or '—'} | "
                f"{intel.location or '—'} | {score_s} | {'; '.join(notes) or '—'} |",
            ]

    lines += [
        "",
        "## All scouted targets (registry)",
        "",
    ]
    if not scouted_registry:
        lines.append("*(empty)*")
    else:
        for key, rec in scouted_registry.items():
            lines.append(
                f"- **{rec.get('display_name', key)}** "
                f"[{rec.get('alliance', '?')}] power={rec.get('power', '?')} "
                f"lvl={rec.get('hq_level', '?')} status={rec.get('status', '?')}"
            )

    lines += [
        "",
        "---",
        f"Full intel JSON: `{intel_file()}`",
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def print_scouting_report() -> None:
    """Print console summary and write markdown report."""
    rows = _intel_rows()
    path = write_scouting_report()

    print("\n" + "=" * 72)
    print("SCOUTING ATTACK REPORT")
    print("=" * 72)
    if not rows:
        print("  No intel yet — scouts will populate this as the loop runs.")
    else:
        print(f"{'#':<4} {'Player':<24} {'Alliance':<8} {'Lvl':>4} {'Power':>10} {'Score':>6} {'Location'}")
        print("-" * 72)
        for rank, (score, intel) in enumerate(rows[:15], 1):
            loc = intel.location or ""
            score_s = f"{score:.0f}" if score is not None else "—"
            print(
                f"{rank:<4} {intel.display_name[:24]:<24} "
                f"{(intel.alliance or '—')[:8]:<8} "
                f"{(intel.hq_level or 0):>4} {(intel.power or 0):>10} "
                f"{score_s:>6} {loc}"
            )
    print(f"\nReport saved: {path}")
    print("=" * 72)
