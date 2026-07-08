"""
OCR helpers for game screenshots.

Two distinct read modes:
  - Timer OCR (HH:MM:SS) — used by drone gift
  - Resource-count OCR  (1.3K / 291 / 12.5M) — used by HQ resource collection

Requires:
  pip install pytesseract
  brew install tesseract   (macOS — see docs/SETUP.md)
"""
import re
from pathlib import Path

import cv2
import numpy as np

try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False

# Tesseract config: single-line mode, digits and colon only (timer OCR)
_PSM7_DIGITS = "--psm 7 -c tessedit_char_whitelist=0123456789:"

# Tesseract config: single-line mode, digits + K/M/B suffix + decimal separator
_PSM7_RESOURCE = "--psm 7 -c tessedit_char_whitelist=0123456789.,KMBkmb"

_DURATION_RE  = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")
_RESOURCE_RE  = re.compile(r"^(\d+(?:[.,]\d+)?)([KMBkmb]?)$")


def parse_duration(text: str) -> int | None:
    """
    Parse a timer string in HH:MM:SS or H:MM:SS format into total seconds.

    Returns None if the text does not contain a valid duration.
    """
    m = _DURATION_RE.search(text)
    if not m:
        return None
    h, mins, secs = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return h * 3600 + mins * 60 + secs


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

    phys_x, phys_y: top-left corner of region in physical screenshot pixels
    phys_w, phys_h: width and height of region in physical screenshot pixels
    """
    if not _TESSERACT_AVAILABLE:
        print("[ocr] pytesseract not installed — cannot read timer text")
        return None

    # Crop region
    crop = screen[phys_y : phys_y + phys_h, phys_x : phys_x + phys_w]
    if crop.size == 0:
        return None

    # The game timer is pure-white text on a mixed-color background.
    # White-pixel extraction (sum of R+G+B > 600) reliably isolates the digits.
    # This requires a color (BGR) image; fall back to grayscale threshold if gray.
    scale = 6
    _PAD = 20  # pixels of black border added BEFORE scaling; Tesseract needs whitespace
               # around text edges or it misreads edge characters (e.g. "2" → "7").
    if len(crop.shape) == 3:
        b, g, r = cv2.split(crop)
        # Isolate white timer text (R+G+B > 600 catches pure-white game font).
        white_mask = ((r.astype(int) + g.astype(int) + b.astype(int)) > 600).astype(np.uint8) * 255
        padded = cv2.copyMakeBorder(white_mask, _PAD, _PAD, _PAD, _PAD,
                                    cv2.BORDER_CONSTANT, value=0)
        enlarged = cv2.resize(padded, (padded.shape[1] * scale, padded.shape[0] * scale),
                              interpolation=cv2.INTER_NEAREST)
        # Tesseract expects dark text on light background — invert the white-on-black mask.
        enlarged = cv2.bitwise_not(enlarged)
    else:
        enlarged = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale),
                              interpolation=cv2.INTER_CUBIC)
        _, enlarged = cv2.threshold(enlarged, 200, 255, cv2.THRESH_BINARY)

    text = pytesseract.image_to_string(enlarged, config=_PSM7_DIGITS).strip()
    print(f"[ocr] raw text from region ({phys_x},{phys_y},{phys_w}x{phys_h}): {repr(text)}")

    result = parse_duration(text)
    if result is None:
        text2 = pytesseract.image_to_string(enlarged, config="--psm 6 -c tessedit_char_whitelist=0123456789:").strip()
        print(f"[ocr] retried psm=6: {repr(text2)}")
        result = parse_duration(text2)

    return result


def format_duration(total_seconds: int) -> str:
    """Format total_seconds back to HH:MM:SS string for logging."""
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Resource-count OCR  (1.3K → 1300, 291 → 291, 12.5M → 12500000)
# ---------------------------------------------------------------------------

def parse_resource_amount(text: str) -> int | None:
    """
    Parse a resource count string into an integer.

    Handles K/M/B suffixes (case-insensitive) and decimal separators.
    Examples:
      "1.3K"  → 1300
      "291"   → 291
      "12.5K" → 12500
      "1,300" → 1300  (comma as thousands sep)
      "2.1M"  → 2100000

    Returns None if the text does not look like a valid resource amount.
    """
    if not text:
        return None
    # Remove commas used as thousands separators; collapse internal whitespace
    cleaned = re.sub(r"\s+", "", text.replace(",", "").strip()).upper()
    m = _RESOURCE_RE.match(cleaned)
    if m is None:
        return None
    number_str, suffix = m.group(1), m.group(2)
    # Normalise decimal separator
    number_str = number_str.replace(",", ".")
    try:
        value = float(number_str)
    except ValueError:
        return None
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "": 1}
    return int(value * multipliers.get(suffix, 1))


def read_resource_count_from_region(
    color_screen: np.ndarray,
    phys_x: int,
    phys_y: int,
    phys_w: int,
    phys_h: int,
    *,
    debug_dir: Path | None = None,
    debug_prefix: str = "resource",
) -> tuple[int | None, str]:
    """
    OCR a resource count label (e.g. "1.3K", "291") from a physical-pixel region.

    The label uses white text on the coloured badge circle, so the same
    white-pixel extraction used for timer OCR is applied here.

    Args:
        color_screen:   BGR color ndarray from capture_both()[0].
        phys_x/y:       Top-left corner of the crop region in physical pixels.
        phys_w/h:       Width and height of the crop region in physical pixels.
        debug_dir:      If given, saves <prefix>_proc.png there for inspection.
        debug_prefix:   Filename prefix for debug images.

    Returns:
        (parsed_int, raw_ocr_text) — parsed_int is None on parse failure.
    """
    if not _TESSERACT_AVAILABLE:
        print("[ocr] pytesseract not installed — cannot read resource count")
        return None, ""

    crop = color_screen[phys_y : phys_y + phys_h, phys_x : phys_x + phys_w]
    if crop.size == 0:
        return None, ""

    scale = 6
    _PAD  = 20
    _WHITE_THRESH = 500

    if len(crop.shape) == 3:
        b, g, r = cv2.split(crop)
        white_mask = (
            (r.astype(int) + g.astype(int) + b.astype(int)) > _WHITE_THRESH
        ).astype(np.uint8) * 255
        padded = cv2.copyMakeBorder(white_mask, _PAD, _PAD, _PAD, _PAD,
                                    cv2.BORDER_CONSTANT, value=0)
        enlarged = cv2.resize(padded, (padded.shape[1] * scale, padded.shape[0] * scale),
                              interpolation=cv2.INTER_NEAREST)
        enlarged = cv2.bitwise_not(enlarged)
    else:
        enlarged = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale),
                              interpolation=cv2.INTER_CUBIC)
        _, enlarged = cv2.threshold(enlarged, 180, 255, cv2.THRESH_BINARY)

    if debug_dir is not None:
        debug_dir = Path(debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_dir / f"{debug_prefix}_proc.png"), enlarged)

    _PSM_TRIES = (
        "--psm 11 -c tessedit_char_whitelist=0123456789.,KMBkmb",
        "--psm 6 -c tessedit_char_whitelist=0123456789.,KMBkmb",
        _PSM7_RESOURCE,
    )
    raw_text = ""
    parsed = None
    for cfg in _PSM_TRIES:
        raw_text = pytesseract.image_to_string(enlarged, config=cfg).strip()
        if not raw_text:
            continue
        # psm 11 may return multiline — try each line
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = parse_resource_amount(line)
            if parsed is not None:
                raw_text = line
                break
        if parsed is not None:
            break

    print(f"[ocr] resource count raw ({phys_x},{phys_y} {phys_w}x{phys_h}): {repr(raw_text)}")

    return parsed, raw_text


# ---------------------------------------------------------------------------
# Generic label OCR + scouting parsers
# ---------------------------------------------------------------------------

_LABEL_WHITELIST = (
    "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]():., "
)
_LABEL_PSM6 = (
    "--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]():., "
)

_ALLIANCE_TAG_RE = re.compile(r"\[([A-Za-z0-9]+)\]")
_MAP_LABEL_RE = re.compile(
    r"(?:\[([A-Za-z0-9]+)\])?([A-Za-z0-9_]+)?",
)
_POWER_RE = re.compile(r"(?:power[:\s]*)?([\d,]+)", re.IGNORECASE)
_LEVEL_RE = re.compile(r"^(\d{1,3})$")


def _preprocess_label_crop(crop: np.ndarray, *, white_thresh: int = 500, scale: int = 6) -> np.ndarray:
    """White-text extraction for game UI labels (map names, modal rows)."""
    _PAD = 20
    if len(crop.shape) == 3:
        b, g, r = cv2.split(crop)
        white_mask = (
            (r.astype(int) + g.astype(int) + b.astype(int)) > white_thresh
        ).astype(np.uint8) * 255
        padded = cv2.copyMakeBorder(white_mask, _PAD, _PAD, _PAD, _PAD,
                                    cv2.BORDER_CONSTANT, value=0)
        enlarged = cv2.resize(padded, (padded.shape[1] * scale, padded.shape[0] * scale),
                              interpolation=cv2.INTER_NEAREST)
        return cv2.bitwise_not(enlarged)
    enlarged = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale),
                          interpolation=cv2.INTER_CUBIC)
    _, enlarged = cv2.threshold(enlarged, 180, 255, cv2.THRESH_BINARY)
    return enlarged


def read_text_from_region(
    color_screen: np.ndarray,
    phys_x: int,
    phys_y: int,
    phys_w: int,
    phys_h: int,
    *,
    debug_dir: Path | None = None,
    debug_prefix: str = "label",
) -> str:
    """
    OCR generic white-on-dark UI text from a physical-pixel region.

    Returns raw text (may be empty). Requires pytesseract.
    """
    if not _TESSERACT_AVAILABLE:
        print("[ocr] pytesseract not installed — cannot read label text")
        return ""

    crop = color_screen[phys_y : phys_y + phys_h, phys_x : phys_x + phys_w]
    if crop.size == 0:
        return ""

    enlarged = _preprocess_label_crop(crop)
    if debug_dir is not None:
        debug_dir = Path(debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_dir / f"{debug_prefix}_proc.png"), enlarged)

    for cfg in (_LABEL_WHITELIST, _LABEL_PSM6, "--psm 11"):
        text = pytesseract.image_to_string(enlarged, config=cfg).strip()
        if text:
            print(f"[ocr] label raw ({phys_x},{phys_y} {phys_w}x{phys_h}): {repr(text)}")
            return text
    return ""


def parse_alliance_tag(text: str) -> str | None:
    """Extract alliance tag from text like '[RT63]Alexsimono' or 'Alliance: [RT63]'."""
    if not text:
        return None
    m = _ALLIANCE_TAG_RE.search(text)
    return m.group(1).upper() if m else None


def parse_map_hq_label(text: str) -> dict:
    """
    Parse a map HQ label block.

    Expected multiline text:
      [RT63]Alexsimono
      23

    Returns dict with keys: alliance_tag, player_name, hq_level (any may be None).
    """
    result: dict = {"alliance_tag": None, "player_name": None, "hq_level": None}
    if not text:
        return result

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return result

    first = lines[0]
    tag = parse_alliance_tag(first)
    if tag:
        result["alliance_tag"] = tag
        name_m = re.search(r"\][A-Za-z0-9_]+", first)
        if name_m:
            result["player_name"] = name_m.group(0)[1:]
    else:
        name_m = re.match(r"^([A-Za-z0-9_]+)$", first)
        if name_m:
            result["player_name"] = name_m.group(1)

    for line in lines[1:]:
        lvl_m = _LEVEL_RE.match(line.strip())
        if lvl_m:
            result["hq_level"] = int(lvl_m.group(1))
            break
        # Level may appear on same line after name in noisy OCR
        digits = re.findall(r"\b(\d{1,3})\b", line)
        if digits and result["hq_level"] is None:
            result["hq_level"] = int(digits[-1])

    return result


def parse_city_label(text: str) -> dict:
    """
    Parse a strategic-zoom city label.

    Examples:
      [RT63] Capital City
      12
      Empty City Name
    """
    result: dict = {"alliance_tag": None, "city_name": None, "city_level": None, "is_empty": False}
    if not text:
        return result

    lower = text.lower()
    if "empty" in lower:
        result["is_empty"] = True

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return result

    first = lines[0]
    tag = parse_alliance_tag(first)
    if tag:
        result["alliance_tag"] = tag
        name_m = re.search(r"\](.+)$", first)
        if name_m:
            result["city_name"] = name_m.group(1).strip()
    else:
        result["city_name"] = first

    for line in lines[1:]:
        lvl_m = _LEVEL_RE.match(line.strip())
        if lvl_m:
            result["city_level"] = int(lvl_m.group(1))
            break

    return result


def parse_map_location(text: str) -> str | None:
    """Parse map coords from modal OCR, e.g. '(X:30 Y:350)' or 'X:38Y:346'."""
    if not text:
        return None
    m = re.search(r"X:\s*(\d+)\s*Y:\s*(\d+)", text, re.IGNORECASE)
    if m:
        return f"X:{m.group(1)} Y:{m.group(2)}"
    return None


def parse_power_value(text: str) -> int | None:
    """Parse Power from modal OCR text, e.g. 'Power 38,500' or '38500'."""
    if not text:
        return None
    low = text.lower()
    if "x:" in low and "y:" in low and "power" not in low:
        return None
    m = _POWER_RE.search(text.replace(" ", ""))
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    cleaned = re.sub(r"[^\d]", "", text)
    if cleaned:
        try:
            return int(cleaned)
        except ValueError:
            pass
    return None


def is_blacklisted(tag: str | None, blacklist: list[str]) -> bool:
    """Case-insensitive alliance blacklist check."""
    if not tag or not blacklist:
        return False
    upper = tag.upper()
    return any(entry.upper() == upper for entry in blacklist)
