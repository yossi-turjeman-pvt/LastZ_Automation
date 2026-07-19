"""
Debug helpers: annotate matches on captures and save under logs/debug/.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from lastz.config import logs_dir
from lastz.screen import physical_to_logical


def debug_dir(*parts: str) -> Path:
    p = logs_dir() / "debug"
    for part in parts:
        p = p / part
    p.mkdir(parents=True, exist_ok=True)
    return p


def frac_xy(phys_x: float, phys_y: float, h: int, w: int) -> tuple[float, float]:
    return phys_x / max(1, w), phys_y / max(1, h)


def in_band(
    phys_x: float,
    phys_y: float,
    h: int,
    w: int,
    y0: float,
    y1: float,
    x0: float = 0.0,
    x1: float = 1.0,
) -> bool:
    xf, yf = frac_xy(phys_x, phys_y, h, w)
    return x0 <= xf <= x1 and y0 <= yf <= y1


def annotate_and_save(
    color_bgr: np.ndarray,
    step: str,
    matches: list[dict],
    *,
    subdir: str = "scout",
) -> Path:
    """
    matches: list of dicts with keys:
      label, phys_x, phys_y, conf, optional phys_w/phys_h, optional note
    """
    img = color_bgr.copy()
    h, w = img.shape[:2]
    for m in matches:
        x, y = int(m["phys_x"]), int(m["phys_y"])
        conf = float(m.get("conf", 0.0))
        label = str(m.get("label", "?"))
        note = str(m.get("note", ""))
        color = (0, 255, 0) if m.get("ok", True) else (0, 0, 255)
        pw = int(m.get("phys_w") or 40)
        ph = int(m.get("phys_h") or 40)
        x1, y1 = max(0, x - pw // 2), max(0, y - ph // 2)
        x2, y2 = min(w - 1, x + pw // 2), min(h - 1, y + ph // 2)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.circle(img, (x, y), 6, color, -1)
        text = f"{label} {conf:.2f} {note}".strip()
        cv2.putText(
            img,
            text[:60],
            (max(0, x1), max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )

    ts = time.strftime("%H%M%S")
    out = debug_dir(subdir) / f"{step}_{ts}.png"
    cv2.imwrite(str(out), img)
    print(f"[debug] saved {out}")
    return out


def match_row(
    template: str,
    phys_x: float,
    phys_y: float,
    conf: float,
    h: int,
    w: int,
    *,
    phys_w: int | None = None,
    phys_h: int | None = None,
    band: tuple[float, float, float, float] | None = None,
    extra: str = "",
) -> dict:
    xf, yf = frac_xy(phys_x, phys_y, h, w)
    lx, ly = physical_to_logical(phys_x, phys_y)
    in_b = True
    if band is not None:
        y0, y1, x0, x1 = band
        in_b = in_band(phys_x, phys_y, h, w, y0, y1, x0, x1)
    return {
        "template": template,
        "conf": conf,
        "phys_x": phys_x,
        "phys_y": phys_y,
        "phys_w": phys_w,
        "phys_h": phys_h,
        "logical": (lx, ly),
        "x_frac": xf,
        "y_frac": yf,
        "in_band": in_b,
        "extra": extra,
        "label": template,
        "ok": in_b,
        "note": f"yf={yf:.2f}" + (f" {extra}" if extra else ""),
    }
