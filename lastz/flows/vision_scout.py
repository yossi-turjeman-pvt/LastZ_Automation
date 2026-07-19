"""
Observe-only vision scout — navigate menus, never Claim / Donate.

Run:
  python -m lastz.flows.vision_scout

Requires LastZ visible. Writes annotated dumps + report under logs/debug/scout/.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from lastz.config import threshold as cfg_threshold
from lastz.debug_match import annotate_and_save, debug_dir, match_row
from lastz.flows.base import dismiss_overlay, ensure_wilderness, reset_ui
from lastz.input import click, ensure_game_running, focus_game
from lastz.screen import capture, capture_both, physical_to_logical
from lastz.vision import click_template, find_all_templates, find_template

# Proposed bands (game capture fractions) — scout reports IN_BAND vs these.
BANDS = {
    "rare_tab": (0.02, 0.22, 0.25, 0.75),       # y0,y1,x0,x1
    "alliance_grid": (0.30, 0.75, 0.15, 0.85),
    "tech_tree": (0.12, 0.70, 0.15, 0.85),
    "hud_shield": (0.55, 0.95, 0.75, 1.0),
    "claim_list": (0.0, 0.48, 0.0, 1.0),
}


def _orange_ratio(bgr: np.ndarray) -> float:
    if bgr is None or bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (5, 80, 80), (30, 255, 255))
    return float(mask.mean()) / 255.0


def _green_ratio(bgr: np.ndarray) -> float:
    if bgr is None or bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (35, 50, 50), (95, 255, 255))
    return float(mask.mean()) / 255.0


def _blue_ratio(bgr: np.ndarray) -> float:
    if bgr is None or bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (95, 60, 50), (140, 255, 255))
    return float(mask.mean()) / 255.0


def _roi(color: np.ndarray, m) -> np.ndarray:
    h, w = color.shape[:2]
    half_w = max(8, getattr(m, "phys_w", 40) // 2)
    half_h = max(8, getattr(m, "phys_h", 40) // 2)
    x1 = max(0, int(m.phys_x - half_w))
    y1 = max(0, int(m.phys_y - half_h))
    x2 = min(w, int(m.phys_x + half_w))
    y2 = min(h, int(m.phys_y + half_h))
    return color[y1:y2, x1:x2]


def _probe(
    step: str,
    templates: list[tuple[str, float, str | None]],
    *,
    color: np.ndarray | None = None,
    gray: np.ndarray | None = None,
    hsv_fn=None,
    hsv_name: str = "",
    use_all: bool = False,
) -> list[dict]:
    """templates: (name, threshold, band_key or None)."""
    if color is None or gray is None:
        color, gray = capture_both()
    h, w = gray.shape[:2]
    rows: list[dict] = []
    ann: list[dict] = []

    print(f"\n[Scout] === {step} ({w}x{h}) ===")
    for name, thr, band_key in templates:
        band = BANDS.get(band_key) if band_key else None
        if use_all or name in (
            "claim_button_clean.png",
            "tech_thumbs_up.png",
            "tech_hex_active.png",
            "donate_blue.png",
        ):
            matches = find_all_templates(gray, name, thr)
            if not matches:
                # Still try single find for logging best below threshold via find_template
                m = find_template(gray, name, 0.0)  # won't return below... use thr low
                print(f"  {name}: no matches >= {thr}")
                continue
            for m in matches[:8]:
                extra = ""
                if hsv_fn is not None:
                    ratio = hsv_fn(_roi(color, m))
                    extra = f"{hsv_name}={ratio:.3f}"
                row = match_row(
                    name,
                    m.phys_x,
                    m.phys_y,
                    m.confidence,
                    h,
                    w,
                    phys_w=m.phys_w,
                    phys_h=m.phys_h,
                    band=band,
                    extra=extra,
                )
                rows.append(row)
                ann.append(row)
                print(
                    f"  {name}: conf={m.confidence:.4f} phys=({m.phys_x:.0f},{m.phys_y:.0f}) "
                    f"log=({row['logical'][0]:.0f},{row['logical'][1]:.0f}) "
                    f"frac=({row['x_frac']:.2f},{row['y_frac']:.2f}) "
                    f"band={'OK' if row['in_band'] else 'OUT'} {extra}"
                )
        else:
            m = find_template(gray, name, thr)
            if m is None:
                # Log best effort at lower threshold for diagnosis
                soft = find_template(gray, name, 0.40)
                if soft is None:
                    print(f"  {name}: MISS (thr={thr})")
                else:
                    row = match_row(
                        name,
                        soft.phys_x,
                        soft.phys_y,
                        soft.confidence,
                        h,
                        w,
                        band=band,
                        extra="BELOW_THR",
                    )
                    rows.append(row)
                    ann.append({**row, "ok": False})
                    print(
                        f"  {name}: BELOW thr={thr} best={soft.confidence:.4f} "
                        f"phys=({soft.phys_x:.0f},{soft.phys_y:.0f}) "
                        f"frac=({row['x_frac']:.2f},{row['y_frac']:.2f}) "
                        f"band={'OK' if row['in_band'] else 'OUT'}"
                    )
                continue
            extra = ""
            if hsv_fn is not None:
                # Match has no bbox — approximate
                class _M:
                    pass
                mm = _M()
                mm.phys_x, mm.phys_y, mm.phys_w, mm.phys_h = m.phys_x, m.phys_y, 60, 40
                ratio = hsv_fn(_roi(color, mm))
                extra = f"{hsv_name}={ratio:.3f}"
            row = match_row(
                name,
                m.phys_x,
                m.phys_y,
                m.confidence,
                h,
                w,
                band=band,
                extra=extra,
            )
            rows.append(row)
            ann.append(row)
            print(
                f"  {name}: conf={m.confidence:.4f} phys=({m.phys_x:.0f},{m.phys_y:.0f}) "
                f"log=({row['logical'][0]:.0f},{row['logical'][1]:.0f}) "
                f"frac=({row['x_frac']:.2f},{row['y_frac']:.2f}) "
                f"band={'OK' if row['in_band'] else 'OUT'} {extra}"
            )

    annotate_and_save(color, step, ann, subdir="scout")
    return rows


def run_vision_scout() -> Path:
    ensure_game_running()
    focus_game()
    out_dir = debug_dir("scout")
    report_lines: list[str] = ["# Vision scout report", ""]

    def add_section(title: str, rows: list[dict]) -> None:
        report_lines.append(f"## {title}")
        if not rows:
            report_lines.append("- (no matches)")
        for r in rows:
            report_lines.append(
                f"- `{r['template']}` conf={r['conf']:.4f} "
                f"phys=({r['phys_x']:.0f},{r['phys_y']:.0f}) "
                f"frac=({r['x_frac']:.2f},{r['y_frac']:.2f}) "
                f"band={'OK' if r['in_band'] else 'OUT'} {r.get('extra','')}"
            )
        report_lines.append("")

    print("[Scout] Observe-only — will NOT Claim or Donate.")
    print("Resetting UI...")
    reset_ui(clicks=3, delay=1.2)
    map_status = ensure_wilderness()
    print(f"[Scout] map → {map_status}")

    # Battlefield — report only
    rows = _probe(
        "01_wilderness",
        [
            ("orange_icon_no_badge.png", cfg_threshold("orange_icon"), None),
            ("alliance_shield_clean.png", cfg_threshold("alliance_shield"), "hud_shield"),
            ("hq_world_button.png", cfg_threshold("hq_world_button"), None),
            ("wilderness_hq_button.png", cfg_threshold("hq_world_button"), None),
        ],
    )
    add_section("Wilderness HUD", rows)

    print("[Scout] Opening Alliance...")
    if click_template(
        "alliance_shield_clean.png",
        cfg_threshold("alliance_shield"),
        label="Alliance (nav)",
    ) is None:
        raise RuntimeError("Alliance shield not found — cannot scout")
    time.sleep(2.0)

    rows = _probe(
        "02_alliance_menu",
        [
            ("alliance_gifts_precise.png", cfg_threshold("alliance_gifts"), "alliance_grid"),
            ("alliance_techs.png", cfg_threshold("alliance_techs"), "alliance_grid"),
            ("alliance_techs_label.png", cfg_threshold("alliance_techs"), "alliance_grid"),
            ("alliance_shield_clean.png", cfg_threshold("alliance_shield"), "hud_shield"),
        ],
    )
    add_section("Alliance menu", rows)

    print("[Scout] Opening Alliance Gifts (nav only)...")
    if click_template(
        "alliance_gifts_precise.png",
        cfg_threshold("alliance_gifts"),
        label="Alliance Gifts (nav)",
    ) is None:
        raise RuntimeError("Alliance Gifts not found")
    time.sleep(2.0)

    rows = _probe(
        "03_gifts_common",
        [
            ("rare_tab.png", cfg_threshold("rare_tab"), "rare_tab"),
            ("claim_all_button_clean.png", cfg_threshold("claim_all"), None),
            ("universal_claim_all_button.png", cfg_threshold("claim_all"), None),
            ("claim_button_clean.png", cfg_threshold("claim_button"), "claim_list"),
        ],
        hsv_fn=_green_ratio,
        hsv_name="green",
        use_all=True,
    )
    add_section("Gifts Common (before Rare click)", rows)

    print("[Scout] Clicking Rare tab (nav only — no Claim)...")
    rare = click_template("rare_tab.png", cfg_threshold("rare_tab"), label="Rare tab (nav)")
    if rare is None:
        print("[Scout] WARN: rare_tab not found at threshold")
    time.sleep(2.0)

    rows = _probe(
        "04_gifts_rare",
        [
            ("rare_tab.png", cfg_threshold("rare_tab"), "rare_tab"),
            ("claim_all_button_clean.png", cfg_threshold("claim_all"), None),
            ("universal_claim_all_button.png", cfg_threshold("claim_all"), None),
            ("claim_button_clean.png", cfg_threshold("claim_button"), "claim_list"),
        ],
        hsv_fn=_green_ratio,
        hsv_name="green",
        use_all=True,
    )
    add_section("Gifts Rare (after Rare click)", rows)

    print("[Scout] Dismissing Gifts...")
    dismiss_overlay(delay=2.0)

    rows = _probe(
        "05_after_gifts_dismiss",
        [
            ("alliance_techs.png", cfg_threshold("alliance_techs"), "alliance_grid"),
            ("alliance_techs_label.png", cfg_threshold("alliance_techs"), "alliance_grid"),
            ("alliance_gifts_precise.png", cfg_threshold("alliance_gifts"), "alliance_grid"),
            ("alliance_shield_clean.png", cfg_threshold("alliance_shield"), "hud_shield"),
        ],
    )
    add_section("After Gifts dismiss", rows)

    # Open Techs — prefer microscope, then label (nav only)
    print("[Scout] Opening Alliance Techs (nav only)...")
    color, gray = capture_both()
    h, w = gray.shape[:2]
    techs_m = find_template(gray, "alliance_techs.png", cfg_threshold("alliance_techs"))
    label_m = find_template(gray, "alliance_techs_label.png", cfg_threshold("alliance_techs"))
    opened = False
    for cand, tag in ((techs_m, "techs_icon"), (label_m, "techs_label")):
        if cand is None:
            continue
        yf = cand.phys_y / h
        xf = cand.phys_x / w
        print(f"[Scout] Techs candidate {tag} conf={cand.confidence:.4f} frac=({xf:.2f},{yf:.2f})")
        # Prefer mid-screen for scout nav
        if 0.25 <= yf <= 0.80:
            lx, ly = physical_to_logical(cand.phys_x, cand.phys_y)
            print(f"[Scout] Clicking {tag} at logical ({lx:.0f},{ly:.0f})")
            click(lx, ly)
            opened = True
            break
    if not opened:
        print("[Scout] WARN: no mid-band Techs match — trying click_template icon then label")
        if click_template("alliance_techs.png", cfg_threshold("alliance_techs"), label="Techs icon") is None:
            click_template(
                "alliance_techs_label.png",
                cfg_threshold("alliance_techs"),
                label="Techs label",
            )
    time.sleep(2.0)

    rows = _probe(
        "06_techs_tree",
        [
            ("tech_thumbs_up.png", cfg_threshold("tech_thumbs_up"), "tech_tree"),
            ("tech_hex_active.png", cfg_threshold("tech_hex_active"), "tech_tree"),
        ],
        hsv_fn=_orange_ratio,
        hsv_name="orange",
        use_all=True,
    )
    add_section("Techs tree", rows)

    # Click best in-band orange thumbs or hex — no Donate
    color, gray = capture_both()
    h, w = gray.shape[:2]
    thumbs = find_all_templates(gray, "tech_thumbs_up.png", cfg_threshold("tech_thumbs_up"))
    picked = None
    for m in thumbs:
        yf, xf = m.phys_y / h, m.phys_x / w
        orange = _orange_ratio(_roi(color, m))
        if 0.12 <= yf <= 0.70 and 0.15 <= xf <= 0.85 and orange >= 0.10:
            picked = ("thumbs", m, orange)
            break
    if picked is None:
        hexes = find_all_templates(gray, "tech_hex_active.png", cfg_threshold("tech_hex_active"))
        for m in hexes:
            yf, xf = m.phys_y / h, m.phys_x / w
            if 0.12 <= yf <= 0.70 and 0.15 <= xf <= 0.85:
                picked = ("hex", m, 0.0)
                break

    if picked is not None:
        tag, m, extra = picked
        lx, ly = physical_to_logical(m.phys_x, m.phys_y)
        if tag == "thumbs":
            lx2, ly2 = physical_to_logical(
                m.phys_x + m.phys_w * 0.35,
                m.phys_y + m.phys_h * 0.45,
            )
            print(f"[Scout] Opening tech via thumbs (orange={extra:.3f}) at ({lx2:.0f},{ly2:.0f})")
            click(lx2, ly2)
        else:
            print(f"[Scout] Opening tech via hex at ({lx:.0f},{ly:.0f})")
            click(lx, ly)
        time.sleep(1.5)
        rows = _probe(
            "07_tech_modal",
            [
                ("donate_blue.png", cfg_threshold("donate_blue"), None),
            ],
            hsv_fn=_blue_ratio,
            hsv_name="blue",
            use_all=True,
        )
        add_section("Tech modal (Donate NOT clicked)", rows)
    else:
        print("[Scout] No in-band thumbs/hex to open — skipping tech modal probe")
        report_lines.append("## Tech modal\n- skipped (no in-band target)\n")

    print("[Scout] Dismissing overlays...")
    dismiss_overlay(delay=1.2)
    dismiss_overlay(delay=1.2)
    dismiss_overlay(delay=1.2)

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"[Scout] Report written to {report_path}")
    print("[Scout] Done (no Claim/Donate performed).")
    return report_path


def main() -> None:
    run_vision_scout()


if __name__ == "__main__":
    main()
