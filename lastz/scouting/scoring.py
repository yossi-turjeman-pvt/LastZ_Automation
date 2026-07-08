"""Attack priority scoring (v2 — used when mail intel is available)."""
from __future__ import annotations

from lastz.config import scouting_cfg
from lastz.scouting.models import ScoutIntel


def _normalize(value: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return max(0.0, min(1.0, value / cap))


def compute_modal_priority(intel: ScoutIntel) -> float | None:
    """
    Attack priority from modal data (power + HQ level) before mail arrives.

    Higher = weaker/easier target relative to your filters. Scale 0–100.
    """
    if intel.power is None:
        return None
    cfg = scouting_cfg()
    max_pwr = int(cfg.get("max_power", 999_999_999))
    max_lvl = int(cfg.get("max_hq_level", 30))
    ref_pwr = int(cfg.get("reference_power", 100_000))

    if intel.power > max_pwr:
        return 0.0

    power_score = 1.0 - _normalize(float(intel.power), float(min(max_pwr, ref_pwr)))
    lvl = intel.hq_level or max_lvl
    lvl_score = 1.0 - _normalize(float(lvl), float(max_lvl))
    return round(100.0 * (0.65 * power_score + 0.35 * lvl_score), 1)


def compute_attack_score(
    intel: ScoutIntel,
    *,
    user_power: int | None = None,
    max_distance: float = 1.0,
    distance: float = 0.0,
) -> float | None:
    """
    Weighted attack priority score in [0, 1].

    Returns None if insufficient data (no resources from mail yet).
    """
    cfg = scouting_cfg().get("attack_score", {})
    w_res = float(cfg.get("weight_resources", 0.4))
    w_pwr = float(cfg.get("weight_power_ratio", 0.3))
    w_dist = float(cfg.get("weight_distance", 0.2))
    w_lvl = float(cfg.get("weight_hq_level", 0.1))

    if intel.food is None and intel.wood is None and intel.zent is None:
        return None

    food = intel.food or 0
    wood = intel.wood or 0
    zent = intel.zent or 0
    resource_score = _normalize(float(food + wood + zent), 5_000_000.0)

    ref_power = user_power or int(scouting_cfg().get("reference_power", 100_000))
    power = intel.power or ref_power
    power_score = 1.0 - _normalize(float(power), float(ref_power))

    dist_score = 1.0 - _normalize(distance, max_distance) if max_distance > 0 else 0.5

    max_lvl = int(scouting_cfg().get("max_hq_level", 30))
    lvl = intel.hq_level or max_lvl
    lvl_score = 1.0 - _normalize(float(lvl), float(max_lvl))

    return (
        w_res * resource_score
        + w_pwr * power_score
        + w_dist * dist_score
        + w_lvl * lvl_score
    )
