"""
Flow 6b — Scout Mail Intel (v2 stub).

Future automation: open Mail, parse scout result messages for location
and resource quantities (food, wood, zent), update scouting_intel.json,
and feed the attack-priority report.

Not implemented in v1 — signatures and docstrings only.
"""
from __future__ import annotations

from typing import Any

from lastz.scouting.models import ScoutIntel


def run_scout_mail_parse_flow() -> str:
    """
    Open Mail, find unread scout reports, OCR location + resources, update intel.

    Returns a human-readable status string.
    """
    return "Scout mail parsing not implemented yet (v2). Run generate_attack_report.py after manual intel."


def parse_scout_mail_screen(screen: Any) -> ScoutIntel | None:
    """
    Parse a single scout mail message from a screenshot.

    Expected fields: location (X/Y), food, wood, zent quantities.
    """
    return None
