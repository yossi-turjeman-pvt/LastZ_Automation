"""
Helicopter (Explore Treasure) flow — priority over gifts collection.

Steps: BR indication → chat coords → march weakest zZz → wait Search (≤6m) →
prize spam-click → thank-you in Alliance chat.
"""
from __future__ import annotations

import datetime
import re
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from lastz.config import load_config, logs_dir, threshold as cfg_threshold
from lastz.debug_match import annotate_and_save, debug_dir, in_band, match_row
from lastz.flows.base import dismiss_overlay, dismiss_quit_tips_if_present
from lastz.flows.ui_bands import BAND_HELI_BR, BAND_HELI_CENTER, BAND_HELI_FORMATIONS
from lastz.heli_priority import clear_heli, heli_pending, signal_heli
from lastz.input import (
    GameNotRunningError,
    click,
    ensure_game_running,
    focus_game,
    is_game_running,
    paste_text,
    press_escape,
    press_return,
    rapid_click,
)
from lastz.ocr import format_duration, read_duration_from_region, read_ui_text
from lastz.runlog import dump_crash, log_click, log_step
from lastz.screen import (
    capture,
    capture_both,
    physical_to_logical,
    window_click,
)
from lastz.vision import ensure_template_scale, find_all_templates, find_template

_HELI_DEBUG = "heli"


def helicopter_cfg() -> dict:
    cfg = load_config().get("helicopter") or {}
    band = cfg.get("br_band") or list(BAND_HELI_BR)
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "poll_sec": float(cfg.get("poll_sec", 1.0)),
        "br_band": [float(band[0]), float(band[1]), float(band[2]), float(band[3])],
        "search_max_sec": int(cfg.get("search_max_sec", 5 * 60)),
        "prize_at_sec": int(cfg.get("prize_at_sec", 1)),
        "prize_clicks": int(cfg.get("prize_clicks", 120)),
        "prize_interval": float(cfg.get("prize_interval", 0.003)),
        "prize_burst_span_sec": float(cfg.get("prize_burst_span_sec", 8.0)),
        "thank_you_text": str(
            cfg.get("thank_you_text") or "Thank You from LastZ-Automation"
        ),
        "empty_land_offset_frac": [
            float(x)
            for x in (cfg.get("empty_land_offset_frac") or [-0.04, 0.06])
        ],
        "wait_search_timeout_sec": float(cfg.get("wait_search_timeout_sec", 7200)),
        "wait_prize_timeout_sec": float(cfg.get("wait_prize_timeout_sec", 600)),
    }


def _thr(name: str, default: float) -> float:
    try:
        return float(cfg_threshold(name))
    except Exception:
        return default


def _log_path() -> Path:
    p = logs_dir() / "heli.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def heli_log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(_log_path(), "a") as f:
        f.write(line + "\n")


def _save_raw(color: np.ndarray, step: str) -> Path:
    ts = time.strftime("%H%M%S")
    out = debug_dir(_HELI_DEBUG) / f"{step}_{ts}_raw.png"
    cv2.imwrite(str(out), color)
    heli_log(f"[debug] raw {out}")
    return out


def _save_roi(color: np.ndarray, step: str, x: int, y: int, bw: int, bh: int) -> Path:
    h, w = color.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + bw), min(h, y + bh)
    crop = color[y0:y1, x0:x1]
    ts = time.strftime("%H%M%S")
    out = debug_dir(_HELI_DEBUG) / f"{step}_{ts}_roi.png"
    cv2.imwrite(str(out), crop)
    heli_log(f"[debug] roi {out} ({x0},{y0},{x1 - x0}x{y1 - y0})")
    return out


def _match_dict(m, label: str, *, ok: bool = True, note: str = "") -> dict:
    return {
        "label": label,
        "phys_x": m.phys_x,
        "phys_y": m.phys_y,
        "conf": m.confidence,
        "phys_w": getattr(m, "phys_w", None) or 40,
        "phys_h": getattr(m, "phys_h", None) or 40,
        "ok": ok,
        "note": note,
    }


def _annotate(color, step: str, matches: list[dict]) -> Path:
    path = annotate_and_save(color, step, matches, subdir=_HELI_DEBUG)
    heli_log(f"[debug] annotated {path}")
    return path


def find_br_heli(gray: np.ndarray | None = None, color: np.ndarray | None = None):
    """Find BR Helicopter indication. Returns match or None."""
    if gray is None or color is None:
        color, gray = capture_both()
    h, w = gray.shape[:2]
    band = tuple(helicopter_cfg()["br_band"])
    thr = _thr("heli_br_icon", 0.70)
    matches = find_all_templates(gray, "heli_br_icon.png", thr)
    in_b = [m for m in matches if in_band(m.phys_x, m.phys_y, h, w, *band)]
    if not in_b:
        # Soft retry lower threshold
        matches = find_all_templates(gray, "heli_br_icon.png", max(0.55, thr - 0.12))
        in_b = [m for m in matches if in_band(m.phys_x, m.phys_y, h, w, *band)]
    if not in_b:
        return None
    in_b.sort(key=lambda m: m.confidence, reverse=True)
    return in_b[0]


def poll_br_heli_once() -> bool:
    """
    Return True if BR heli indication is visible (and signal priority).

    Uses the occlusion-proof window capture (by game process/window, not a
    full-display screencapture) — this poller runs continuously in the
    background while the operator (and this agent) may have Cursor in the
    foreground on top of the game, and a full-display capture would just
    see Cursor's own UI at that moment instead, silently going blind to a
    real BR indication for as long as the game stays occluded. Falls back
    to the full-display capture only if the window-specific one is
    unavailable (e.g. game minimized).
    """
    if not helicopter_cfg()["enabled"]:
        return False
    try:
        color, gray = _watch_capture()
        ensure_template_scale(gray)
        m = find_br_heli(gray, color)
        if m is not None:
            signal_heli()
            return True
    except Exception as e:
        heli_log(f"poll warn: {e}")
    return False


_monitor_stop = threading.Event()
_monitor_thread: threading.Thread | None = None


def start_heli_monitor() -> None:
    """Background BR poller — sets heli_pending when indication appears."""
    global _monitor_thread
    if not helicopter_cfg()["enabled"]:
        return
    if _monitor_thread is not None and _monitor_thread.is_alive():
        return
    _monitor_stop.clear()
    poll = helicopter_cfg()["poll_sec"]

    def _loop() -> None:
        heli_log(f"BR monitor started (poll={poll}s)")
        while not _monitor_stop.is_set():
            try:
                if is_game_running() and not heli_pending():
                    poll_br_heli_once()
            except Exception:
                pass
            _monitor_stop.wait(poll)
        heli_log("BR monitor stopped")

    _monitor_thread = threading.Thread(target=_loop, name="heli-br-monitor", daemon=True)
    _monitor_thread.start()


def stop_heli_monitor() -> None:
    _monitor_stop.set()


def _click_match(m, label: str, template: str) -> None:
    lx, ly = physical_to_logical(m.phys_x, m.phys_y)
    log_click(label, template=template, conf=m.confidence, logical_xy=(lx, ly),
              phys_xy=(m.phys_x, m.phys_y))
    heli_log(
        f"[click] {label} conf={m.confidence:.3f} "
        f"phys=({m.phys_x:.0f},{m.phys_y:.0f}) logical=({lx:.0f},{ly:.0f})"
    )
    click(lx, ly)


def _click_frac(fx: float, fy: float, label: str, color: np.ndarray | None = None) -> None:
    lx, ly = window_click(fx, fy)
    heli_log(f"[click] {label} window_frac ({fx:.2f},{fy:.2f}) -> logical ({lx:.0f},{ly:.0f})")
    if color is not None:
        h, w = color.shape[:2]
        # Approximate phys from window frac for annotation (best-effort)
        px, py = int(fx * w), int(fy * h)
        _annotate(
            color,
            f"{label}_frac",
            [{"label": label, "phys_x": px, "phys_y": py, "conf": 0.0, "ok": True, "note": "frac"}],
        )
    click(lx, ly)


def _step_open_from_br() -> bool:
    heli_log("[Heli] Step1: BR indication")
    color, gray = capture_both()
    _save_raw(color, "step1_br")
    h, w = gray.shape[:2]
    band = tuple(helicopter_cfg()["br_band"])
    thr = _thr("heli_br_icon", 0.70)
    raw = find_all_templates(gray, "heli_br_icon.png", max(0.45, thr - 0.25))
    rows = [
        match_row(
            "heli_br_icon.png",
            m.phys_x,
            m.phys_y,
            m.confidence,
            h,
            w,
            phys_w=getattr(m, "phys_w", None),
            phys_h=getattr(m, "phys_h", None),
            band=band,
        )
        for m in raw
    ]
    m = find_br_heli(gray, color)
    if m is None:
        heli_log(f"[Heli] BR heli not found (raw_matches={len(raw)} thr={thr} band={band})")
        _annotate(color, "step1_br_MISS", rows if rows else [
            {"label": "no_match", "phys_x": int(0.9 * w), "phys_y": int(0.8 * h), "conf": 0, "ok": False}
        ])
        # BR quarter crop for template retune
        y0, y1 = int(band[0] * h), int(band[1] * h)
        x0, x1 = int(band[2] * w), int(band[3] * w)
        _save_roi(color, "step1_br_band", x0, y0, x1 - x0, y1 - y0)
        return False
    _annotate(color, "step1_br_HIT", [_match_dict(m, "heli_br", note="click")])
    _click_match(m, "heli_br", "heli_br_icon.png")
    time.sleep(2.0)
    after, _ = capture_both()
    _save_raw(after, "step1_br_after")
    return True


_INVITE_REJECT_PHRASES = (
    "fully explored",
    "been fully",
    "jackpot",
    "double",
    "quick march",
    "missed out",
    "oops you",
    "oops, you",
    "can obtain",
    "cost:",
)


def _is_active_invite_text(text_lower: str) -> bool:
    """
    True only for a live "send troops to explore together" invite — never for
    a "has been fully explored" notice, missed-reward Details modal, or an
    unrelated shared-item message. Both banners share the same orange graphic,
    so text content (not just color) is what tells them apart.

    Note: never reject on bare "oops" — OCR of "troops"/"itroops" contains
    the substring "oops" and false-rejected live invites (attempt_001).
    """
    if any(p in text_lower for p in _INVITE_REJECT_PHRASES):
        return False
    # Prefer clear invite phrasing; tolerate OCR glue (itroops, tojexplore).
    has_send = "send" in text_lower
    has_troop = "troop" in text_lower
    has_explore = "explore" in text_lower
    has_together = "together" in text_lower
    has_treasure = "treasure" in text_lower or "ireasure" in text_lower
    if has_send and (has_troop or has_explore or has_together):
        return True
    # OCR sometimes drops "send" but keeps explore+treasure+found.
    if has_explore and has_treasure and ("found" in text_lower or has_together or has_troop):
        return True
    return False


def _is_missed_out_modal(color: np.ndarray) -> bool:
    """True if the 'Oops, you missed out on the reward!' Details modal is up."""
    h, w = color.shape[:2]
    text = _ocr_block(color, int(0.30 * w), int(0.18 * h), int(0.40 * w), int(0.45 * h))
    low = text.lower().replace("\n", " ")
    return ("missed out" in low) or ("oops you" in low and "reward" in low) or (
        "oops, you" in low and "reward" in low
    )


def _find_orange_banner_blobs(color: np.ndarray, min_area_frac: float = 0.003) -> list[tuple[int, int, int, int, int]]:
    """Wide orange/red event-banner blocks — rejects full-screen / chrome blobs."""
    h, w = color.shape[:2]
    hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (5, 90, 90), (30, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 25), np.uint8))
    n, _labels, stats, _cents = cv2.connectedComponentsWithStats(mask, 8)
    min_area = min_area_frac * w * h
    max_area = 0.12 * w * h
    blobs = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area or area > max_area:
            continue
        if bw / max(bh, 1) < 1.5:
            continue
        # Full-width chrome / map wash is never the chat invite banner.
        if bw / max(w, 1) > 0.55:
            continue
        blobs.append((int(x), int(y), int(bw), int(bh), int(area)))
    blobs.sort(key=lambda b: b[4], reverse=True)
    return blobs


def _ocr_block(color: np.ndarray, x: int, y: int, w: int, h: int) -> str:
    from lastz.ocr import tesseract_available

    if not tesseract_available():
        return ""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(color.shape[1], x + w), min(color.shape[0], y + h)
    crop = color[y0:y1, x0:x1]
    if crop.size == 0:
        return ""
    import pytesseract

    big = cv2.resize(crop, (crop.shape[1] * 3, crop.shape[0] * 3), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    try:
        return pytesseract.image_to_string(gray, config="--psm 6").strip()
    except Exception:
        return ""


def _find_green_text_blob(color: np.ndarray, x: int, y: int, w: int, h: int):
    """Largest wide/short green blob in region — the coords link text line."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(color.shape[1], x + w), min(color.shape[0], y + h)
    roi = color[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (40, 60, 60), (95, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 15), np.uint8))
    n, _labels, stats, _cents = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if area < 30 or bw / max(bh, 1) < 2:
            continue
        if best is None or area > best[4]:
            best = (bx, by, bw, bh, area)
    if best is None:
        return None
    bx, by, bw, bh, area = best
    return (bx + x0 + bw / 2.0, by + y0 + bh / 2.0, bw, bh, area)


def find_explore_treasure_coords(color: np.ndarray) -> dict | None:
    """
    Fully dynamic locate of the active "Explore Treasure — send troops" chat
    banner in THIS frame only.

    Collects all orange+OCR invite candidates, then picks the best:
    prefer lower on screen (real chat rows, not top chrome), prefer banners
    that also have a green coords blob. Falls back to heli_explore_banner /
    heli_coords_link templates when OCR rejects (e.g. historical "oops" in
    "itroops" false reject).
    """
    h, w = color.shape[:2]
    candidates: list[dict] = []
    for bx, by, bw, bh, _area in _find_orange_banner_blobs(color):
        cy_blob = by + bh / 2.0
        # Top chrome / notice strip — never the Alliance chat invite.
        if cy_blob / h < 0.28:
            continue
        ext_h = int(bh * 4.5)
        rx, ry, rw = bx - 10, by - 5, bw + 260
        text = _ocr_block(color, rx, ry, rw, ext_h)
        text_lower = text.lower().replace("\n", " | ")
        if not _is_active_invite_text(text_lower):
            continue
        green = _find_green_text_blob(color, rx, by, rw, ext_h)
        cx, cy = bx + bw / 2.0, by + bh / 2.0
        # Prefer lower banners; strong bonus if green State/X/Y link is present.
        score = (cy / h) + (0.5 if green is not None else 0.0)
        candidates.append(
            {
                "phys_x": cx,
                "phys_y": cy,
                "banner_bbox": (bx, by, bw, bh),
                "coords_bbox": None
                if green is None
                else (
                    green[0] - green[2] / 2.0,
                    green[1] - green[3] / 2.0,
                    green[2],
                    green[3],
                ),
                "text": text,
                "score": score,
                "has_green": green is not None,
            }
        )
    if candidates:
        candidates.sort(key=lambda c: c["score"], reverse=True)
        best = candidates[0]
        heli_log(
            f"[Heli] banner candidates={len(candidates)} pick yf={best['phys_y']/h:.2f} "
            f"green={best['has_green']} score={best['score']:.2f}"
        )
        return {k: v for k, v in best.items() if k not in ("score", "has_green")}

    # Template fallback — reliable when OCR reject/noise kills color path.
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    for tpl, thr in (("heli_coords_link.png", 0.70), ("heli_explore_banner.png", 0.65)):
        m = find_template(gray, tpl, thr)
        if m is None:
            continue
        if m.phys_y / h < 0.28:
            continue
        heli_log(
            f"[Heli] banner template fallback {tpl} conf={m.confidence:.3f} "
            f"frac=({m.phys_x/w:.2f},{m.phys_y/h:.2f})"
        )
        return {
            "phys_x": float(m.phys_x),
            "phys_y": float(m.phys_y),
            "banner_bbox": (
                int(m.phys_x - 40),
                int(m.phys_y - 20),
                80,
                40,
            ),
            "coords_bbox": None,
            "text": f"template:{tpl}",
        }
    return None


def _step_click_coords() -> bool:
    heli_log("[Heli] Step2: Explore Treasure coords (dynamic OCR+color — no fixed position)")
    color, gray = capture_both()
    _save_raw(color, "step2_coords")
    if _is_missed_out_modal(color):
        heli_log("[Heli] FAIL: missed-out Details modal already open — aborting before banner click")
        _annotate(color, "step2_missed_out_ABORT", [])
        return False
    found = find_explore_treasure_coords(color)
    if found is None:
        heli_log("[Heli] No active Explore Treasure invite found in current frame")
        _annotate(color, "step2_coords_MISS", [])
        return False

    cx, cy = found["phys_x"], found["phys_y"]
    bx, by, bw, bh = found["banner_bbox"]
    ann = color.copy()
    cv2.rectangle(ann, (bx, by), (bx + bw, by + bh), (255, 255, 0), 2)
    cv2.circle(ann, (int(cx), int(cy)), 12, (0, 0, 255), 3)
    ts = time.strftime("%H%M%S")
    ann_path = debug_dir(_HELI_DEBUG) / f"step2_coords_dynamic_{ts}.png"
    cv2.imwrite(str(ann_path), ann)
    heli_log(f"[debug] dynamic coords annotated {ann_path} text={found['text'][:160]!r}")

    lx, ly = physical_to_logical(cx, cy)
    log_click("heli_coords", template="dynamic_ocr_color", conf=1.0,
              logical_xy=(lx, ly), phys_xy=(cx, cy))
    heli_log(f"[click] heli_coords dynamic logical=({lx:.0f},{ly:.0f})")
    click(lx, ly)
    time.sleep(2.0)
    after, _ = capture_both()
    _save_raw(after, "step2_coords_after")
    if _is_missed_out_modal(after):
        heli_log("[Heli] FAIL: banner click opened missed-out Details — wrong/old invite")
        _annotate(after, "step2_missed_out_AFTER_CLICK", [])
        return False
    return True


def _find_march_ring(gray: np.ndarray, color: np.ndarray):
    """
    Locate the circular March ring under a selected map target.
    Center-band only — no blind fraction click. Returns Match or None.
    """
    h, w = gray.shape[:2]
    thr = _thr("heli_march", 0.55)
    # Ring sits under the selection near mid-screen — exclude top chrome FPs.
    band = (0.45, 0.82, 0.32, 0.70)
    soft = find_all_templates(gray, "heli_march.png", max(0.42, thr - 0.12))
    in_band_hits = [m for m in soft if in_band(m.phys_x, m.phys_y, h, w, *band)]
    in_band_hits.sort(key=lambda m: m.confidence, reverse=True)
    if in_band_hits and in_band_hits[0].confidence >= thr:
        return in_band_hits[0]
    if in_band_hits and in_band_hits[0].confidence >= 0.48:
        heli_log(
            f"[Heli] March soft in-band conf={in_band_hits[0].confidence:.3f} "
            f"frac=({in_band_hits[0].phys_x/w:.2f},{in_band_hits[0].phys_y/h:.2f})"
        )
        return in_band_hits[0]

    # OCR "March" label in center band (Teleport/March ring under selection).
    x0, y0 = int(0.32 * w), int(0.45 * h)
    x1, y1 = int(0.70 * w), int(0.82 * h)
    for text, cx, cy in _ocr_lines(color, x0, y0, x1, y1):
        compact = re.sub(r"[^a-z]", "", text.lower())
        if compact == "march" or compact.endswith("march"):
            heli_log(f"[Heli] March OCR label at phys=({cx:.0f},{cy:.0f}) text={text!r}")
            near = [
                m
                for m in soft
                if abs(m.phys_x - cx) < 80 and abs(m.phys_y - cy) < 100
            ]
            if near:
                near.sort(key=lambda m: m.confidence, reverse=True)
                return near[0]
            from types import SimpleNamespace

            return SimpleNamespace(
                phys_x=cx,
                phys_y=cy - 20,
                confidence=0.99,
                scale=1.0,
            )
    return None


def _ocr_lines(
    color: np.ndarray, x0: int, y0: int, x1: int, y1: int, *, scale: int = 2, psm: int = 11
) -> list[tuple[str, float, float]]:
    """
    OCR a region and group word boxes into lines. Returns (text, cx, cy) in
    full-frame physical-pixel coords. Position-agnostic — caller supplies
    whatever region it needs scanned; no assumption baked in here about
    where on screen text lives.
    """
    from lastz.ocr import tesseract_available

    if not tesseract_available():
        return []
    import pytesseract
    from pytesseract import Output

    h, w = color.shape[:2]
    x0c, y0c = max(0, x0), max(0, y0)
    x1c, y1c = min(w, x1), min(h, y1)
    crop = color[y0c:y1c, x0c:x1c]
    if crop.size == 0:
        return []
    big = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    try:
        data = pytesseract.image_to_data(gray, config=f"--psm {psm}", output_type=Output.DICT)
    except Exception:
        return []
    groups: dict[tuple, list] = {}
    n = len(data.get("text", []))
    for i in range(n):
        word = data["text"][i].strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        groups.setdefault(key, []).append(
            (word, data["left"][i], data["top"][i], data["width"][i], data["height"][i])
        )
    out = []
    for words in groups.values():
        text = " ".join(wd[0] for wd in words)
        lefts = [wd[1] for wd in words]
        tops = [wd[2] for wd in words]
        rights = [wd[1] + wd[3] for wd in words]
        bottoms = [wd[2] + wd[4] for wd in words]
        bx0, by0, bx1, by1 = min(lefts), min(tops), max(rights), max(bottoms)
        cx = x0c + (bx0 + bx1) / (2.0 * scale)
        cy = y0c + (by0 + by1) / (2.0 * scale)
        out.append((text, cx, cy))
    return out


def _find_idle_formation_row(color: np.ndarray) -> tuple[float, float] | None:
    """
    Locate the idle ("Zz" sleep-indicator) formation row beside the March
    panel via OCR text — NOT the heli_zzz.png icon template, which
    false-positives heavily on background terrain (13 raw matches on trees
    seen live, zero of them near the real avatar column) and has never
    reliably hit the real badge.

    Busy rows show an HH:MM:SS/"1h53m"-style return timer instead of "Zz".
    Region is a generous band around where the March panel actually opens
    (it anchors near the empty-land click point, not a fixed screen
    fraction) rather than the old, simply-wrong right-edge-of-screen band.
    Per house rule: if multiple idle rows exist, pick the bottom-most.
    """
    h, w = color.shape[:2]
    x0, y0 = int(0.44 * w), int(0.12 * h)
    x1, y1 = int(0.68 * w), int(0.78 * h)
    lines = _ocr_lines(color, x0, y0, x1, y1)
    idle_rows = []
    for text, cx, cy in lines:
        compact = re.sub(r"[^a-z0-9]", "", text.lower())
        if compact and ("zz" in compact or compact in ("2z", "z2", "22")):
            idle_rows.append((cy, cx))
    if not idle_rows:
        return None
    idle_rows.sort(key=lambda r: r[0])
    cy, cx = idle_rows[-1]
    return (cx, cy)


def _find_march_confirm_ocr(color: np.ndarray) -> tuple[float, float] | None:
    """
    Locate the panel's blue "March" confirm button by detecting its
    distinctive blue rectangular blob (HSV) first, then OCR'ing just that
    patch with white-text brightness extraction.

    Plain grayscale OCR across the whole panel region completely missed
    "March" (return-timer / Troop Capacity text read fine, but the
    white-on-solid-blue button text did not — offline-verified). Isolating
    the button via color first fixes that. This also replaces pixel
    template matching (heli_march_confirm.png), which scored a consistent
    ~0.47 (below the 0.6 threshold) on a live capture despite matching its
    own source crop at 1.0 offline — the panel's screen position shifts
    with wherever empty-land was clicked, which pixel NCC is sensitive to
    but this color+OCR approach is not.
    """
    from lastz.ocr import tesseract_available

    if not tesseract_available():
        return None
    import pytesseract

    h, w = color.shape[:2]
    x0, y0 = int(0.35 * w), int(0.10 * h)
    x1, y1 = int(0.70 * w), int(0.95 * h)
    crop = color[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (95, 80, 80), (130, 255, 255))
    n, _labels, stats, _cents = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if area < 2000 or bw / max(bh, 1) < 1.5:
            continue
        boxes.append((bx, by, bw, bh))
    boxes.sort(key=lambda b: -(b[2] * b[3]))
    for bx, by, bw, bh in boxes[:4]:
        sub = crop[by : by + bh, bx : bx + bw]
        b, g, r = cv2.split(sub)
        white = ((r.astype(int) + g.astype(int) + b.astype(int)) > 500).astype(np.uint8) * 255
        big = cv2.resize(white, (white.shape[1] * 3, white.shape[0] * 3), interpolation=cv2.INTER_NEAREST)
        big = cv2.bitwise_not(big)
        try:
            txt = pytesseract.image_to_string(big, config="--psm 7").strip()
        except Exception:
            continue
        if re.sub(r"[^a-z]", "", txt.lower()) == "march":
            return (x0 + bx + bw / 2.0, y0 + by + bh / 2.0)
    return None


def _step_march_formation() -> bool:
    heli_log("[Heli] Step3: empty land → March → weakest zZz")
    cfg = helicopter_cfg()
    color0, _ = capture_both()
    _save_raw(color0, "step3_before_empty_land")
    if _is_missed_out_modal(color0):
        heli_log("[Heli] FAIL: missed-out modal before empty land — abort Step3")
        _annotate(color0, "step3_missed_out_ABORT", [])
        return False

    dx, dy = cfg["empty_land_offset_frac"]
    fx, fy = 0.50 + dx, 0.52 + dy
    _click_frac(fx, fy, "heli_empty_land", color0)
    time.sleep(1.2)

    color, gray = capture_both()
    _save_raw(color, "step3_after_empty_land")
    if _is_missed_out_modal(color):
        heli_log("[Heli] FAIL: missed-out modal after empty land — abort (never reached live heli)")
        _annotate(color, "step3_missed_out_AFTER_EMPTY", [])
        return False

    hit = _find_march_ring(gray, color)
    if hit is None:
        soft = find_all_templates(gray, "heli_march.png", 0.40)
        _annotate(
            color,
            "step3_march_MISS",
            [_match_dict(x, "heli_march", ok=False) for x in soft[:8]],
        )
        heli_log("[Heli] FAIL: March ring not found — no blind frac click")
        return False
    _annotate(color, "step3_march_HIT", [_match_dict(hit, "heli_march")])
    _click_match(hit, "heli_march", "heli_march.png")
    time.sleep(1.8)

    color, gray = capture_both()
    _save_raw(color, "step3_formation_panel")
    h, w = gray.shape[:2]
    thr_z = _thr("heli_zzz", 0.60)
    zs_all = find_all_templates(gray, "heli_zzz.png", max(0.45, thr_z - 0.15))
    zs = [m for m in zs_all if in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_FORMATIONS)]
    _annotate(
        color,
        "step3_zzz_scan",
        [_match_dict(m, "zzz", ok=(m in zs)) for m in zs_all[:12]],
    )

    if zs:
        zs.sort(key=lambda m: m.phys_y)
        pick = zs[-1]
        heli_log(
            f"[Heli] zZz template picks={len(zs)} choosing bottom yf={pick.phys_y/h:.2f} "
            f"conf={pick.confidence:.3f}"
        )
        _annotate(color, "step3_zzz_PICK", [_match_dict(pick, "zzz_pick", note="bottom")])
        _click_match(pick, "heli_zzz", "heli_zzz.png")
        time.sleep(0.8)
    else:
        idle_ocr = _find_idle_formation_row(color)
        if idle_ocr is not None:
            cx, cy = idle_ocr
            heli_log(f"[Heli] zZz OCR fallback: idle row at phys=({cx:.0f},{cy:.0f})")
            _annotate(
                color,
                "step3_zzz_OCR_PICK",
                [{"label": "zzz_ocr", "phys_x": int(cx), "phys_y": int(cy), "conf": 1.0, "ok": True}],
            )
            lx, ly = physical_to_logical(cx, cy)
            log_click("heli_zzz_ocr", template="ocr_text", conf=1.0, logical_xy=(lx, ly), phys_xy=(cx, cy))
            heli_log(f"[click] heli_zzz_ocr logical=({lx:.0f},{ly:.0f})")
            click(lx, ly)
            time.sleep(0.8)
        else:
            # Template AND OCR both missed. Do NOT blind-click a guessed
            # fraction here — that's exactly what dismissed the whole panel
            # last time (frac (0.94,0.28) landed nowhere near the real
            # column, which sits ~xf 0.55-0.62). The game already
            # auto-selects a default formation (visibly highlighted) when
            # the panel opens, so skipping the click and proceeding with
            # that default is safer than risking another blind miss.
            heli_log("[Heli] WARN: no zZz found (template+OCR) — keeping game's default selection, no click")
            _annotate(color, "step3_zzz_MISS", [])

    color, gray = capture_both()
    _save_raw(color, "step3_before_march_confirm")
    thr_confirm = _thr("heli_march_confirm", 0.60)
    m2 = find_template(gray, "heli_march_confirm.png", thr_confirm)
    if m2 is None:
        # Retry a few frames — dialog can take a beat to settle after the
        # formation-panel click, and a stale/mid-transition capture can miss.
        for _ in range(3):
            time.sleep(0.25)
            color, gray = capture_both()
            m2 = find_template(gray, "heli_march_confirm.png", thr_confirm)
            if m2 is not None:
                break
    if m2 is not None:
        _annotate(color, "step3_march_confirm_HIT", [_match_dict(m2, "march_confirm")])
        _click_match(m2, "heli_march_confirm", "heli_march_confirm.png")
        time.sleep(2.0)
        _save_raw(capture_both()[0], "step3_after_march")
        return True

    # Template missed — OCR the "March" word directly, position-independent.
    ocr_hit = _find_march_confirm_ocr(color)
    if ocr_hit is not None:
        cx, cy = ocr_hit
        lx, ly = physical_to_logical(cx, cy)
        log_click("heli_march_confirm_ocr", template="ocr_text", conf=1.0, logical_xy=(lx, ly), phys_xy=(cx, cy))
        heli_log(f"[click] heli_march_confirm_ocr logical=({lx:.0f},{ly:.0f})")
        _annotate(
            color,
            "step3_march_confirm_OCR_HIT",
            [{"label": "march_confirm_ocr", "phys_x": int(cx), "phys_y": int(cy), "conf": 1.0, "ok": True}],
        )
        click(lx, ly)
        time.sleep(2.0)
        _save_raw(capture_both()[0], "step3_after_march")
        return True

    soft = find_all_templates(gray, "heli_march_confirm.png", 0.35)
    _annotate(
        color,
        "step3_march_confirm_MISS",
        [_match_dict(x, "march_confirm", ok=False) for x in soft[:8]],
    )
    heli_log("[Heli] FAIL: March confirm not found (template+OCR) — no frac fallback")
    return False


class _FocusTracker:
    """
    Reasserts game focus at most every `min_interval` seconds, instead of
    on every poll (focus_game() has a fixed ~1.5s sleep — calling it every
    poll would badly hurt latency in the tight prize-window loop).

    Why this exists: a real live run had the agent doing its own
    read-only debugging in Cursor (reading files, running diagnostic
    shell commands) WHILE this exact wait loop was polling with a
    full-display capture_both(). Cursor being frontmost on the same
    screen made capture_both() photograph the Cursor IDE instead of the
    game — OCR at one point read back this very chat's own text. A
    periodic refresh here bounds how long that kind of occlusion (from
    any app, not just Cursor) can persist during a long wait.
    """

    def __init__(self) -> None:
        self.last = time.time()

    def refresh(self, min_interval: float = 30.0, force: bool = False) -> None:
        now = time.time()
        if force or (now - self.last) >= min_interval:
            focus_game()
            self.last = time.time()


def _watch_capture() -> tuple[np.ndarray, np.ndarray]:
    """
    Capture for long-running OBSERVATION polling (step4 wait, step5 prize
    wait) — prefers the off-screen window capture (immune to the game
    being occluded by another app during a long wait; see _FocusTracker
    docstring for what happened without this), falling back to the
    full-display capture only after a couple of retries, since the
    fallback is subject to exactly the occlusion problem this exists to
    avoid — confirmed live: capture_game_window_bg() returned None at
    least once mid-run, silently falling back to a Cursor-occluded
    capture_both() for that poll.
    """
    from lastz.screen import capture_game_window_bg

    for _ in range(3):
        r = capture_game_window_bg()
        if r is not None:
            return r
        time.sleep(0.15)
    return capture_both()


def _dismiss_stray_ally_popup(color: np.ndarray) -> bool:
    """
    Defensive recovery: a blind fallback click (e.g. the march-confirm
    fraction fallback) can occasionally land on a nearby alliance member's
    icon instead of the intended UI target — this happened live. It opens
    that player's info popup (Power/Kills/Alliance) and pans the camera
    away from the heli, which silently breaks Search/prize detection for
    the rest of the run since both are band-restricted around where the
    heli is expected to be. Detect that signature and press Escape to
    close it, rather than polling a stray popup for up to 2 hours.
    """
    h, w = color.shape[:2]
    text = _ocr_block(color, int(0.30 * w), int(0.10 * h), int(0.30 * w), int(0.35 * h))
    low = text.lower()
    if "power" in low and "kills" in low:
        heli_log(
            f"[Heli] WARN: stray ally info popup detected (camera likely drifted off the heli) "
            f"— dismissing: {text[:80]!r}"
        )
        press_escape()
        time.sleep(0.6)
        return True
    return False


def _find_dispatched_formation_row(color: np.ndarray) -> tuple[float, float] | None:
    """
    Locate the row for the formation already dispatched in Step 3, inside
    the formations modal that reappears after clicking Explore.

    UNVERIFIED LIVE — this modal has never been observed directly. Per
    user: select the SAME formation sent in Step 3 even if it hasn't
    arrived yet (its march is being retargeted to enter the heli, not
    restarted), so unlike Step 3's idle-row search this looks for a BUSY
    row (a return-timer-like string, NOT "Zz") — our dispatched formation
    is presumably the only non-idle entry relevant here. Mirrors
    _find_idle_formation_row's OCR-row-scanning approach and region guess
    (same relative area as the March panel — unverified for this specific
    modal, may need retuning once actually seen).
    """
    h, w = color.shape[:2]
    x0, y0 = int(0.44 * w), int(0.12 * h)
    x1, y1 = int(0.68 * w), int(0.78 * h)
    lines = _ocr_lines(color, x0, y0, x1, y1)
    busy_rows = []
    for text, cx, cy in lines:
        compact = re.sub(r"[^a-z0-9]", "", text.lower())
        if not compact or "zz" in compact or compact in ("2z", "z2", "22"):
            continue
        if re.search(r"\d", text) and (":" in text or re.search(r"\d\s*[hm]\b", text.lower())):
            busy_rows.append((cy, cx))
    if not busy_rows:
        return None
    busy_rows.sort(key=lambda r: r[0])
    cy, cx = busy_rows[0]
    return (cx, cy)


def _find_enter_confirm_ocr(color: np.ndarray) -> tuple[float, float] | None:
    """
    Locate the confirm button in the reappeared formations modal. Reuses
    _find_march_confirm_ocr's proven blue-blob + OCR isolation approach,
    but accepts a broader set of possible labels since this modal's exact
    button text is unverified live (could repeat "March", or say
    "Confirm"/"Enter"/etc).
    """
    from lastz.ocr import tesseract_available

    if not tesseract_available():
        return None
    import pytesseract

    h, w = color.shape[:2]
    x0, y0 = int(0.35 * w), int(0.10 * h)
    x1, y1 = int(0.70 * w), int(0.95 * h)
    crop = color[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (95, 80, 80), (130, 255, 255))
    n, _labels, stats, _cents = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if area < 2000 or bw / max(bh, 1) < 1.5:
            continue
        boxes.append((bx, by, bw, bh))
    boxes.sort(key=lambda b: -(b[2] * b[3]))
    candidates = {"march", "confirm", "enter", "explore", "ok", "go"}
    for bx, by, bw, bh in boxes[:4]:
        sub = crop[by : by + bh, bx : bx + bw]
        b, g, r = cv2.split(sub)
        white = ((r.astype(int) + g.astype(int) + b.astype(int)) > 500).astype(np.uint8) * 255
        big = cv2.resize(white, (white.shape[1] * 3, white.shape[0] * 3), interpolation=cv2.INTER_NEAREST)
        big = cv2.bitwise_not(big)
        try:
            txt = pytesseract.image_to_string(big, config="--psm 7").strip()
        except Exception:
            continue
        if re.sub(r"[^a-z]", "", txt.lower()) in candidates:
            return (x0 + bx + bw / 2.0, y0 + by + bh / 2.0)
    return None


def _step_enter_heli_formation() -> bool:
    """
    After clicking Explore, a formations modal reappears (confirmed live)
    — per user, select the SAME formation already dispatched in Step 3
    (its march is retargeted to enter the heli, not restarted, so it may
    still show as busy/en-route rather than idle), then confirm. Only
    after this does the formation actually enter the heli.

    UNVERIFIED LIVE beyond that description — never seen this exact modal.
    Mirrors Step 3's safety philosophy: if the target row can't be
    confidently identified, don't blind-click a guess; rely on the game's
    default selection (likely already correct, since only one formation
    is plausibly relevant here) and proceed straight to confirming.

    Non-fatal by design: caller should treat a False return as "log and
    continue", not abort the whole flow — the user is running this fully
    autonomously and won't be watching to manually restart it.
    """
    time.sleep(0.8)
    color, gray = capture_both()
    _save_raw(color, "step4b_enter_formation_panel")

    row = _find_dispatched_formation_row(color)
    if row is not None:
        cx, cy = row
        lx, ly = physical_to_logical(cx, cy)
        heli_log(f"[Heli] dispatched-formation row found at phys=({cx:.0f},{cy:.0f})")
        _annotate(
            color,
            "step4b_formation_row_PICK",
            [{"label": "dispatched_row", "phys_x": int(cx), "phys_y": int(cy), "conf": 1.0, "ok": True}],
        )
        log_click("heli_enter_formation_row", template="ocr_text", conf=1.0, logical_xy=(lx, ly), phys_xy=(cx, cy))
        click(lx, ly)
        time.sleep(0.6)
        color, gray = capture_both()
    else:
        heli_log("[Heli] WARN: dispatched-formation row not identified — keeping game's default selection")
        _annotate(color, "step4b_formation_row_MISS", [])

    _save_raw(color, "step4b_before_enter_confirm")
    ocr_hit = _find_enter_confirm_ocr(color)
    if ocr_hit is not None:
        cx, cy = ocr_hit
        lx, ly = physical_to_logical(cx, cy)
        heli_log(f"[click] heli_enter_confirm_ocr logical=({lx:.0f},{ly:.0f})")
        _annotate(
            color,
            "step4b_enter_confirm_OCR_HIT",
            [{"label": "enter_confirm_ocr", "phys_x": int(cx), "phys_y": int(cy), "conf": 1.0, "ok": True}],
        )
        log_click("heli_enter_confirm_ocr", template="ocr_text", conf=1.0, logical_xy=(lx, ly), phys_xy=(cx, cy))
        click(lx, ly)
        time.sleep(1.5)
        _save_raw(capture_both()[0], "step4b_after_enter_confirm")
        return True

    # Fall back to the same template used for March's confirm button, in
    # case this modal reuses that exact asset.
    thr_confirm = _thr("heli_march_confirm", 0.6)
    m2 = find_template(gray, "heli_march_confirm.png", thr_confirm)
    if m2 is not None:
        _annotate(color, "step4b_enter_confirm_HIT", [_match_dict(m2, "enter_confirm")])
        _click_match(m2, "heli_enter_confirm", "heli_march_confirm.png")
        time.sleep(1.5)
        _save_raw(capture_both()[0], "step4b_after_enter_confirm")
        return True

    heli_log(
        "[Heli] WARN: could not find confirm button in reappeared formations modal — "
        "saved step4b_before_enter_confirm for review"
    )
    _save_raw(color, "step4b_enter_confirm_MISS")
    return False


def _read_heli_timer(color: np.ndarray, *, save_rois: bool = False) -> int | None:
    """OCR HH:MM:SS above centered heli / Search."""
    h, w = color.shape[:2]
    bands = [
        (int(0.38 * w), int(0.22 * h), int(0.24 * w), int(0.12 * h)),
        (int(0.42 * w), int(0.28 * h), int(0.20 * w), int(0.10 * h)),
        (int(0.35 * w), int(0.18 * h), int(0.30 * w), int(0.18 * h)),
    ]
    for i, (x, y, bw, bh) in enumerate(bands):
        if save_rois:
            _save_roi(color, f"timer_roi_{i}", x, y, bw, bh)
        sec = read_duration_from_region(color, x, y, bw, bh)
        if sec is not None:
            return sec
    return None


def _find_search(gray: np.ndarray):
    """
    Green floating icon shown BEFORE the heli has been clicked — no text
    label, timer floats above it. Confirmed live this is a different visual
    state from the actual clickable button (see _find_explore_button()):
    clicking the heli first is required, which swaps this for a white icon
    with an "Explore" text label below it. Kept as a signal for "we've
    arrived and something is here", band-checked to avoid the false
    positive an earlier unbanded fallback caused on an unrelated popup.
    """
    thr = _thr("heli_search", 0.65)
    h, w = gray.shape[:2]
    m = find_template(gray, "heli_search.png", thr)
    if m is not None and in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_CENTER):
        return m
    m = find_template(gray, "heli_search.png", max(0.55, thr - 0.1))
    if m is not None and in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_CENTER):
        return m
    return None


def _find_heli_model(gray: np.ndarray):
    """
    The helicopter sprite itself — confirmed live this IS the required
    first click: it opens a modal (Exploring NN%, Exploration Speed,
    countdown) and, below that modal, swaps the green icon for a white
    "Explore" button that must be clicked next (see _find_explore_button()).
    Template is a tight crop of just the fuselage/cockpit, deliberately
    excluding the rotor blades (their spin angle varies frame-to-frame and
    would hurt template matching).
    """
    thr = _thr("heli_model", 0.6)
    h, w = gray.shape[:2]
    m = find_template(gray, "heli_model.png", thr)
    if m is not None and in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_CENTER):
        return m
    m = find_template(gray, "heli_model.png", max(0.45, thr - 0.15))
    if m is not None and in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_CENTER):
        return m
    return None


def _find_explore_button(color: np.ndarray, gray: np.ndarray):
    """
    The actual clickable button — a white circle/magnifying-glass icon with
    an "Explore" text label below it, which only appears after clicking the
    heli model (see _find_heli_model()). Visually distinct from the earlier
    green heli_search.png icon: white fill vs green, and has a text label.
    Template cropped and confidence-verified (0.9999) from a real capture
    where this exact state was missed live — the earlier code was (a)
    matching against the wrong-colored template and (b) OCR-searching for
    the word "search" when the real label is "Explore".
    """
    thr = _thr("heli_explore_white", 0.6)
    h, w = gray.shape[:2]
    m = find_template(gray, "heli_explore_white.png", thr)
    if m is not None and in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_CENTER):
        return m
    m = find_template(gray, "heli_explore_white.png", max(0.45, thr - 0.15))
    if m is not None and in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_CENTER):
        return m
    lines = _ocr_lines(color, int(0.25 * w), int(0.15 * h), int(0.75 * w), int(0.85 * h))
    for text, cx, cy in lines:
        if "explore" in text.strip().lower() and in_band(cx, cy, h, w, *BAND_HELI_CENTER):
            return (cx, cy)
    return None


def _step_wait_and_search() -> bool:
    """
    Two-step click, confirmed live: (1) click the heli model itself, which
    opens a status modal AND swaps the green "not yet" icon for a white
    "Explore" button below it; (2) click that white Explore button. An
    earlier attempt skipped step 1 (clicking the green icon directly) and
    a later attempt clicked the heli but then searched for the WRONG
    button (wrong template color, and OCR for "search" instead of the
    actual "Explore" label) — both cost real misses.

    Gate: confirmed live that this formation's own march/travel timer can
    still read ~5 minutes while the *shared* explore progress (from
    whichever alliance members already arrived) is already near 100% and
    about to expire — waiting for search_max_sec=5:00 was too late.
    search_max_sec is now 20:00 so the click fires earlier.
    """
    cfg = helicopter_cfg()
    max_wait = cfg["wait_search_timeout_sec"]
    gate = cfg["search_max_sec"]
    heli_log(f"[Heli] Step4: wait timer ≤ {format_duration(gate)} then click heli → Explore")
    t0 = time.time()
    searched = False
    last_dump = 0.0
    focus = _FocusTracker()
    while time.time() - t0 < max_wait:
        focus.refresh(min_interval=30.0)
        color, gray = _watch_capture()
        if _dismiss_stray_ally_popup(color):
            color, gray = _watch_capture()
        now = time.time()
        dump = (now - last_dump) >= 15.0 or last_dump == 0.0
        if dump:
            last_dump = now
            _save_raw(color, "step4_wait")
            sec = _read_heli_timer(color, save_rois=True)
        else:
            sec = _read_heli_timer(color, save_rois=False)
        if sec is not None:
            heli_log(f"[Heli] timer={format_duration(sec)}")

        ready = sec is not None and sec <= gate
        # Timer OCR can fail outright; don't wait the full 2h timeout blind
        # once we're well past when the gate should have arrived.
        stalled = sec is None and (time.time() - t0) > max(60, gate + 30)
        if ready or stalled:
            if stalled:
                heli_log("[Heli] WARN: timer OCR never resolved — proceeding on elapsed-time fallback")
            # Re-verify with an authoritative, freshly-focused full-display
            # capture right before clicking — the observation loop above
            # may have used the occlusion-proof window capture, and this is
            # the moment a real click is about to fire, so it must be
            # correct.
            focus.refresh(force=True)
            color2, gray2 = capture_both()
            model = _find_heli_model(gray2)
            if model is None:
                heli_log("[Heli] heli model not found at gate — continuing to wait")
                time.sleep(1.0)
                continue
            _annotate(color2, "step4_heli_click_HIT", [_match_dict(model, "heli_model")])
            _click_match(model, "heli_model", "heli_model.png")
            time.sleep(1.2)

            color3, gray3 = capture_both()
            _save_raw(color3, "step4_after_heli_click_modal")
            btn = _find_explore_button(color3, gray3)
            if btn is None:
                # Retry once — modal/button can take a beat to render.
                time.sleep(0.6)
                color3, gray3 = capture_both()
                _save_raw(color3, "step4_after_heli_click_modal_retry")
                btn = _find_explore_button(color3, gray3)
            if btn is not None:
                if isinstance(btn, tuple):
                    cx, cy = btn
                    lx, ly = physical_to_logical(cx, cy)
                    log_click("heli_explore_ocr", template="ocr_text", conf=1.0, logical_xy=(lx, ly), phys_xy=(cx, cy))
                    heli_log(f"[click] heli_explore_ocr logical=({lx:.0f},{ly:.0f})")
                    _annotate(
                        color3,
                        "step4_explore_OCR_HIT",
                        [{"label": "explore_ocr", "phys_x": int(cx), "phys_y": int(cy), "conf": 1.0, "ok": True}],
                    )
                    click(lx, ly)
                else:
                    _annotate(color3, "step4_explore_HIT", [_match_dict(btn, "explore")])
                    _click_match(btn, "heli_explore", "heli_explore_white.png")
                time.sleep(1.5)
                _save_raw(capture_both()[0], "step4_after_search")
                searched = True
                break
            heli_log(
                "[Heli] WARN: clicked heli model but Explore button not found — "
                "saved step4_after_heli_click_modal(_retry) for review"
            )
            _save_raw(capture_both()[0], "step4_explore_MISS")
        time.sleep(1.0)

    if not searched:
        heli_log("[Heli] Search gate timed out / not clicked")
        color, gray = capture_both()
        soft = find_all_templates(gray, "heli_explore_white.png", 0.45)
        _annotate(color, "step4_search_TIMEOUT", [_match_dict(m, "search", ok=False) for m in soft[:8]])
        _save_raw(color, "step4_search_TIMEOUT")
        return False
    return True


_PRIZE_CLAIM_RE = re.compile(r"(?<!\d)(?:[0-9]|10)\s*/\s*10(?!\d)")


def _find_prize(gray: np.ndarray, color: np.ndarray):
    """
    Prize bubble only ever appears centered over the heli. Both the template
    match and the OCR fallback previously accepted a hit anywhere on screen
    with no location or content-shape check — that false-positived on
    unrelated Alliance-chat reward text mentioning "9/10" and fired a bogus
    claim burst. Now: template must be in the center band; OCR fallback must
    be a short claim-count label (not a long scrolled text block) matching
    N/10 as a standalone token.
    """
    thr = _thr("heli_prize", 0.60)
    h, w = gray.shape[:2]
    m = find_template(gray, "heli_prize_bubble.png", thr)
    if m is not None and in_band(m.phys_x, m.phys_y, h, w, *BAND_HELI_CENTER):
        return m
    rx, ry, rw, rh = int(0.35 * w), int(0.35 * h), int(0.35 * w), int(0.40 * h)
    text = read_ui_text(color, rx, ry, rw, rh)
    compact = text.replace(" ", "")
    if len(text) > 60:
        return None
    if _PRIZE_CLAIM_RE.search(compact):
        heli_log(f"[Heli] prize OCR hit: {text!r}")
        return "ocr"
    return None


def _step_prize_burst() -> bool:
    """
    The claim window is extremely short live — confirmed by direct
    observation, barely visible "for a blink of a second" even to a human,
    especially during busy periods. A single reactively-timed burst is too
    fragile: by the time one poll cycle (capture + OCR/template match,
    hundreds of ms) confirms the window is open, it may already be
    closing. Strategy: once we're within a few seconds of the predicted
    moment (by countdown timer OR an actual prize sighting, whichever
    comes first), stop trying to precisely time a single shot and instead
    fire repeated rapid-click bursts continuously for several seconds
    spanning the predicted instant. Clicking empty map when nothing is
    there is harmless, so over-firing across the window has no downside
    and hugely raises the odds of overlapping the real, sub-second window
    despite OCR/timing imprecision.
    """
    cfg = helicopter_cfg()
    heli_log("[Heli] Step5: wait prize then sustained rapid-click burst")
    t0 = time.time()
    timeout = cfg["wait_prize_timeout_sec"]
    prize_at = cfg["prize_at_sec"]
    burst_span = cfg.get("prize_burst_span_sec", 8.0)
    n = cfg["prize_clicks"]
    gap = cfg["prize_interval"]
    color = None
    last_dump = 0.0
    focus = _FocusTracker()
    switched_to_authoritative = False
    in_burst_zone = False
    burst_zone_start = 0.0
    lx, ly = window_click(0.52, 0.55)  # default center target (logical/OS coords), refined below if a real hit is found
    ann_px, ann_py = None, None  # physical-pixel coords for debug annotation only

    while time.time() - t0 < timeout:
        focus.refresh(min_interval=20.0)
        if switched_to_authoritative or in_burst_zone:
            color, gray = capture_both()
        else:
            color, gray = _watch_capture()
        if not in_burst_zone and _dismiss_stray_ally_popup(color):
            continue
        sec = _read_heli_timer(color)
        if not switched_to_authoritative and sec is not None and sec <= prize_at + 5:
            heli_log(f"[Heli] prize window approaching (timer={format_duration(sec)}) — refocusing early")
            focus.refresh(force=True)
            switched_to_authoritative = True
            continue

        prize = _find_prize(gray, color)
        if prize is not None and not isinstance(prize, str):
            lx, ly = physical_to_logical(prize.phys_x, prize.phys_y)
            ann_px, ann_py = int(prize.phys_x), int(prize.phys_y)

        if time.time() - last_dump >= 10.0:
            last_dump = time.time()
            _save_raw(color, "step5_prize_wait")

        if not in_burst_zone and ((sec is not None and sec <= prize_at + 2) or prize is not None):
            in_burst_zone = True
            burst_zone_start = time.time()
            _annotate(color, "step5_prize_burst_ZONE_ENTER", [])
            heli_log(
                f"[Heli] entering sustained burst window (timer={sec}, prize_signal={prize is not None}) "
                f"— clicking continuously for up to {burst_span:.0f}s"
            )

        if in_burst_zone:
            heli_log(f"[Heli] rapid_click n={n} interval={gap} at ({lx:.0f},{ly:.0f})")
            rapid_click(lx, ly, count=n, interval=gap)
            if time.time() - burst_zone_start > burst_span:
                heli_log("[Heli] sustained burst window elapsed — stopping")
                break
            continue
        time.sleep(0.15)

    if color is None:
        color, _ = capture_both()
    if ann_px is None:
        h, w = color.shape[:2]
        ann_px, ann_py = int(0.52 * w), int(0.55 * h)
    _annotate(
        color,
        "step5_prize_click_point",
        [{"label": "burst", "phys_x": ann_px, "phys_y": ann_py, "conf": 1.0, "ok": True}],
    )

    time.sleep(1.5)
    _save_raw(capture_both()[0], "step5_after_burst")
    dismiss_overlay(delay=0.8)
    dismiss_overlay(delay=0.8)
    _save_raw(capture_both()[0], "step5_after_dismiss")
    return True


def _step_thank_you() -> bool:
    cfg = helicopter_cfg()
    text = cfg["thank_you_text"]
    heli_log("[Heli] Step6: thank-you chat")
    color0, _ = capture_both()
    _save_raw(color0, "step6_before_chat")
    _click_frac(0.22, 0.92, "heli_chat_overlay", color0)
    time.sleep(1.5)

    color, gray = capture_both()
    _save_raw(color, "step6_chat_open")
    thr = _thr("heli_alliance_tab", 0.65)
    tab = find_template(gray, "heli_alliance_tab.png", thr)
    if tab is not None:
        _annotate(color, "step6_alliance_HIT", [_match_dict(tab, "alliance_tab")])
        _click_match(tab, "heli_alliance_tab", "heli_alliance_tab.png")
        time.sleep(0.8)
    else:
        soft = find_all_templates(gray, "heli_alliance_tab.png", 0.45)
        _annotate(color, "step6_alliance_MISS", [_match_dict(m, "alliance", ok=False) for m in soft[:6]])
        _click_frac(0.48, 0.14, "heli_alliance_tab_frac", color)
        time.sleep(0.8)

    color, _ = capture_both()
    _save_raw(color, "step6_before_input")
    _click_frac(0.42, 0.88, "heli_chat_input", color)
    time.sleep(0.4)
    paste_text(text)
    time.sleep(0.2)
    press_return()
    time.sleep(0.8)
    _save_raw(capture_both()[0], "step6_after_send")
    press_escape()
    time.sleep(0.5)
    _save_raw(capture_both()[0], "step6_after_close")
    heli_log(f"[Heli] thank-you sent: {text!r}")
    return True


def run_helicopter_flow(*, source: str = "watcher") -> str:
    """
    Full Helicopter priority flow. Clears heli_pending when done.
    Returns status string.
    """
    cfg = helicopter_cfg()
    if not cfg["enabled"]:
        return "skipped: helicopter.enabled=false"

    heli_log("=" * 50)
    heli_log(f"HELICOPTER FLOW START source={source}")
    heli_log("=" * 50)
    log_step("Heli", "info", f"start:{source}")

    try:
        ensure_game_running()
        focus_game()
        # If a prior Escape left Quit Tips up, Cancel it before BR/chat work.
        if dismiss_quit_tips_if_present():
            heli_log("[Heli] cleared Quit Tips at flow start")
        color, gray = capture_both()
        ensure_template_scale(gray)
        _save_raw(color, "flow_start")

        opened = _step_open_from_br()
        if opened:
            if not _step_click_coords():
                log_step("Heli", "fail", "coords")
                _save_raw(capture_both()[0], "flow_fail_coords")
                return "failed: coords"
        else:
            heli_log("[Heli] BR miss — trying coords/search on current screen")
            _annotate(capture_both()[0], "flow_br_miss_continue", [])
            if not _step_click_coords():
                heli_log("[Heli] FAIL: coords also failed after BR miss")
                log_step("Heli", "fail", "coords")
                _save_raw(capture_both()[0], "flow_fail_coords")
                return "failed: coords"

        if not _step_march_formation():
            log_step("Heli", "fail", "march")
            _save_raw(capture_both()[0], "flow_fail_march")
            return "failed: march"

        # A blind fallback click during march (e.g. the march-confirm
        # fraction fallback) can land on a nearby alliance member's icon
        # instead of the intended target, panning the camera away from the
        # heli — this happened live and silently broke every band-restricted
        # check downstream. Check for and recover from that signature before
        # committing to the long Step4 wait.
        color, _ = capture_both()
        if _dismiss_stray_ally_popup(color):
            heli_log("[Heli] WARN: recovered from stray popup right after march — verifying camera")
            _save_raw(capture_both()[0], "flow_post_march_drift_recovery")

        if not _step_wait_and_search():
            log_step("Heli", "fail", "search")
            _save_raw(capture_both()[0], "flow_fail_search")
            return "failed: search"

        # Non-fatal: clicking Explore reopens a formations modal that must
        # be confirmed before the formation actually enters the heli (per
        # user). If this can't be confidently completed, log and continue
        # anyway rather than abort — running fully autonomously now, so
        # there's no one watching to manually recover a hard failure here,
        # and the prize/thank-you steps are still worth attempting either way.
        if not _step_enter_heli_formation():
            log_step("Heli", "warn", "enter_formation")

        _step_prize_burst()
        _step_thank_you()

        log_step("Heli", "pass", "complete")
        heli_log("HELICOPTER FLOW COMPLETE")
        _save_raw(capture_both()[0], "flow_complete")
        return "complete"
    except GameNotRunningError:
        raise
    except Exception as e:
        heli_log(f"HELICOPTER FATAL: {e}")
        log_step("Heli", "fail", str(e))
        try:
            dump_crash(e, prefix="crash_heli")
        except Exception:
            pass
        raise
    finally:
        clear_heli()


def run_helicopter_monitor_loop() -> None:
    """Menu: constant BR watch; run full heli flow when spotted."""
    cfg = helicopter_cfg()
    poll = cfg["poll_sec"]
    heli_log("=" * 50)
    heli_log("HELICOPTER MONITOR (menu) STARTED")
    heli_log(f"poll={poll}s enabled={cfg['enabled']}")
    heli_log("=" * 50)
    try:
        ensure_game_running()
        focus_game()
    except GameNotRunningError as e:
        heli_log(str(e))
        return

    while True:
        try:
            if not is_game_running():
                time.sleep(2.0)
                continue
            if poll_br_heli_once() or heli_pending():
                heli_log(">>> Heli indication — running flow")
                run_helicopter_flow(source="menu")
                heli_log(">>> Heli done — resume monitoring")
            time.sleep(poll)
        except KeyboardInterrupt:
            heli_log("Helicopter monitor stopped by user.")
            break
        except GameNotRunningError as e:
            heli_log(f"GAME NOT RUNNING: {e}")
            time.sleep(3.0)
        except Exception as e:
            heli_log(f"ERROR: {e}")
            time.sleep(2.0)
