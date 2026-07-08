"""
Flow 6 — World Map Scouting.

Dynamically discovers enemy HQs (OCR + pan/zoom), dispatches scout drones,
records intel, and writes an attack-priority report — no manual coordinates.
"""
from __future__ import annotations

import math
import time

from lastz.config import scouting_cfg, templates_dir, threshold as cfg_threshold
from lastz.flows.base import dismiss_overlay, reset_ui
from lastz.flows.hq_nav import is_hq_mode, navigate_to_wilderness
from lastz.input import ensure_game_running, focus_game
from lastz.ocr import is_blacklisted
from lastz.scouting.filters import evaluate_map_label, evaluate_modal
from lastz.scouting.map_nav import enter_sector, pan_scan_step, pan_travel_sector
from lastz.scouting.map_scan import MapTextHit, scan_map_labels
from lastz.scouting.models import MapLabel, ScoutIntel, ScoutTarget, SessionStats
from lastz.scouting.modal_detect import is_player_hq_modal
from lastz.scouting.ocr_labels import ocr_map_label_at, ocr_modal_fields, ocr_modal_header
from lastz.scouting.registry import already_scouted, mark_scouted_target, print_registry_summary
from lastz.scouting.report import print_scouting_report
from lastz.scouting.scoring import compute_modal_priority
from lastz.scouting.state import (
    filter_config_from_yaml,
    load_loop_state,
    record_intel,
    save_loop_state,
    state_file,
)
from lastz.scouting.log import close_run_log, open_run_log, slog
from lastz.scouting.zoom_levels import (
    log_zoom_snapshot,
    read_zoom_snapshot,
    return_to_server_overview,
    zoom_into_city_until_hq_labels,
    zoom_to_server_overview,
)
from lastz.screen import capture_both, click_capture_phys
from lastz.vision import find_all_templates, click_template


def _cfg() -> dict:
    return scouting_cfg()


def _template_exists(name: str) -> bool:
    return (templates_dir() / name).exists()


def _drone_sidebar_roi(gray) -> tuple[int, int, int, int]:
    h, w = gray.shape[:2]
    return int(w * 0.82), int(h * 0.18), w, int(h * 0.52)


def _count_idle_drones(gray) -> int:
    max_drones = int(_cfg().get("max_parallel_drones", 3))
    x0, y0, x1, y1 = _drone_sidebar_roi(gray)

    def _in_sidebar(m) -> bool:
        return x0 <= m.phys_x <= x1 and y0 <= m.phys_y <= y1

    if _template_exists("drone_slot_idle.png"):
        idle_thresh = cfg_threshold("drone_slot_idle")
        idle = [m for m in find_all_templates(gray, "drone_slot_idle.png", idle_thresh) if _in_sidebar(m)]
        if idle:
            n = min(max_drones, len(idle))
            slog(f"drone tray: {n} idle slot(s) visible")
            return n

    if not _template_exists("drone_slot_busy.png"):
        slog("drone tray: no templates — assuming all idle")
        return max_drones

    busy_thresh = cfg_threshold("drone_slot_busy")
    busy_all = find_all_templates(gray, "drone_slot_busy.png", busy_thresh)
    if len(busy_all) > max_drones * 2:
        slog(f"drone tray: busy template noisy ({len(busy_all)} hits) — assuming all idle")
        return max_drones
    busy = [m for m in busy_all if _in_sidebar(m)]
    idle = max(0, max_drones - min(max_drones, len(busy)))
    slog(f"drone tray: {len(busy)} busy → {idle} idle")
    return idle


def _ensure_wilderness() -> bool:
    _, screen = capture_both()
    if is_hq_mode(screen):
        slog("in HQ base mode — switching to wilderness")
        navigate_to_wilderness()
        time.sleep(2.0)
        _, screen = capture_both()
        if is_hq_mode(screen):
            slog("ERROR: failed to reach wilderness")
            return False
    slog("wilderness mode OK")
    return True


def _hit_to_label(hit: MapTextHit) -> MapLabel:
    if hit.name and hit.alliance_tag:
        display = f"[{hit.alliance_tag}]{hit.name}"
    elif hit.alliance_tag:
        display = f"[{hit.alliance_tag}]"
    else:
        display = hit.name or hit.text
    return MapLabel(
        alliance_tag=hit.alliance_tag,
        player_name=hit.name,
        hq_level=hit.level,
        raw_text=hit.text,
    )


def _filter_hq_hits(hits: list[MapTextHit], filt) -> list[MapTextHit]:
    own = filt.own_alliance.upper()
    kept: list[MapTextHit] = []
    for h in hits:
        tag = (h.alliance_tag or "").upper()
        if not tag or len(tag) < 2:
            continue
        if "[" not in h.text:
            continue
        if own and tag == own:
            continue
        if is_blacklisted(tag, filt.alliance_blacklist):
            continue
        if h.name and len(h.name) < 2:
            continue
        kept.append(h)
    return kept


def _debug_shot(color, name: str) -> None:
    try:
        import cv2
        from lastz.config import logs_dir
        path = logs_dir() / f"scout_debug_{name}.png"
        cv2.imwrite(str(path), color)
        slog(f"debug screenshot: {path}", phase="debug")
    except Exception:
        pass


def _filter_cities(cities: list[MapTextHit], filt) -> list[MapTextHit]:
    """Overview city list — blacklist only; own-alliance HQs filtered after zoom-in."""
    kept: list[MapTextHit] = []
    for hit in cities:
        tag = (hit.alliance_tag or "").upper()
        if is_blacklisted(tag, filt.alliance_blacklist):
            slog(f"skip blacklisted city [{tag}] {hit.name}", phase="city")
            continue
        kept.append(hit)
    return kept


def _click_offset(kind: str) -> tuple[float, float]:
    key = "hq_click_offset" if kind == "hq" else "city_click_offset"
    off = _cfg().get(key, [0, 50])
    return float(off[0]), float(off[1])


def _open_at(px: float, py: float, *, kind: str = "hq") -> None:
    ox, oy = _click_offset(kind)
    tx, ty = px + ox, py + oy
    slog(f"click {kind} @({tx:.0f}, {ty:.0f}) [label was ({px:.0f},{py:.0f})]", phase="click")
    click_capture_phys(tx, ty)
    time.sleep(float(_cfg().get("modal_settle_sec", 1.5)))


def _click_scout() -> bool:
    if not _template_exists("scout_action_btn.png"):
        slog("ERROR: scout_action_btn.png missing", phase="scout")
        return False
    match = click_template("scout_action_btn.png", cfg_threshold("scout_action_btn") - 0.15)
    if match:
        slog(f"clicked Scout btn conf={match.confidence:.3f}", phase="scout")
    else:
        slog("Scout button not found", phase="scout")
    return match is not None


def _dismiss_modal() -> None:
    dismiss_overlay(delay=0.8)
    time.sleep(0.5)


def _try_scout_target(
    target: ScoutTarget,
    label: MapLabel,
    *,
    filt,
    state: dict,
    stats: SessionStats,
    dry_run: bool,
    alliance_crop,
    power_crop,
    header_crop,
) -> bool:
    player_key = label.key or label.display_name

    if already_scouted(player_key, state):
        slog(f"registry skip: {label.display_name}", phase="scout")
        stats.record("skipped_cooldown")
        return False

    decision = evaluate_map_label(label, filt)
    if not decision.allowed:
        slog(f"map filter skip {label.display_name}: {decision.reason}", phase="scout")
        stats.record(decision.status or "ocr_incomplete")
        return False

    slog(f"opening HQ {label.display_name} lvl={label.hq_level}", phase="scout")
    _open_at(target.phys_x, target.phys_y, kind="hq")
    time.sleep(float(_cfg().get("house_click_settle_sec", 2.0)))
    color, _ = capture_both()

    if not is_player_hq_modal(color):
        from lastz.scouting.modal_detect import is_city_modal
        if is_city_modal(color):
            slog("opened CITY modal not HQ — dismissing", phase="scout")
        else:
            slog("not HQ modal after click — dismissing", phase="scout")
        _dismiss_modal()
        stats.record("ocr_incomplete")
        return False

    slog("HQ modal gate1 passed (Scout row visible)", phase="scout")

    header = ocr_modal_header(color, header_crop)
    if header.player_name or header.alliance_tag:
        label.alliance_tag = header.alliance_tag or label.alliance_tag
        label.player_name = header.player_name or label.player_name
        player_key = label.key or player_key
        slog(f"modal header OCR: {label.display_name}", phase="scout")

    modal = ocr_modal_fields(color, alliance_crop, power_crop)
    slog(
        f"modal OCR: alliance={modal.alliance_tag} power={modal.power} "
        f"(raw power={modal.power_raw!r})",
        phase="scout",
    )
    modal_decision = evaluate_modal(modal, filt)
    if not modal_decision.allowed:
        slog(f"modal filter skip: {modal_decision.reason}", phase="scout")
        stats.record(modal_decision.status or "ocr_incomplete")
        _dismiss_modal()
        return False

    if dry_run:
        slog(
            f"DRY RUN would scout {label.display_name} "
            f"alliance={modal.alliance_tag} power={modal.power}",
            phase="scout",
        )
        stats.record("dry_run_would_scout")
        if modal.power:
            record_intel(ScoutIntel(
                display_name=label.display_name,
                alliance=modal.alliance_tag or label.alliance_tag,
                hq_level=label.hq_level,
                power=modal.power,
                location=modal.map_location,
                scouted_at=time.time(),
                status="dry_run_would_scout",
                attack_score=compute_modal_priority(ScoutIntel(
                    display_name=label.display_name,
                    power=modal.power,
                    hq_level=label.hq_level,
                )),
            ))
        _dismiss_modal()
        return True

    if not _click_scout():
        stats.record("ocr_incomplete")
        _dismiss_modal()
        return False

    mark_scouted_target(
        state,
        player_key=player_key,
        display_name=label.display_name,
        alliance=modal.alliance_tag or label.alliance_tag,
        hq_level=label.hq_level,
        power=modal.power,
        status="dispatched",
    )
    save_loop_state(state)
    intel = ScoutIntel(
        display_name=label.display_name,
        alliance=modal.alliance_tag or label.alliance_tag,
        hq_level=label.hq_level,
        power=modal.power,
        location=modal.map_location,
        scouted_at=time.time(),
        status="dispatched",
        attack_score=compute_modal_priority(ScoutIntel(
            display_name=label.display_name,
            alliance=modal.alliance_tag,
            hq_level=label.hq_level,
            power=modal.power,
        )),
    )
    record_intel(intel)
    stats.record("dispatched")
    slog(f"SCOUT DISPATCHED: {label.display_name} power={modal.power}", phase="scout")
    _dismiss_modal()
    return True


def _scan_overview_cities(color, filt) -> list[MapTextHit]:
    cities = scan_map_labels(color, kind="city", strict=True)
    slog(f"OCR found {len(cities)} raw city label(s) on screen", phase="overview")
    cities = _filter_cities(cities, filt)
    own = filt.own_alliance.upper()
    # dedupe same city name; prefer top-most hit
    seen: dict[str, MapTextHit] = {}
    for c in cities:
        key = f"{(c.alliance_tag or '').upper()}:{(c.name or '').lower()}"
        if key not in seen:
            seen[key] = c
    cities = list(seen.values())
    cities.sort(key=lambda h: ((h.alliance_tag or "").upper() == own, h.phys_y, h.phys_x))
    for i, c in enumerate(cities):
        slog(
            f"  [{i}] [{c.alliance_tag}] {c.name} lvl={c.level} @({c.phys_x},{c.phys_y})",
            phase="overview",
        )
    return cities


def _scan_enemy_hqs(color, filt) -> list[MapTextHit]:
    """Find enemy HQ nameplates on the current screen (full map ROI, dynamic)."""
    own = filt.own_alliance.upper()
    hits = scan_map_labels(color, kind="hq", strict=True)
    refined: list[MapTextHit] = []
    for hit in hits:
        if not hit.alliance_tag or not hit.name:
            continue
        tag = hit.alliance_tag.upper()
        if own and tag == own:
            continue
        if is_blacklisted(tag, filt.alliance_blacklist):
            continue
        if hit.level is not None and hit.level > filt.max_hq_level:
            continue
        refined.append(hit)
    seen: dict[str, MapTextHit] = {}
    for h in refined:
        key = f"{h.alliance_tag}:{h.name}".lower()
        seen.setdefault(key, h)
    enemy = list(seen.values())
    enemy.sort(key=lambda h: (h.phys_y, h.phys_x))
    return enemy


def run_scouting_flow(*, dry_run: bool = False, max_scouts: int | None = None) -> None:
    log_path = open_run_log()
    slog(f"run log: {log_path}", phase="flow")

    def _check_scout_limit() -> None:
        if max_scouts and stats.dispatched >= max_scouts:
            slog(f"reached max_scouts={max_scouts} — stopping", phase="flow")
            raise KeyboardInterrupt

    ensure_game_running()
    focus_game()
    if not _ensure_wilderness():
        return

    reset_ui(clicks=2, delay=1.0)

    filt = filter_config_from_yaml()
    state = load_loop_state()
    stats = SessionStats()
    alliance_crop = _cfg().get("modal_alliance_crop", [0, 0, 0, 0])
    power_crop = _cfg().get("modal_power_crop", [0, 0, 0, 0])
    header_crop = _cfg().get("modal_header_crop", [0, 0, 0, 0])
    poll = float(_cfg().get("poll_interval_sec", 5))
    scan_steps_per_sector = int(_cfg().get("scan", {}).get("steps_per_sector", 6))
    max_overview_pans = len(_cfg().get("travel", {}).get("sector_pans", [])) or 8

    mode = "DRY RUN" if dry_run else "LIVE"
    limit = f" max_scouts={max_scouts}" if max_scouts else ""
    slog(f"=== Scouting {mode} — dynamic map sweep{limit} ===", phase="flow")
    slog(
        f"filters: own={filt.own_alliance!r} max_lvl={filt.max_hq_level} "
        f"max_pwr={filt.max_power}",
        phase="flow",
    )
    slog(f"registry: {state_file()}", phase="flow")
    print_registry_summary(state, header="Loaded registry")

    if state.get("phase") == "home":
        slog("STEP 1: default world view — confirm zoom snapshot", phase="flow")
        color, _ = capture_both()
        log_zoom_snapshot(color, label="home view")
        enemy_hqs = _scan_enemy_hqs(color, filt)
        if enemy_hqs:
            slog(f"already at HQ label zoom — {len(enemy_hqs)} enemy HQ(s) visible", phase="flow")
            state["phase"] = "hq_sweep"
        else:
            slog("STEP 2: zoom out to server overview", phase="flow")
            zoom_to_server_overview(from_home=True)
            state["phase"] = "overview"
        state["city_index"] = 0
        state["overview_pan_index"] = 0
        state["scan_step_index"] = 0
        save_loop_state(state)

    try:
        while True:
            color, gray = capture_both()
            idle = _count_idle_drones(gray)
            slog(f"idle drones: {idle}/{_cfg().get('max_parallel_drones', 3)}", phase="loop")

            if idle == 0:
                slog(f"all drones busy — wait {poll:.0f}s", phase="loop")
                time.sleep(poll)
                continue

            phase = state.get("phase", "overview")

            hq_targets = _scan_enemy_hqs(color, filt)
            if hq_targets:
                slog(f"found {len(hq_targets)} enemy HQ(s) on screen — scouting", phase="discover")
                dispatched = 0
                for hit in hq_targets:
                    if dispatched >= idle:
                        break
                    label = _hit_to_label(hit)
                    slog(
                        f"  target {label.display_name} lvl={label.hq_level} "
                        f"@({hit.phys_x},{hit.phys_y})",
                        phase="discover",
                    )
                    target = ScoutTarget(hit.phys_x, hit.phys_y, 1.0, 0)
                    if _try_scout_target(
                        target, label, filt=filt, state=state, stats=stats,
                        dry_run=dry_run, alliance_crop=alliance_crop,
                        power_crop=power_crop, header_crop=header_crop,
                    ):
                        dispatched += 1
                        _check_scout_limit()
                        if dry_run:
                            slog("dry run success — stopping", phase="flow")
                            raise KeyboardInterrupt

                scan_step = int(state.get("scan_step_index", 0))
                pan_scan_step(scan_step)
                state["scan_step_index"] = scan_step + 1
                state["phase"] = "hq_sweep"
                if state["scan_step_index"] >= scan_steps_per_sector:
                    state["scan_step_index"] = 0
                    slog("HQ screen swept — zoom out to find next area", phase="nav")
                    return_to_server_overview()
                    state["phase"] = "overview"
                    state["overview_pan_index"] = int(state.get("overview_pan_index", 0)) + 1
                save_loop_state(state)
                continue

            if phase == "overview":
                pan_idx = int(state.get("overview_pan_index", 0))
                if pan_idx > 0:
                    slog(f"overview pan {pan_idx}/{max_overview_pans}", phase="overview")
                    pan_travel_sector(pan_idx)
                    color, _ = capture_both()

                log_zoom_snapshot(color, label="overview screen")
                cities = _scan_overview_cities(color, filt)
                own_tag = filt.own_alliance.upper()
                enemy_cities = [c for c in cities if (c.alliance_tag or "").upper() != own_tag]
                if not enemy_cities:
                    slog("no enemy cities on screen — pan to next overview sector", phase="overview")
                    state["overview_pan_index"] = (pan_idx + 1) % max_overview_pans
                    state["city_index"] = 0
                    save_loop_state(state)
                    continue
                cities = enemy_cities
                city_idx = int(state.get("city_index", 0))

                if not cities:
                    slog("no enemy cities on screen — pan to next overview sector", phase="overview")
                    state["overview_pan_index"] = (pan_idx + 1) % max_overview_pans
                    state["city_index"] = 0
                    save_loop_state(state)
                    continue

                if city_idx >= len(cities):
                    slog(f"all {len(cities)} cities on this screen visited — next pan", phase="overview")
                    state["overview_pan_index"] = (pan_idx + 1) % max_overview_pans
                    state["city_index"] = 0
                    save_loop_state(state)
                    continue

                city = cities[city_idx]
                slog(
                    f"STEP 3: visit city {city_idx + 1}/{len(cities)} "
                    f"[{city.alliance_tag}] {city.name}",
                    phase="flow",
                )
                _open_at(city.phys_x, city.phys_y, kind="city")
                time.sleep(float(_cfg().get("city_click_settle_sec", 3.0)))
                color, _ = capture_both()
                _debug_shot(color, "after_city_click")
                from lastz.scouting.modal_detect import is_city_modal
                if is_city_modal(color):
                    slog("city modal opened on click — dismissing before zoom-in", phase="city")
                    _dismiss_modal()
                state["phase"] = "in_city"
                save_loop_state(state)
                continue

            if phase == "in_city":
                slog("STEP 3b: zoom in until HQ name+level labels visible", phase="flow")
                hq_hits = zoom_into_city_until_hq_labels(filt=filt)
                color, _ = capture_both()
                _debug_shot(color, "after_city_zoom_in")
                slog(f"found {len(hq_hits)} HQ label(s) in city", phase="city")

                dispatched = 0
                for hit in hq_hits:
                    if dispatched >= idle:
                        break
                    label = _hit_to_label(hit)
                    slog(
                        f"HQ candidate: {label.display_name} lvl={label.hq_level} "
                        f"@({hit.phys_x},{hit.phys_y})",
                        phase="city",
                    )
                    target = ScoutTarget(hit.phys_x, hit.phys_y, 1.0, 0)
                    if _try_scout_target(
                        target, label, filt=filt, state=state, stats=stats,
                        dry_run=dry_run, alliance_crop=alliance_crop,
                        power_crop=power_crop, header_crop=header_crop,
                    ):
                        dispatched += 1
                        _check_scout_limit()
                        if dry_run:
                            slog("dry run success — stopping", phase="flow")
                            raise KeyboardInterrupt

                slog(f"city done — scouted {dispatched}, returning to overview", phase="city")
                return_to_server_overview()
                state["city_index"] = int(state.get("city_index", 0)) + 1
                state["phase"] = "overview"
                save_loop_state(state)
                continue

            slog(f"unknown phase {phase!r} — reset to overview", phase="flow")
            state["phase"] = "overview"
            save_loop_state(state)

    except KeyboardInterrupt:
        print("\n>>> Scouting stopped.")
        print_registry_summary(state, header="Final registry")
        print(
            f"    session: scouted={stats.dispatched} skipped_registry={stats.skipped_cooldown} "
            f"own={stats.skipped_own_alliance} blacklist={stats.skipped_blacklist} "
            f"level={stats.skipped_level} power={stats.skipped_power} dry_run={stats.dry_run_would_scout}"
        )
        print_scouting_report()
        close_run_log()
