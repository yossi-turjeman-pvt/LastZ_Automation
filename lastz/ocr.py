"""
OCR helpers for game screenshots — timer (HH:MM:SS) for HQ drone gift,
plus general UI label text (Alliance grid tiles, etc.).

Requires:
  pip install pytesseract
  brew install tesseract   (macOS — see docs/SETUP.md)
"""
import re

import cv2
import numpy as np

try:
    import pytesseract

    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False

_PSM7_DIGITS = "--psm 7 -c tessedit_char_whitelist=0123456789:"
_DURATION_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")


def parse_duration(text: str) -> int | None:
    """Parse HH:MM:SS or H:MM:SS into total seconds. None if invalid."""
    m = _DURATION_RE.search(text)
    if not m:
        return None
    h, mins, secs = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return h * 3600 + mins * 60 + secs


def format_duration(total_seconds: int) -> str:
    """Format total_seconds as HH:MM:SS for logging."""
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def tesseract_available() -> bool:
    return _TESSERACT_AVAILABLE


def normalize_ui_text(text: str) -> str:
    """Lowercase letters-only for fuzzy UI label checks."""
    return re.sub(r"[^a-z]", "", (text or "").lower())


def text_mentions_wrong_alliance_tile(text: str) -> bool:
    """True if OCR clearly names a non-Techs Alliance grid tile (Shop, Gifts, …)."""
    t = normalize_ui_text(text)
    if not t:
        return False
    if "shop" in t:
        return True
    if "gift" in t:
        return True
    if "build" in t:
        return True
    if "rank" in t or "member" in t:
        return True
    # "help" alone is short; require it not look like techs
    if "help" in t and "tech" not in t and "teh" not in t:
        return True
    if t == "wars" or t.endswith("wars"):
        return True
    return False


def text_mentions_techs(text: str) -> bool:
    """
    True if OCR text looks like Alliance Techs.

    Tolerates common misreads (e.g. 'Tanhe' for 'Techs', 'Allianas' for 'Alliance').
    """
    t = normalize_ui_text(text)
    if not t or text_mentions_wrong_alliance_tile(text):
        return False
    needles = (
        "tech",
        "teh",
        "tanhe",
        "tache",
        "tehn",
        "tach",
        "teck",
        "tec",
        "chn",  # …chn… in garbled techs
    )
    if any(n in t for n in needles):
        return True
    # Alliance + tech-ish fragment (Allianas Tanhe → allianastanheom)
    if "allian" in t and any(n in t for n in ("tan", "teh", "tec", "chn", "ach")):
        return True
    return False


def read_ui_text(
    screen: np.ndarray,
    phys_x: int,
    phys_y: int,
    phys_w: int,
    phys_h: int,
) -> str:
    """
    OCR white-outlined UI label text from a physical-pixel region.

    Returns raw tesseract string (may be empty). Empty if tesseract missing.
    """
    if not _TESSERACT_AVAILABLE:
        print("[ocr] pytesseract not installed — cannot read UI text")
        return ""

    h, w = screen.shape[:2]
    x0 = max(0, phys_x)
    y0 = max(0, phys_y)
    x1 = min(w, phys_x + phys_w)
    y1 = min(h, phys_y + phys_h)
    crop = screen[y0:y1, x0:x1]
    if crop.size == 0:
        return ""

    scale = 4
    _PAD = 12
    if len(crop.shape) == 3:
        b, g, r = cv2.split(crop)
        # Bright label fill (white / near-white)
        white_mask = ((r.astype(int) + g.astype(int) + b.astype(int)) > 520).astype(np.uint8) * 255
        padded = cv2.copyMakeBorder(
            white_mask, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_CONSTANT, value=0
        )
        enlarged = cv2.resize(
            padded,
            (padded.shape[1] * scale, padded.shape[0] * scale),
            interpolation=cv2.INTER_NEAREST,
        )
        # Tesseract prefers dark text on light bg
        enlarged = cv2.bitwise_not(enlarged)
    else:
        enlarged = cv2.resize(
            crop,
            (crop.shape[1] * scale, crop.shape[0] * scale),
            interpolation=cv2.INTER_CUBIC,
        )
        _, enlarged = cv2.threshold(enlarged, 160, 255, cv2.THRESH_BINARY)

    try:
        text = pytesseract.image_to_string(enlarged, config="--psm 6").strip()
    except Exception as exc:
        print(f"[ocr] UI text error: {exc}")
        return ""
    print(f"[ocr] UI text ({x0},{y0},{x1 - x0}x{y1 - y0}): {text!r}")
    return text


def read_duration_from_region(
    screen: np.ndarray,
    phys_x: int,
    phys_y: int,
    phys_w: int,
    phys_h: int,
) -> int | None:
    """
    OCR a HH:MM:SS duration from a physical-pixel region of a screenshot.

    Returns total seconds, or None if tesseract is unavailable or parsing fails.
    """
    if not _TESSERACT_AVAILABLE:
        print("[ocr] pytesseract not installed — cannot read timer text")
        return None

    crop = screen[phys_y : phys_y + phys_h, phys_x : phys_x + phys_w]
    if crop.size == 0:
        return None

    scale = 6
    _PAD = 20
    if len(crop.shape) == 3:
        b, g, r = cv2.split(crop)
        white_mask = ((r.astype(int) + g.astype(int) + b.astype(int)) > 600).astype(np.uint8) * 255
        padded = cv2.copyMakeBorder(
            white_mask, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_CONSTANT, value=0
        )
        enlarged = cv2.resize(
            padded,
            (padded.shape[1] * scale, padded.shape[0] * scale),
            interpolation=cv2.INTER_NEAREST,
        )
        enlarged = cv2.bitwise_not(enlarged)
    else:
        enlarged = cv2.resize(
            crop,
            (crop.shape[1] * scale, crop.shape[0] * scale),
            interpolation=cv2.INTER_CUBIC,
        )
        _, enlarged = cv2.threshold(enlarged, 200, 255, cv2.THRESH_BINARY)

    text = pytesseract.image_to_string(enlarged, config=_PSM7_DIGITS).strip()
    print(f"[ocr] raw text from region ({phys_x},{phys_y},{phys_w}x{phys_h}): {repr(text)}")

    result = parse_duration(text)
    if result is None:
        text2 = pytesseract.image_to_string(
            enlarged, config="--psm 6 -c tessedit_char_whitelist=0123456789:"
        ).strip()
        print(f"[ocr] retried psm=6: {repr(text2)}")
        result = parse_duration(text2)

    return result
