"""Detect and navigate between world-map zoom levels for city-sweep scouting."""
from __future__ import annotations

import time
from dataclasses import dataclass

from lastz.config import scouting_cfg
from lastz.scouting.map_nav import zoom_in, zoom_out
from lastz.scouting.map_scan import MapTextHit, scan_map_labels


def _cfg() -> dict:
    return scouting_cfg()


def _zoom_cfg() -> dict:
    return _cfg().get("zoom", {})


from lastz.scouting.log import slog


@dataclass
class ZoomSnapshot:
    city_labels: int
    hq_labels: int
    colorful_territory: bool

    @property
    def level(self) -> str:
        if self.hq_labels >= 1 and self.city_labels <= 2:
            return "hq_labels"
        if self.colorful_territory and self.city_labels >= 3:
            return "server_overview"
        if self.city_labels >= 4 and self.hq_labels < 2:
            return "server_overview"
        if self.hq_labels >= 2:
            return "hq_labels"
        if self.city_labels == 0 and self.hq_labels == 0:
            return "home_or_unknown"
        return "mixed"


def read_zoom_snapshot(color) -> ZoomSnapshot:
    from lastz.scouting.map_nav import looks_like_territory_map

    cities = scan_map_labels(color, kind="city", strict=True)
    hqs = scan_map_labels(color, kind="hq", strict=True)
    return ZoomSnapshot(
        city_labels=len(cities),
        hq_labels=len(hqs),
        colorful_territory=looks_like_territory_map(color),
    )


def log_zoom_snapshot(color, *, label: str = "snapshot") -> ZoomSnapshot:
    snap = read_zoom_snapshot(color)
    slog(
        f"{label}: level={snap.level} cities={snap.city_labels} "
        f"hqs={snap.hq_labels} territory={snap.colorful_territory}",
    )
    return snap


def zoom_to_server_overview(*, from_home: bool = True) -> ZoomSnapshot:
    """Zoom out until colorful server map with several city labels; avoid over-zoom."""
    from lastz.screen import capture_both

    z = _zoom_cfg()
    color, _ = capture_both()
    snap = log_zoom_snapshot(color, label="before server zoom-out")
    min_cities = int(z.get("server_overview_min_cities", 4))
    if snap.city_labels >= min_cities:
        slog("already at server overview — skip zoom-out")
        return snap

    batch = int(z.get("server_overview_out_steps", 6))
    max_rounds = int(z.get("server_overview_max_rounds", 6))
    best_cities = snap.city_labels
    if from_home:
        slog("zooming OUT to server overview (adaptive)")

    for rnd in range(max_rounds):
        zoom_out(steps=batch)
        time.sleep(float(z.get("settle_sec", 1.2)))
        color, _ = capture_both()
        snap = log_zoom_snapshot(color, label=f"server zoom-out round {rnd + 1}")
        if snap.city_labels >= min_cities:
            return snap
        if snap.city_labels > best_cities:
            best_cities = snap.city_labels
        elif best_cities > 0 and snap.city_labels < best_cities:
            slog(f"over-zoomed ({snap.city_labels} < peak {best_cities}) — zoom IN 4 steps")
            zoom_in(steps=4)
            time.sleep(0.8)
            color, _ = capture_both()
            return log_zoom_snapshot(color, label="server overview corrected")
    return snap


def zoom_into_city_until_hq_labels(*, min_labels: int | None = None, filt=None) -> list[MapTextHit]:
    """After clicking a city, zoom IN until player HQ name+level labels appear."""
    z = _zoom_cfg()
    max_steps = int(z.get("city_zoom_in_max_steps", 10))
    per_step = int(z.get("city_zoom_in_per_step", 2))
    need = min_labels if min_labels is not None else int(z.get("hq_label_min_count", 1))
    bootstrap = int(z.get("city_zoom_in_bootstrap_steps", 8))

    from lastz.screen import capture_both
    from lastz.scouting.filters import FilterConfig

    filt = filt or FilterConfig("", [], 99, 999_999_999)

    slog(f"bootstrap zoom IN {bootstrap} steps after city click", phase="zoom")
    zoom_in(steps=bootstrap)
    time.sleep(float(z.get("settle_sec", 1.2)))

    for step in range(max_steps):
        color, _ = capture_both()
        raw = scan_map_labels(color, kind="hq", strict=False)
        valid_hqs = _filter_hq_hits_loose(raw, filt)
        slog(f"city zoom-in step {step + 1}/{max_steps}: {len(valid_hqs)} HQ(s) (raw {len(raw)})", phase="zoom")
        for h in valid_hqs[:6]:
            slog(f"    [{h.alliance_tag}]{h.name} lvl={h.level} @({h.phys_x},{h.phys_y})", phase="zoom")
        if len(valid_hqs) >= need:
            return valid_hqs
        zoom_in(steps=per_step)
        time.sleep(float(z.get("step_delay_sec", 0.3)))

    color, _ = capture_both()
    raw = scan_map_labels(color, kind="hq", strict=False)
    return _filter_hq_hits_loose(raw, filt)


def _filter_hq_hits_loose(hits: list[MapTextHit], filt) -> list[MapTextHit]:
    from lastz.ocr import is_blacklisted

    own = filt.own_alliance.upper()
    kept: list[MapTextHit] = []
    for h in hits:
        tag = (h.alliance_tag or "").upper()
        if not tag or len(tag) < 2:
            continue
        if own and tag == own:
            continue
        if is_blacklisted(tag, filt.alliance_blacklist):
            continue
        if not h.name or len(h.name) < 2:
            continue
        kept.append(h)
    return kept


def return_to_server_overview(*, steps: int | None = None) -> ZoomSnapshot:
    """Zoom back out to server overview after visiting a city."""
    z = _zoom_cfg()
    n = steps if steps is not None else int(z.get("return_overview_out_steps", 6))
    slog(f"returning to server overview ({n} zoom-out steps)")
    zoom_out(steps=n)
    time.sleep(float(z.get("settle_sec", 1.2)))

    from lastz.screen import capture_both

    color, _ = capture_both()
    snap = log_zoom_snapshot(color, label="back at overview")
    if snap.city_labels < 2:
        zoom_out(steps=3)
        time.sleep(0.6)
        color, _ = capture_both()
        snap = log_zoom_snapshot(color, label="overview nudge")
    return snap
