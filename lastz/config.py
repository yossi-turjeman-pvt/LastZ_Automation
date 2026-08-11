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
    # Wide highway scan to discover ALL tracks, then code uses uppermost only.
    band = cfg.get("highway_band") or cfg.get("upper_plus_band") or [0.10, 0.78, 0.28, 0.72]
    if len(band) < 4:
        band = [0.10, 0.78, 0.28, 0.72]
    return {
        "include_trucks_flow": bool(cfg.get("include_trucks_flow", True)),
        "allow_purple_trucks": bool(cfg.get("allow_purple_trucks", False)),
        "max_refreshes": int(cfg.get("max_refreshes", 15)),
        # Open on badge always; also every Nth gifts run (send without badge).
        "open_every_n_runs": max(1, int(cfg.get("open_every_n_runs", 5))),
        "highway_band": [
            float(band[0]),
            float(band[1]),
            float(band[2]),
            float(band[3]),
        ],
        # Save ROI+mask crops under logs/debug/trucks/color/ for human VERIFY
        "save_color_debug": bool(cfg.get("save_color_debug", True)),
        # Number of highway lanes when all are visible/empty (observed: 4).
        # Used to only "learn" the true top-row Y-position from a scan we can
        # be sure has no hidden occupied row above it.
        "expected_track_count": max(1, int(cfg.get("expected_track_count", 4))),
        # How far below the learned top-row Y-fraction a slot can still be
        # trusted as "the upper slot". A track further down than this is
        # treated as row 2+ (i.e. row 1 is probably an invisible in-transit
        # truck) and the send is refused rather than guessed.
        "top_row_tolerance": float(cfg.get("top_row_tolerance", 0.05)),
    }


def farm_resources_cfg() -> dict:
    """HQ farm resource collection flow toggles (zoom-out + pan scan)."""
    cfg = load_config().get("farm_resources") or {}

    origin = cfg.get("map_drag_origin") or [0.5, 0.42]
    if len(origin) < 2:
        origin = [0.5, 0.42]

    zoom = cfg.get("zoom") or {}

    swipes_raw = cfg.get("pan_swipes") or [[0, -260], [260, 0], [0, 260], [-260, 0]]
    pan_swipes = []
    for s in swipes_raw:
        if len(s) >= 2:
            pan_swipes.append([float(s[0]), float(s[1])])
    if not pan_swipes:
        pan_swipes = [[0.0, -260.0], [260.0, 0.0], [0.0, 260.0], [-260.0, 0.0]]

    hud = cfg.get("hud_exclude") or {}

    return {
        "enabled": bool(cfg.get("enabled", True)),
        "map_drag_origin": [float(origin[0]), float(origin[1])],
        "zoom_out_steps": max(0, int(zoom.get("out_steps", 4))),
        "zoom_delta_per_step": float(zoom.get("delta_per_step", -3)),
        "zoom_step_delay_sec": float(zoom.get("step_delay_sec", 0.25)),
        "zoom_settle_sec": float(zoom.get("settle_sec", 1.5)),
        "pan_swipes": pan_swipes,
        "pan_settle_sec": float(cfg.get("pan_settle_sec", 1.0)),
        "hud_top_frac": float(hud.get("top_frac", 0.08)),
        "hud_bottom_frac": float(hud.get("bottom_frac", 0.12)),
        "hud_left_frac": float(hud.get("left_frac", 0.02)),
        "hud_right_frac": float(hud.get("right_frac", 0.07)),
        "dedupe_radius_px": float(cfg.get("dedupe_radius_px", 80)),
        "post_click_settle_sec": float(cfg.get("post_click_settle_sec", 1.5)),
    }


def help_watcher_cfg() -> dict:
    """Help blink-clicker poll + search band (yf0, yf1, xf0, xf1)."""
    cfg = load_config().get("help_watcher") or {}
    band = cfg.get("band") or [0.50, 1.0, 0.75, 1.0]
    if len(band) < 4:
        band = [0.50, 1.0, 0.75, 1.0]
    return {
        "poll_sec": float(cfg.get("poll_sec", 0.05)),
        "band": [float(band[0]), float(band[1]), float(band[2]), float(band[3])],
    }


def healing_cfg() -> dict:
    """Healing flow config (runs in parallel with Help watcher)."""
    cfg = load_config().get("healing") or {}
    icon_band = cfg.get("icon_band") or [0.75, 1.0, 0.0, 0.20]
    if len(icon_band) < 4:
        icon_band = [0.75, 1.0, 0.0, 0.20]
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "batch_size": int(cfg.get("batch_size", 50)),
        "check_interval_sec": float(cfg.get("check_interval_sec", 5.0)),
        "icon_band": [float(icon_band[0]), float(icon_band[1]), float(icon_band[2]), float(icon_band[3])],
    }
