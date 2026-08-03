"""
Motivation stats — monthly loot ledger, runtime, donations, claim counts.

Persists to data/motivation_stats.json (configurable). Local only; gitignored.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from lastz.config import PROJECT_ROOT, load_config

_lock = threading.Lock()

# In-process this-run accumulator (cleared at run start).
_run: dict[str, Any] | None = None
_run_t0: float | None = None


def stats_enabled() -> bool:
    cfg = load_config().get("stats") or {}
    return bool(cfg.get("enabled", True))


def stats_path() -> Path:
    cfg = load_config().get("stats") or {}
    rel = cfg.get("path") or "data/motivation_stats.json"
    return PROJECT_ROOT / rel


def _month_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%Y-%m")


def _empty_month() -> dict[str, Any]:
    return {
        "runtime_sec": 0.0,
        "donations": 0,
        "help_clicks": 0,
        "loot_by_source": {
            "alliance_gifts": {},
            "battlefield": {},
            "drone": {},
            "trucks": {},
        },
        "loot_total": {},
        "claims": {
            "common_claim_all": 0,
            "rare_claim_all": 0,
            "common_individual": 0,
            "rare_individual": 0,
            "battlefield_claim_all": 0,
            "drone_collect": 0,
            "trucks_claimed": 0,
            "trucks_sent": 0,
        },
        "history": [],
    }


def _empty_run() -> dict[str, Any]:
    return {
        "loot_by_source": {
            "alliance_gifts": {},
            "battlefield": {},
            "drone": {},
            "trucks": {},
        },
        "loot_total": {},
        "donations": 0,
        "claims": {},
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }


def _load() -> dict[str, Any]:
    path = stats_path()
    if not path.exists():
        return {"months": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"months": {}}
    if not isinstance(data, dict):
        return {"months": {}}
    data.setdefault("months", {})
    return data


def _save(data: dict[str, Any]) -> None:
    path = stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def _month_bucket(data: dict[str, Any], key: str | None = None) -> dict[str, Any]:
    key = key or _month_key()
    months = data.setdefault("months", {})
    if key not in months:
        months[key] = _empty_month()
    bucket = months[key]
    # Soft-migrate missing keys
    base = _empty_month()
    for k, v in base.items():
        if k not in bucket:
            bucket[k] = v if not isinstance(v, dict) else dict(v)
        elif isinstance(v, dict):
            for sk, sv in v.items():
                bucket[k].setdefault(sk, sv if not isinstance(sv, dict) else dict(sv))
    return bucket


def _add_amounts(dest: dict[str, float], items: dict[str, float]) -> None:
    for k, v in items.items():
        if v is None:
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            continue
        if n == 0:
            continue
        dest[k] = float(dest.get(k, 0)) + n


def begin_run_stats() -> None:
    """Start this-run accumulator (call at flow start)."""
    global _run, _run_t0
    if not stats_enabled():
        return
    _run = _empty_run()
    _run_t0 = time.monotonic()


def end_run_stats(*, print_summary: bool = True) -> None:
    """Record runtime for this run and optionally print summary."""
    global _run, _run_t0
    if not stats_enabled():
        return
    elapsed = 0.0
    if _run_t0 is not None:
        elapsed = max(0.0, time.monotonic() - _run_t0)
    if elapsed > 0:
        record_runtime(elapsed)
    if print_summary:
        print(format_summary(include_run=True))
    # Append compact history entry
    if _run and (_run.get("loot_total") or _run.get("donations") or _run.get("claims")):
        with _lock:
            data = _load()
            bucket = _month_bucket(data)
            hist = bucket.setdefault("history", [])
            hist.append(
                {
                    "at": datetime.now().isoformat(timespec="seconds"),
                    "runtime_sec": round(elapsed, 1),
                    "donations": int(_run.get("donations") or 0),
                    "loot_total": dict(_run.get("loot_total") or {}),
                    "claims": dict(_run.get("claims") or {}),
                }
            )
            # Cap history
            if len(hist) > 50:
                del hist[:-50]
            _save(data)
    _run = None
    _run_t0 = None


def record_runtime(seconds: float) -> None:
    if not stats_enabled() or seconds <= 0:
        return
    with _lock:
        data = _load()
        bucket = _month_bucket(data)
        bucket["runtime_sec"] = float(bucket.get("runtime_sec") or 0) + float(seconds)
        _save(data)


def record_donations(n: int) -> None:
    if not stats_enabled() or n <= 0:
        return
    with _lock:
        data = _load()
        bucket = _month_bucket(data)
        bucket["donations"] = int(bucket.get("donations") or 0) + int(n)
        _save(data)
    if _run is not None:
        _run["donations"] = int(_run.get("donations") or 0) + int(n)


def record_help_clicks(n: int = 1) -> None:
    if not stats_enabled() or n <= 0:
        return
    with _lock:
        data = _load()
        bucket = _month_bucket(data)
        bucket["help_clicks"] = int(bucket.get("help_clicks") or 0) + int(n)
        _save(data)


def record_claim(claim_key: str, n: int = 1) -> None:
    if not stats_enabled() or n <= 0 or not claim_key:
        return
    with _lock:
        data = _load()
        bucket = _month_bucket(data)
        claims = bucket.setdefault("claims", {})
        claims[claim_key] = int(claims.get(claim_key) or 0) + int(n)
        _save(data)
    if _run is not None:
        rc = _run.setdefault("claims", {})
        rc[claim_key] = int(rc.get(claim_key) or 0) + int(n)


def record_loot(source: str, items: dict[str, float]) -> None:
    """
    Add itemized loot for a source.

    source: alliance_gifts | battlefield | drone | trucks
    items: { item_key: amount } — amounts are material totals or stack counts.
    """
    if not stats_enabled() or not items:
        return
    cleaned: dict[str, float] = {}
    for k, v in items.items():
        key = str(k).strip()
        if not key:
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            continue
        if n == 0:
            continue
        cleaned[key] = n
    if not cleaned:
        return
    with _lock:
        data = _load()
        bucket = _month_bucket(data)
        by_src = bucket.setdefault("loot_by_source", {})
        src_bucket = by_src.setdefault(source, {})
        _add_amounts(src_bucket, cleaned)
        total = bucket.setdefault("loot_total", {})
        _add_amounts(total, cleaned)
        _save(data)
    if _run is not None:
        run_src = _run.setdefault("loot_by_source", {}).setdefault(source, {})
        _add_amounts(run_src, cleaned)
        run_total = _run.setdefault("loot_total", {})
        _add_amounts(run_total, cleaned)


def month_summary(month: str | None = None) -> dict[str, Any]:
    with _lock:
        data = _load()
        key = month or _month_key()
        return dict(_month_bucket(data, key))


def format_qty(n: float) -> str:
    """Human-readable quantity for display."""
    abs_n = abs(n)
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    if abs_n >= 1_000:
        return f"{n / 1_000:.2f}K".rstrip("0").rstrip(".")
    if float(n).is_integer():
        return str(int(n))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _format_loot_lines(loot: dict[str, float], indent: str = "  ") -> list[str]:
    if not loot:
        return [f"{indent}(none)"]
    lines = []
    for key in sorted(loot.keys(), key=lambda k: (-float(loot[k]), k)):
        lines.append(f"{indent}{key}: {format_qty(float(loot[key]))}")
    return lines


def format_summary(*, include_run: bool = True, month: str | None = None) -> str:
    """Multi-line terminal summary for this run (if any) + current month."""
    key = month or _month_key()
    bucket = month_summary(key)
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("  MOTIVATION STATS")
    lines.append("=" * 60)

    if include_run and _run is not None:
        lines.append("This run:")
        if _run.get("donations"):
            lines.append(f"  donations: {_run['donations']}")
        claims = _run.get("claims") or {}
        if claims:
            claim_bits = ", ".join(f"{k}={v}" for k, v in sorted(claims.items()))
            lines.append(f"  claims: {claim_bits}")
        lines.append("  loot:")
        lines.extend(_format_loot_lines(_run.get("loot_total") or {}))
        by_src = _run.get("loot_by_source") or {}
        for src in ("alliance_gifts", "battlefield", "drone"):
            src_loot = by_src.get(src) or {}
            if src_loot:
                lines.append(f"  [{src}]")
                lines.extend(_format_loot_lines(src_loot, indent="    "))
        lines.append("-" * 60)

    runtime_h = float(bucket.get("runtime_sec") or 0) / 3600.0
    lines.append(f"Month {key}:")
    lines.append(f"  runtime: {runtime_h:.2f} h")
    lines.append(f"  donations: {int(bucket.get('donations') or 0)}")
    lines.append(f"  help clicks: {int(bucket.get('help_clicks') or 0)}")
    claims = bucket.get("claims") or {}
    if any(int(claims.get(k) or 0) for k in claims):
        claim_bits = ", ".join(
            f"{k}={int(v)}" for k, v in sorted(claims.items()) if int(v or 0)
        )
        lines.append(f"  claims: {claim_bits}")
    lines.append("  loot total:")
    lines.extend(_format_loot_lines(bucket.get("loot_total") or {}))
    by_src = bucket.get("loot_by_source") or {}
    for src in ("alliance_gifts", "battlefield", "drone", "trucks"):
        src_loot = by_src.get(src) or {}
        if src_loot:
            lines.append(f"  [{src}]")
            lines.extend(_format_loot_lines(src_loot, indent="    "))
    lines.append("=" * 60)
    return "\n".join(lines)


def print_month_stats() -> None:
    print(format_summary(include_run=False))
