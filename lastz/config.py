"""
Loads config.yaml and exposes typed accessors.

PROJECT_ROOT is resolved relative to this file so the project works
on any machine without hardcoded absolute paths.
"""
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_config: dict | None = None


def load_config() -> dict:
    global _config
    if _config is None:
        cfg_path = PROJECT_ROOT / "config.yaml"
        with open(cfg_path, "r") as f:
            _config = yaml.safe_load(f)
    return _config


def reload_config() -> dict:
    """Force re-read config.yaml (clears in-process cache)."""
    global _config
    _config = None
    return load_config()


def templates_dir() -> Path:
    cfg = load_config()
    return PROJECT_ROOT / cfg["paths"]["templates_dir"]


def logs_dir() -> Path:
    cfg = load_config()
    return PROJECT_ROOT / cfg["paths"]["logs_dir"]


def game_process() -> str:
    return load_config()["game"]["process_name"]


def threshold(name: str) -> float:
    return float(load_config()["thresholds"][name])


def coord_offset(name: str) -> tuple[float, float]:
    """Return a 2-value coordinate tuple from config coordinates:."""
    values = load_config()["coordinates"][name]
    return float(values[0]), float(values[1])


def window_offset_click(name: str = "dismiss_outside") -> tuple[float, float]:
    """
    Click point inside the game window for overlay dismiss.

    Prefers `dismiss_outside_frac` [fx, fy] as fractions of window width/height.
    Falls back to legacy pixel `dismiss_outside` offset from window top-left.
    """
    from lastz.screen import get_game_window_bounds

    wx, wy, ww, wh = get_game_window_bounds()
    coords = load_config().get("coordinates", {})

    frac = coords.get("dismiss_outside_frac")
    if frac is not None and len(frac) >= 2:
        fx, fy = float(frac[0]), float(frac[1])
        return wx + fx * ww, wy + fy * wh

    # Legacy pixel offset (absolute logical px from window origin)
    legacy = coords.get(name) or coords.get("dismiss_outside")
    if legacy is not None and len(legacy) >= 2:
        return wx + float(legacy[0]), wy + float(legacy[1])

    # Safe default: upper-left empty map area
    return wx + 0.06 * ww, wy + 0.28 * wh


def watcher_cfg() -> dict:
    return load_config()["watcher"]


def trucks_cfg() -> dict:
    """Trucks flow toggles; defaults keep flow on and orange-only."""
    cfg = load_config().get("trucks") or {}
    return {
        "include_trucks_flow": bool(cfg.get("include_trucks_flow", True)),
        "allow_purple_trucks": bool(cfg.get("allow_purple_trucks", False)),
        "max_refreshes": int(cfg.get("max_refreshes", 15)),
        # Open on badge always; also every Nth gifts run (send without badge).
        "open_every_n_runs": max(1, int(cfg.get("open_every_n_runs", 5))),
    }
