#!/usr/bin/env python3
"""
heliwake — one-word resume for the corrected heli + March learning loops.

Starts the learn monitor (BR heli + full March practice). The Cursor agent
should also relaunch the reviewer sub-agent when the user says: heliwake

Usage:
  python3 scripts/dev/heliwake.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lastz.config import logs_dir

LEARN = logs_dir() / "heli_learn"
STOP = LEARN / "STOP"
STATUS = LEARN / "STATUS.json"
VERDICT = LEARN / "REVIEWER_VERDICT.json"
MARCH = LEARN / "MARCH_PRACTICE.json"
GOALS = LEARN / "GOALS.json"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main() -> int:
    LEARN.mkdir(parents=True, exist_ok=True)

    if STOP.exists():
        STOP.unlink()
        print("[heliwake] removed STOP")

    # Reset paused verdict so the loop does not treat pause as done.
    if VERDICT.exists():
        try:
            v = json.loads(VERDICT.read_text(encoding="utf-8"))
        except Exception:
            v = {}
        if v.get("verdict") in ("paused", "not_ready", "flawless"):
            bak = LEARN / f"REVIEWER_VERDICT.bak_{int(time.time())}.json"
            VERDICT.rename(bak)
            print(f"[heliwake] moved old verdict → {bak.name}")

    goals = {
        "resume_phrase": "heliwake",
        "heli_flow": [
            "BR icon → Explore Treasure chat banner (correct invite)",
            "empty land → March ring → weakest idle formation → March confirm",
            "wait Explore → enter formation (4b) → prize burst → thank-you",
        ],
        "march_practice_must_prove": [
            "empty land opens Teleport/March ring",
            "March icon click opens formation modal",
            "weakest/idle (zZz) formation is selected",
            "March confirm is clicked and troops actually dispatch",
            "same formation recalled / marched back to HQ (queue slot frees)",
            "PASS only if send + recall both succeed — Escape-after-ring is NOT a pass",
        ],
        "march_recall_to_hq": {
            "why": "Full march-queue soak: send → free slot → send again",
            "required_after_practice_send": True,
            "plan": "logs/heli_learn/RECALL_HQ_PLAN.md",
            "cycle": "empty land → March → idle pick → confirm → recall to HQ",
        },
        "reviewer_flawless_requires": [
            "MARCH_PRACTICE.solid == true (streak of FULL send+recall cycles)",
            "at least one attempt_*_PASS.json result==complete",
            "no blind frac / wrong-banner / Escape-Quit junk in that pass",
        ],
        "agent_on_heliwake": [
            "Run: python3 scripts/dev/heliwake.py",
            "Relaunch reviewer sub-agent on logs/heli_learn/",
            "Ensure recall-to-HQ is implemented per RECALL_HQ_PLAN.md",
            "On FAIL: fix code, re-run heliwake — user stays out of the loop",
        ],
        "updated_at": _now(),
    }
    GOALS.write_text(json.dumps(goals, indent=2) + "\n", encoding="utf-8")

    # Invalidate prior "solid" that only tested ring-click + Escape.
    march = {
        "attempts": 0,
        "passes": 0,
        "fails": 0,
        "streak": 0,
        "best_streak": 0,
        "solid": False,
        "last_result": None,
        "mode": "full_send_and_recall",
        "note": "PASS requires idle pick + confirm send + recall to HQ",
        "updated_at": _now(),
    }
    MARCH.write_text(json.dumps(march, indent=2) + "\n", encoding="utf-8")

    STATUS.write_text(
        json.dumps(
            {
                "phase": "starting",
                "resume_phrase": "heliwake",
                "goals": goals,
                "march": march,
                "updated_at": _now(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Kill any stale loop, then start fresh.
    subprocess.run(["pkill", "-f", "scripts/dev/heli_learn_loop.py"], check=False)
    time.sleep(0.8)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    log_path = LEARN / "loop_stdout.log"
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n===== heliwake {_now()} =====\n")
        proc = subprocess.Popen(
            [sys.executable, str(_ROOT / "scripts/dev/heli_learn_loop.py"), "--poll", "1.0", "--march-every", "12.0"],
            cwd=str(_ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    print(f"[heliwake] learn loop PID={proc.pid}")
    print("[heliwake] AGENT: relaunch reviewer sub-agent watching logs/heli_learn/")
    print("[heliwake] goals →", GOALS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
