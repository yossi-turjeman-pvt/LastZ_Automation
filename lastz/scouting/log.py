"""File + console logging for scouting runs."""
from __future__ import annotations

import time
from pathlib import Path

_log_path: Path | None = None
_log_handle = None


def open_run_log() -> Path:
    """Start a fresh run log file for this scouting session."""
    global _log_path, _log_handle
    from lastz.config import logs_dir, scouting_cfg

    rel = scouting_cfg().get("run_log_file", "logs/scouting_run.log")
    _log_path = logs_dir() / Path(rel).name
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    if _log_handle:
        _log_handle.close()
    _log_handle = open(_log_path, "w", encoding="utf-8")
    _log_handle.write(f"=== scouting run started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    _log_handle.flush()
    return _log_path


def close_run_log() -> None:
    global _log_handle
    if _log_handle:
        _log_handle.write(f"=== scouting run ended {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        _log_handle.flush()
        _log_handle.close()
        _log_handle = None


def run_log_path() -> Path | None:
    return _log_path


def slog(msg: str, *, phase: str = "scout") -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}][{phase}] {msg}"
    print(line, flush=True)
    if _log_handle:
        _log_handle.write(line + "\n")
        _log_handle.flush()
