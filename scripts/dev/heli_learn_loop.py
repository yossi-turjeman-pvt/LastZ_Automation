#!/usr/bin/env python3
"""
TEMP heli learn loop — monitor BR heli + FULL March practice while idle.

March practice PASS requires: empty land → March ring → idle/weakest
formation → March confirm (actual send). Escape-after-ring is NOT a pass.

Resume: python3 scripts/dev/heliwake.py  (user says: heliwake)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lastz.config import logs_dir
from lastz.flows.base import dismiss_quit_tips_if_present
from lastz.flows.helicopter import (
    _annotate,
    _click_frac,
    _click_match,
    _find_idle_formation_row,
    _find_march_confirm_ocr,
    _find_march_ring,
    _match_dict,
    _save_raw,
    _thr,
    find_br_heli,
    helicopter_cfg,
    heli_log,
    poll_br_heli_once,
    run_helicopter_flow,
)
from lastz.flows.ui_bands import BAND_HELI_FORMATIONS
from lastz.debug_match import in_band
from lastz.heli_priority import clear_heli, heli_pending, signal_heli
from lastz.input import (
    click,
    ensure_game_running,
    focus_game,
    is_game_running,
    press_escape,
)
from lastz.screen import capture_both, physical_to_logical
from lastz.vision import ensure_template_scale, find_all_templates, find_template

LEARN_DIR = logs_dir() / "heli_learn"
STATUS_PATH = LEARN_DIR / "STATUS.json"
VERDICT_PATH = LEARN_DIR / "REVIEWER_VERDICT.json"
MARCH_STATS_PATH = LEARN_DIR / "MARCH_PRACTICE.json"
GOALS_PATH = LEARN_DIR / "GOALS.json"
STOP_PATH = LEARN_DIR / "STOP"

# Consecutive FULL march sends (ring → idle formation → confirm) before solid.
MARCH_STREAK_TARGET = 5


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_status(**payload) -> None:
    LEARN_DIR.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = _now()
    if GOALS_PATH.exists():
        try:
            payload.setdefault("goals", json.loads(GOALS_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    STATUS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[heli_learn] status → {STATUS_PATH}")


def _load_march_stats() -> dict:
    if MARCH_STATS_PATH.exists():
        try:
            return json.loads(MARCH_STATS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "attempts": 0,
        "passes": 0,
        "fails": 0,
        "streak": 0,
        "best_streak": 0,
        "solid": False,
        "last_result": None,
        "mode": "full_send",
    }


def _save_march_stats(stats: dict) -> None:
    LEARN_DIR.mkdir(parents=True, exist_ok=True)
    stats["updated_at"] = _now()
    stats["mode"] = "full_send"
    MARCH_STATS_PATH.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")


def _tail_heli_log(n: int = 80) -> list[str]:
    p = logs_dir() / "heli.log"
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]


def _dismiss_junk() -> None:
    """Clear Quit Tips only — NEVER blind Escape (opens Quit Tips)."""
    if dismiss_quit_tips_if_present():
        heli_log("[heli_learn] dismissed Quit Tips via Cancel")
    else:
        heli_log("[heli_learn] no Quit Tips present — skipped Escape cleanup")


def _abort_formation_safely() -> None:
    """Emergency close only — never counts as a March practice PASS."""
    press_escape()
    time.sleep(0.5)
    dismiss_quit_tips_if_present()
    time.sleep(0.3)


def practice_march_once() -> bool:
    """
    FULL March path (required for PASS / solid):
      empty land → March ring → weakest idle formation → March confirm (send)

    Escape-after-ring alone is NOT success. Yields immediately if BR heli appears.
    """
    dismiss_quit_tips_if_present()
    focus_game()
    cfg = helicopter_cfg()
    color0, gray0 = capture_both()
    ensure_template_scale(gray0)

    if find_br_heli(gray0, color0) is not None or heli_pending():
        heli_log("[march_practice] BR heli visible — yielding to heli flow")
        return False

    base_dx, base_dy = cfg["empty_land_offset_frac"]
    offsets = [
        (base_dx, base_dy),
        (0.0, 0.04),
        (-0.06, 0.02),
        (0.06, 0.06),
        (-0.03, -0.04),
        (0.04, -0.02),
    ]

    hit = None
    color = color0
    gray = gray0
    for i, (dx, dy) in enumerate(offsets):
        if find_br_heli() is not None or heli_pending():
            heli_log("[march_practice] BR appeared mid-practice — yielding")
            return False
        color0, _ = capture_both()
        fx, fy = 0.50 + dx, 0.52 + dy
        _save_raw(color0, f"march_practice_before_empty_{i}")
        _click_frac(fx, fy, f"march_practice_empty_{i}", color0)
        time.sleep(1.0)
        color, gray = capture_both()
        _save_raw(color, f"march_practice_after_empty_{i}")
        hit = _find_march_ring(gray, color)
        if hit is not None:
            h, w = gray.shape[:2]
            if abs(hit.phys_x / w - fx) < 0.18 and abs(hit.phys_y / h - fy) < 0.22:
                heli_log(
                    f"[march_practice] ring after offset[{i}] "
                    f"frac=({fx:.2f},{fy:.2f}) conf={getattr(hit,'confidence',0):.3f}"
                )
                break
            heli_log(
                f"[march_practice] rejecting far match offset[{i}] "
                f"hit=({hit.phys_x/w:.2f},{hit.phys_y/h:.2f}) click=({fx:.2f},{fy:.2f})"
            )
            hit = None
        else:
            heli_log(f"[march_practice] no ring after offset[{i}] ({fx:.2f},{fy:.2f})")

    if hit is None:
        soft = find_all_templates(gray, "heli_march.png", 0.40)
        _annotate(
            color,
            "march_practice_MISS_ring",
            [_match_dict(x, "heli_march", ok=False) for x in soft[:8]],
        )
        heli_log("[march_practice] FAIL: March ring not found")
        _abort_formation_safely()
        return False

    _annotate(color, "march_practice_ring_HIT", [_match_dict(hit, "heli_march")])
    _click_match(hit, "march_practice_march", "heli_march.png")
    heli_log("[march_practice] clicked March ring — waiting formation modal")
    time.sleep(1.6)

    if find_br_heli() is not None or heli_pending():
        heli_log("[march_practice] BR during formation — aborting practice send")
        _abort_formation_safely()
        return False

    color, gray = capture_both()
    _save_raw(color, "march_practice_formation_panel")
    h, w = gray.shape[:2]

    # Weakest/idle formation: template in band, else OCR idle row, else keep default.
    thr_z = _thr("heli_zzz", 0.60)
    zs_all = find_all_templates(gray, "heli_zzz.png", max(0.45, thr_z - 0.15))
    zs = [m for m in zs_all if in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_FORMATIONS)]
    picked = False
    if zs:
        zs.sort(key=lambda m: m.phys_y)
        pick = zs[-1]
        _annotate(color, "march_practice_zzz_PICK", [_match_dict(pick, "zzz")])
        _click_match(pick, "march_practice_zzz", "heli_zzz.png")
        heli_log(f"[march_practice] picked bottom idle zZz conf={pick.confidence:.3f}")
        picked = True
        time.sleep(0.7)
    else:
        idle = _find_idle_formation_row(color)
        if idle is not None:
            cx, cy = idle
            lx, ly = physical_to_logical(cx, cy)
            click(lx, ly)
            heli_log(f"[march_practice] picked idle via OCR phys=({cx:.0f},{cy:.0f})")
            picked = True
            time.sleep(0.7)
        else:
            heli_log("[march_practice] WARN: no idle row found — using game default selection")

    color, gray = capture_both()
    _save_raw(color, "march_practice_before_confirm")
    thr_c = _thr("heli_march_confirm", 0.60)
    m2 = find_template(gray, "heli_march_confirm.png", thr_c)
    if m2 is None:
        for _ in range(3):
            time.sleep(0.25)
            color, gray = capture_both()
            m2 = find_template(gray, "heli_march_confirm.png", thr_c)
            if m2 is not None:
                break

    if m2 is not None:
        _annotate(color, "march_practice_confirm_HIT", [_match_dict(m2, "confirm")])
        _click_match(m2, "march_practice_confirm", "heli_march_confirm.png")
        heli_log(f"[march_practice] clicked March confirm conf={m2.confidence:.3f}")
    else:
        ocr = _find_march_confirm_ocr(color)
        if ocr is None:
            _annotate(color, "march_practice_confirm_MISS", [])
            heli_log("[march_practice] FAIL: March confirm not found — aborting (no send)")
            _abort_formation_safely()
            return False
        cx, cy = ocr
        lx, ly = physical_to_logical(cx, cy)
        click(lx, ly)
        heli_log(f"[march_practice] clicked March confirm via OCR phys=({cx:.0f},{cy:.0f})")

    time.sleep(1.8)
    after, _ = capture_both()
    _save_raw(after, "march_practice_after_send")
    # Success = we completed confirm click. Panel should be gone / troops en route.
    if _find_march_confirm_ocr(after) is not None:
        heli_log("[march_practice] FAIL: confirm still visible after click")
        _abort_formation_safely()
        return False

    heli_log(
        f"[march_practice] PASS full send (idle_picked={picked})"
    )
    dismiss_quit_tips_if_present()
    return True


def _attempt(attempt: int) -> str:
    heli_log("=" * 50)
    heli_log(f"HELI LEARN attempt={attempt}")
    dismiss_quit_tips_if_present()
    clear_heli()
    signal_heli()
    t0 = time.time()
    result = run_helicopter_flow(source="learn")
    elapsed = time.time() - t0
    ok = result == "complete"
    report = {
        "phase": "result",
        "attempt": attempt,
        "result": result,
        "ok": ok,
        "elapsed_sec": round(elapsed, 1),
        "heli_log_tail": _tail_heli_log(100),
    }
    out = LEARN_DIR / f"attempt_{attempt:03d}_{'PASS' if ok else 'FAIL'}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_status(**report, report_path=str(out))
    heli_log(f"HELI LEARN result={result} elapsed={elapsed:.1f}s → {out}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll", type=float, default=1.0, help="BR poll seconds")
    ap.add_argument("--once", action="store_true", help="Exit after first heli attempt")
    ap.add_argument("--cooldown", type=float, default=45.0)
    ap.add_argument(
        "--march-every",
        type=float,
        default=8.0,
        help="Seconds between March practice tries while watching",
    )
    ap.add_argument(
        "--no-march-practice",
        action="store_true",
        help="Disable idle March practice",
    )
    args = ap.parse_args()

    LEARN_DIR.mkdir(parents=True, exist_ok=True)
    attempt = 0
    march_stats = _load_march_stats()
    last_march_practice = 0.0
    _write_status(phase="starting", attempt=0, ok=None, result=None, march=march_stats)

    try:
        ensure_game_running()
        focus_game()
        dismiss_quit_tips_if_present()
    except Exception as e:
        _write_status(phase="error", error=str(e), ok=False)
        return 2

    heli_log("HELI LEARN LOOP STARTED (with March practice)")
    print("[heli_learn] watching BR + practicing March while idle…")
    _write_status(phase="watching", attempt=0, ok=None, result=None, march=march_stats)

    while True:
        if STOP_PATH.exists():
            _write_status(phase="stopped", reason="STOP file", attempt=attempt, march=march_stats)
            print("[heli_learn] STOP file present — exiting")
            return 0
        if VERDICT_PATH.exists():
            try:
                v = json.loads(VERDICT_PATH.read_text(encoding="utf-8"))
            except Exception:
                v = {}
            if v.get("verdict") == "flawless":
                _write_status(
                    phase="done",
                    attempt=attempt,
                    ok=True,
                    result="reviewer:flawless",
                    march=march_stats,
                )
                print("[heli_learn] REVIEWER_VERDICT=flawless — exiting")
                return 0

        if not is_game_running():
            time.sleep(2.0)
            continue

        try:
            color, gray = capture_both()
            ensure_template_scale(gray)
            br = find_br_heli(gray, color)
            pending = heli_pending()
            if br or pending or poll_br_heli_once():
                attempt += 1
                print(f"[heli_learn] HELI DETECTED — attempt {attempt}")
                _write_status(
                    phase="running",
                    attempt=attempt,
                    ok=None,
                    result=None,
                    br=bool(br),
                    march=march_stats,
                )
                result = _attempt(attempt)
                if result != "complete":
                    _dismiss_junk()
                    _write_status(
                        phase="failed_waiting_fix",
                        attempt=attempt,
                        ok=False,
                        result=result,
                        march=march_stats,
                        note="Parent agent must inspect fail report, fix, restart loop",
                    )
                    print(f"[heli_learn] FAIL ({result}) — stopping for learn/fix")
                    return 1
                print(f"[heli_learn] PASS attempt {attempt}")
                if args.once:
                    return 0
                time.sleep(args.cooldown)
                _write_status(
                    phase="watching",
                    attempt=attempt,
                    ok=True,
                    result="complete",
                    march=march_stats,
                )
                last_march_practice = time.time()
                continue

            # Idle: practice March ring when due (yields immediately if BR appears).
            now = time.time()
            if (
                not args.no_march_practice
                and not march_stats.get("solid")
                and (now - last_march_practice) >= args.march_every
            ):
                last_march_practice = now
                _write_status(
                    phase="march_practice",
                    attempt=attempt,
                    ok=None,
                    result=None,
                    march=march_stats,
                )
                print("[heli_learn] March practice tick…")
                ok = practice_march_once()
                march_stats["attempts"] = int(march_stats.get("attempts", 0)) + 1
                if ok:
                    march_stats["passes"] = int(march_stats.get("passes", 0)) + 1
                    march_stats["streak"] = int(march_stats.get("streak", 0)) + 1
                    march_stats["best_streak"] = max(
                        int(march_stats.get("best_streak", 0)),
                        int(march_stats["streak"]),
                    )
                    march_stats["last_result"] = "pass"
                    if march_stats["streak"] >= MARCH_STREAK_TARGET:
                        march_stats["solid"] = True
                        heli_log(
                            f"[march_practice] SOLID — full-send streak={march_stats['streak']}"
                        )
                        print("[heli_learn] March practice SOLID (full send path)")
                else:
                    # Only count as fail if BR did not interrupt.
                    if not heli_pending() and find_br_heli() is None:
                        march_stats["fails"] = int(march_stats.get("fails", 0)) + 1
                        march_stats["streak"] = 0
                        march_stats["last_result"] = "fail"
                _save_march_stats(march_stats)
                _write_status(
                    phase="watching",
                    attempt=attempt,
                    ok=None,
                    result=None,
                    march=march_stats,
                )
                # Re-check BR immediately after practice.
                continue

            time.sleep(args.poll)
        except KeyboardInterrupt:
            _write_status(
                phase="stopped",
                reason="KeyboardInterrupt",
                attempt=attempt,
                march=march_stats,
            )
            return 0
        except Exception as e:
            heli_log(f"HELI LEARN ERROR: {e}")
            _write_status(
                phase="error",
                attempt=attempt,
                ok=False,
                error=str(e),
                march=march_stats,
            )
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
