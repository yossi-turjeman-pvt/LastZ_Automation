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
    """Return a physical-pixel offset stored at reference capture resolution."""
    values = load_config()["coordinates"][name]
    return float(values[0]), float(values[1])


def window_offset_click(name: str) -> tuple[float, float]:
    """Click a fixed logical-pixel offset from the game window top-left corner."""
    from lastz.screen import get_game_window_bounds

    ox, oy = coord_offset(name)
    wx, wy, _, _ = get_game_window_bounds()
    return wx + ox, wy + oy


def watcher_cfg() -> dict:
    return load_config()["watcher"]


def scouting_cfg() -> dict:
    return load_config().get("scouting", {})
