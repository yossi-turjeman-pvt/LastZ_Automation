"""
OCR helpers for game screenshots — timer (HH:MM:SS) for HQ drone gift.

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
