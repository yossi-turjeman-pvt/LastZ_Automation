"""
Parse itemized loot from reward UIs (Congratulations grid + Battle Rewards table).

OCR-first; saves debug crops under logs/debug/flow/ on miss or always when debug=True.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from lastz.config import logs_dir
from lastz.ocr import tesseract_available

try:
    import pytesseract
except ImportError:
    pytesseract = None  # type: ignore


# Compact qty like 1.0K, 100.0k, 1.3M, 12.7M, 789.1K, 10k
_QTY_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<suf>[KkMm])?\b"
)

# Lines that look like Congrats item labels
_SPEEDUP_RE = re.compile(
    r"(?P<n>\d+)\s*[- ]?\s*min\s+(?P<kind>Training|Healing|Building|Research|General)?\s*Speedup",
    re.I,
)
_RESOURCE_LABEL_RE = re.compile(
    r"(?P<qty>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<suf>[KkMm])?\s+"
    r"(?P<name>Food|Wood|Steel|Oil|Gold|Zent|Energy|Gem|Gems|Hero\s*EXP|EXP)\b",
    re.I,
)
_NAMED_ITEM_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9\-/ ]{1,40}?)\s*(?:[xX×]\s*)?(?P<stack>\d+)?\s*$"
)
_STACK_TAIL_RE = re.compile(r"^(?P<label>.+?)\s+[xX×]?\s*(?P<stack>\d+)\s*$")


def parse_qty_token(num: str, suf: str | None = None) -> float:
    """Parse '1,000' / '1.0' + optional K/M suffix into a float amount."""
    raw = (num or "").replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return 0.0
    if not suf:
        return val
    s = suf.upper()
    if s == "K":
        return val * 1_000.0
    if s == "M":
        return val * 1_000_000.0
    return val


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "unknown"


def normalize_item_key(label: str, *, unit_amount: float | None = None) -> str:
    """
    Map an OCR label to a stable item key.

    Resources with a unit size become food / wood / … (materialized totals use unit*stack).
    Speedups become speedup_training_1m etc.
    """
    text = " ".join((label or "").split())
    if not text:
        return "unknown"

    m = _SPEEDUP_RE.search(text)
    if m:
        mins = m.group("n")
        kind = (m.group("kind") or "general").lower()
        return f"speedup_{kind}_{mins}m"

    m = _RESOURCE_LABEL_RE.search(text)
    if m:
        name = m.group("name").lower().replace(" ", "_")
        if name in ("gem",):
            name = "gems"
        if name == "exp":
            name = "hero_exp"
        return name

    low = text.lower()
    # Standalone resource words (drone Congrats: "Zent", "Food", "Wood")
    for word, key in (
        ("zent", "zent"),
        ("food", "food"),
        ("wood", "wood"),
        ("steel", "steel"),
        ("oil", "oil"),
        ("gold", "gold"),
        ("energy", "energy"),
        ("hero exp", "hero_exp"),
        ("gems", "gems"),
        ("gem", "gems"),
    ):
        if low == word or low.startswith(word + " "):
            return key

    # Gear / books / shards — slug the label
    # Strip leading qty from label if present
    cleaned = re.sub(
        r"^\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*[KkMm]?\s+",
        "",
        text,
    ).strip()
    if unit_amount and unit_amount >= 1000 and re.match(r"^\d", text):
        # Prefer resource-style if we already extracted unit
        pass
    return _slug(cleaned or text)


def _ocr_region(screen: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> str:
    if not tesseract_available() or pytesseract is None:
        return ""
    h, w = screen.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return ""
    crop = screen[y0:y1, x0:x1]
    if crop.size == 0:
        return ""

    scale = 3
    if len(crop.shape) == 3:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    else:
        gray = crop
    # Boost white-ish UI text
    _, bw = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    # Prefer dark text on light for tesseract
    inv = cv2.bitwise_not(bw)
    enlarged = cv2.resize(
        inv,
        (inv.shape[1] * scale, inv.shape[0] * scale),
        interpolation=cv2.INTER_NEAREST,
    )
    try:
        text = pytesseract.image_to_string(enlarged, config="--psm 6").strip()
    except Exception as exc:
        print(f"[loot] OCR error: {exc}")
        return ""
    return text


def _save_debug(screen: np.ndarray, name: str, rect: tuple[int, int, int, int] | None = None) -> Path:
    out_dir = logs_dir() / "debug" / "flow"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    path = out_dir / f"loot_parse_{name}_{stamp}.png"
    img = screen
    if rect is not None:
        x0, y0, x1, y1 = rect
        vis = screen.copy()
        cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 255, 0), 2)
        cv2.imwrite(str(path), vis)
        crop_path = out_dir / f"loot_parse_{name}_{stamp}_crop.png"
        cv2.imwrite(str(crop_path), screen[y0:y1, x0:x1])
    else:
        cv2.imwrite(str(path), img)
    return path


def _congrats_roi(h: int, w: int) -> tuple[int, int, int, int]:
    # Center modal band — works for gifts row and drone multi-row grid
    return int(0.22 * w), int(0.12 * h), int(0.78 * w), int(0.78 * h)


def _parse_congrats_text(text: str) -> dict[str, float]:
    """Extract item_key → amount from OCR text of a Congratulations popup."""
    items: dict[str, float] = {}
    if not text:
        return items

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Drop header-only lines
    body_lines = [
        ln
        for ln in lines
        if "congratulation" not in ln.lower() and ln.lower() not in ("ok", "claim", "collect")
    ]

    # Pair consecutive lines: often qty badge on one line, label on next — or label includes qty
    i = 0
    while i < len(body_lines):
        ln = body_lines[i]
        low = ln.lower()

        # Full "1,000 Food" / "1-min Training Speedup"
        m_res = _RESOURCE_LABEL_RE.search(ln)
        if m_res:
            unit = parse_qty_token(m_res.group("qty"), m_res.group("suf"))
            key = normalize_item_key(ln)
            # Look for a nearby lone stack digit
            stack = 1.0
            if i + 1 < len(body_lines) and re.fullmatch(r"\d{1,4}", body_lines[i + 1].strip()):
                stack = float(body_lines[i + 1].strip())
                i += 2
            else:
                # Stack digit sometimes precedes label
                if i > 0 and re.fullmatch(r"\d{1,4}", body_lines[i - 1].strip()):
                    stack = float(body_lines[i - 1].strip())
                i += 1
            items[key] = items.get(key, 0.0) + unit * stack
            continue

        m_sp = _SPEEDUP_RE.search(ln)
        if m_sp:
            key = normalize_item_key(ln)
            stack = 1.0
            if i + 1 < len(body_lines) and re.fullmatch(r"\d{1,4}", body_lines[i + 1].strip()):
                stack = float(body_lines[i + 1].strip())
                i += 2
            else:
                i += 1
            items[key] = items.get(key, 0.0) + stack
            continue

        # "Zent" / "Food" / "D3-Pistol" with qty on same or adjacent line
        # Pattern: line is mostly a name; qty is "789.1K" nearby
        qty_only = _QTY_RE.fullmatch(ln.replace(" ", ""))
        if qty_only and i + 1 < len(body_lines):
            amount = parse_qty_token(qty_only.group("num"), qty_only.group("suf"))
            label = body_lines[i + 1]
            key = normalize_item_key(label)
            # If label is also a qty, skip
            if _QTY_RE.fullmatch(label.replace(" ", "")):
                i += 1
                continue
            # Resources: amount is the material total (badge on icon)
            if key in (
                "food",
                "wood",
                "steel",
                "oil",
                "gold",
                "zent",
                "energy",
                "hero_exp",
                "gems",
            ):
                items[key] = items.get(key, 0.0) + amount
            else:
                # Gear: amount is often stack on icon (1, 2) — if amount < 100 treat as stack
                if amount < 100:
                    items[key] = items.get(key, 0.0) + amount
                else:
                    items[key] = items.get(key, 0.0) + amount
            i += 2
            continue

        # "D3-Combat Boots" then "2"
        if re.search(r"[A-Za-z]", ln) and "speedup" not in low:
            key = normalize_item_key(ln)
            stack = 1.0
            if i + 1 < len(body_lines):
                nxt = body_lines[i + 1].strip()
                m_q = _QTY_RE.fullmatch(nxt.replace(" ", ""))
                if m_q:
                    amount = parse_qty_token(m_q.group("num"), m_q.group("suf"))
                    if key in (
                        "food",
                        "wood",
                        "steel",
                        "oil",
                        "gold",
                        "zent",
                        "energy",
                        "hero_exp",
                        "gems",
                    ):
                        items[key] = items.get(key, 0.0) + amount
                    else:
                        items[key] = items.get(key, 0.0) + (amount if amount < 100 else 1.0)
                    i += 2
                    continue
                if re.fullmatch(r"\d{1,4}", nxt):
                    stack = float(nxt)
                    i += 2
                    items[key] = items.get(key, 0.0) + stack
                    continue
            items[key] = items.get(key, 0.0) + stack
            i += 1
            continue

        i += 1

    return items


def read_congrats_popup(screen: np.ndarray, *, debug: bool = True) -> tuple[bool, dict[str, float]]:
    """
    Parse a Congratulations! reward popup from a full color (or gray) capture.

    Returns (popup_confirmed, {item_key: amount}). popup_confirmed is True
    only when the "Congratulations!" header text was actually found in the
    OCR'd ROI. This matters because some UIs (e.g. Alliance Gifts' Common
    tab) leave an always-on panel behind the button — a persistent
    boomer-spoils/activity-log list — in the exact same ROI when the click
    hasn't (yet) produced a real reward popup. Real incident: that list's
    row text ("AussieLana teamed up and attacked Boomer", timestamps, etc.)
    got OCR'd and reported as if it were claimed loot, on every single
    cycle, because nothing checked whether a genuine popup was ever there.
    Callers that need to trust the returned items for a claim-success
    decision should check popup_confirmed, not just whether items is
    non-empty (item parsing can spuriously "succeed" on unrelated text).
    """
    if screen is None or screen.size == 0:
        return False, {}
    h, w = screen.shape[:2]
    x0, y0, x1, y1 = _congrats_roi(h, w)
    text = _ocr_region(screen, x0, y0, x1, y1)
    preview = text if len(text) < 500 else text[:500]
    print(f"[loot] Congrats OCR ({len(text)} chars): {preview!r}")

    popup_confirmed = "congrat" in text.lower()
    if not popup_confirmed and debug:
        # Still try parse — header OCR can miss; save crop for tuning
        _save_debug(screen, "congrats_noheader", (x0, y0, x1, y1))

    items = _parse_congrats_text(text)
    if not items:
        if debug:
            path = _save_debug(screen, "congrats_miss", (x0, y0, x1, y1))
            print(f"[loot] Congrats parse miss — saved {path}")
        return popup_confirmed, {}

    if debug:
        _save_debug(screen, "congrats_ok", (x0, y0, x1, y1))
    print(f"[loot] Congrats items: {items}")
    return popup_confirmed, items


def parse_congrats_grid(screen: np.ndarray, *, debug: bool = True) -> dict[str, float]:
    """
    Back-compat wrapper around read_congrats_popup() that returns just the
    parsed items, regardless of whether the "Congratulations!" header was
    confirmed. Existing callers (e.g. the Drone Gift flow, which always
    shows a real Congrats popup) rely on this permissive behavior; callers
    that need to distinguish a real popup from unrelated background text
    (e.g. Alliance Gifts Claim All, which does not always show one) should
    use read_congrats_popup() directly instead.
    """
    _confirmed, items = read_congrats_popup(screen, debug=debug)
    return items


def _battle_roi(h: int, w: int) -> tuple[int, int, int, int]:
    # Battle Rewards modal center; Your Reward column is right half of modal
    return int(0.20 * w), int(0.15 * h), int(0.80 * w), int(0.75 * h)


def _parse_battle_text(text: str) -> dict[str, float]:
    """
    Battlefield rewards show icon strips with qty labels (10k, 100.0k, 40.0k)
    and occasional EXP text — few English names.

    Recognized EXP → hero_exp; other qtys → battlefield_reward_N.
    """
    items: dict[str, float] = {}
    if not text:
        return items

    exp_amt = 0.0
    for m in re.finditer(
        r"(?:hero\s*)?exp\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<suf>[KkMm])?",
        text,
        flags=re.I,
    ):
        amt = parse_qty_token(m.group("num"), m.group("suf"))
        if amt:
            exp_amt += amt
    if exp_amt:
        items["hero_exp"] = exp_amt

    qtys: list[float] = []
    for m in _QTY_RE.finditer(text.replace("\n", " ")):
        start = m.start()
        prefix = text[max(0, start - 4) : start].lower()
        if "lv" in prefix or "lvl" in prefix:
            continue
        amt = parse_qty_token(m.group("num"), m.group("suf"))
        if m.group("suf") is None and amt < 10:
            continue
        if amt > 0:
            qtys.append(amt)

    skipped_exp = False
    unknown_i = 1
    for amt in qtys:
        if not skipped_exp and exp_amt and abs(amt - exp_amt) < 1e-6:
            skipped_exp = True
            continue
        items[f"battlefield_reward_{unknown_i}"] = (
            items.get(f"battlefield_reward_{unknown_i}", 0.0) + amt
        )
        unknown_i += 1
    return items


def parse_battle_rewards(screen: np.ndarray, *, debug: bool = True) -> dict[str, float]:
    """
    Parse Battle Rewards modal (Your Reward row) BEFORE Claim All.

    Returns {item_key: amount}.
    """
    if screen is None or screen.size == 0:
        return {}
    h, w = screen.shape[:2]
    x0, y0, x1, y1 = _battle_roi(h, w)
    mid = (x0 + x1) // 2
    text_full = _ocr_region(screen, x0, y0, x1, y1)
    text_right = _ocr_region(screen, mid, y0, x1, y1)
    text = text_full + "\n" + text_right
    preview = text if len(text) < 500 else text[:500]
    print(f"[loot] Battle Rewards OCR: {preview!r}")

    if "battle" not in text.lower() and "reward" not in text.lower() and debug:
        _save_debug(screen, "battle_noheader", (x0, y0, x1, y1))

    items = _parse_battle_text(text)
    if not items:
        if debug:
            path = _save_debug(screen, "battle_miss", (x0, y0, x1, y1))
            print(f"[loot] Battle Rewards parse miss — saved {path}")
        return {}

    if debug:
        _save_debug(screen, "battle_ok", (x0, y0, x1, y1))
    print(f"[loot] Battle Rewards items: {items}")
    return items


def merge_loot(*parts: Iterable[dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in parts:
        for k, v in (p or {}).items():
            out[k] = out.get(k, 0.0) + float(v)
    return out
