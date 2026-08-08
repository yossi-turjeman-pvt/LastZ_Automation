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


_DIGIT_MATCH_SIZE = (24, 32)  # (w, h) common size digits are resized to for comparison
_MIN_COMPONENT_AREA = 8       # ignore specks smaller than this (anti-aliasing noise)
# Final acceptance threshold, checked once against the best interpretation
# found. Touching-digit splits (see _read_digits_from_blob) inherently score
# lower than a cleanly isolated single digit (each piece carries a sliver of
# its neighbor), and even a genuinely isolated single digit can land as low
# as ~0.39 depending on rendering/antialiasing (live-measured). Live-measured
# true positives ranged ~0.39-0.76; every wrong split/digit candidate seen
# capped out ~0.30-0.35. 0.35 keeps clear margin below every observed true
# positive while still well above observed wrong-candidate noise.
_MIN_DIGIT_CONFIDENCE = 0.35
# Very low floor used only to prune obviously-degenerate candidates mid-
# search (not a real acceptance bar - that's _MIN_DIGIT_CONFIDENCE, checked
# once on the overall best interpretation after the search completes).
_SEARCH_PRUNE_FLOOR = 0.15
_digit_templates: dict[str, np.ndarray] | None = None


def _digit_templates_dir():
    from lastz.config import templates_dir

    return templates_dir().parent / "digits"


def digit_templates_available() -> bool:
    return _load_digit_templates() is not None


def _load_digit_templates() -> dict[str, np.ndarray] | None:
    global _digit_templates
    if _digit_templates is not None:
        return _digit_templates
    d = _digit_templates_dir()
    templates: dict[str, np.ndarray] = {}
    for digit in range(10):
        p = d / f"digit_{digit}.png"
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"[ocr] digit template missing: {p}")
            return None
        templates[str(digit)] = cv2.resize(img, _DIGIT_MATCH_SIZE, interpolation=cv2.INTER_AREA)
    _digit_templates = templates
    return templates


def _merge_overlapping_x(
    components: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    """
    Merge connected components whose x-ranges overlap into a single box.

    Some digits in this font (0, 9 - anything with an enclosed loop) render
    as TWO disconnected foreground blobs under 8-connectivity: the outer
    ring plus a thin inner artifact near the loop's center. Treating those
    as two separate "digits" corrupts the whole read (extra/wrong
    characters). Grouping by x-overlap before matching - rather than
    assuming one component == one digit - fixes this without needing
    per-glyph special-casing.
    """
    boxes = sorted(components, key=lambda c: c[0])
    merged: list[list[int]] = []
    for x, y, w, h in boxes:
        placed = False
        for group in merged:
            gx0, gy0, gx1, gy1 = group
            if x < gx1 and (x + w) > gx0:  # horizontal overlap
                group[0] = min(gx0, x)
                group[1] = min(gy0, y)
                group[2] = max(gx1, x + w)
                group[3] = max(gy1, y + h)
                placed = True
                break
        if not placed:
            merged.append([x, y, x + w, y + h])
    return [(gx0, gy0, gx1 - gx0, gy1 - gy0) for gx0, gy0, gx1, gy1 in merged]


_SINGLE_DIGIT_MAX_WIDTH = 27  # observed native single-glyph widths are 17-25px
_MIN_SPLIT_PIECE_WIDTH = 6
_MAX_DIGITS_PER_BLOB = 3  # this field never realistically shows more digits


def _match_piece(piece: np.ndarray, templates: dict[str, np.ndarray]) -> tuple[str | None, float]:
    if piece.shape[1] < _MIN_SPLIT_PIECE_WIDTH:
        return None, -1.0
    # Saved digit templates were captured with a ~3px margin of real
    # background around the glyph (bbox-of-foreground-pixels + pad=3).
    # Since the background here is genuinely uniform (thresholds to solid
    # 0), a synthetic zero border reproduces that same context without
    # needing access to the original larger array at every split boundary.
    padded = cv2.copyMakeBorder(piece, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=0)
    resized = cv2.resize(padded, _DIGIT_MATCH_SIZE, interpolation=cv2.INTER_AREA)
    best_digit, best_score = None, -1.0
    for digit_char, tmpl in templates.items():
        score = float(cv2.matchTemplate(resized, tmpl, cv2.TM_CCOEFF_NORMED)[0][0])
        if score > best_score:
            best_digit, best_score = digit_char, score
    return best_digit, best_score


def _read_digits_from_blob(blob: np.ndarray, templates: dict[str, np.ndarray]) -> tuple[str | None, float]:
    """
    Read one or more digits out of a single (possibly multi-digit) blob.

    A simple "find the one column with lowest ink density" split fails when
    adjacent digits are touching pixel-for-pixel in places but the true
    gap sits somewhere the density profile doesn't clearly reveal (found
    live: "5" and "0" touch at their top curves, and the actual lowest-
    density column lands inside "0" itself, not between the two digits).
    Instead, brute-force every plausible split point (or pair of points for
    3 digits) and keep whichever full interpretation scores best overall -
    the blob is small (a handful of pixels wide per candidate), so this is
    cheap despite being O(w) / O(w^2).
    """
    w = blob.shape[1]
    if w <= _SINGLE_DIGIT_MAX_WIDTH:
        digit, score = _match_piece(blob, templates)
        return digit, score

    best_digits: str | None = None
    best_score = -1.0

    # Two-digit interpretations.
    for split in range(_MIN_SPLIT_PIECE_WIDTH, w - _MIN_SPLIT_PIECE_WIDTH):
        d1, s1 = _match_piece(blob[:, :split], templates)
        if d1 is None or s1 < _SEARCH_PRUNE_FLOOR:
            continue
        d2, s2 = _match_piece(blob[:, split:], templates)
        if d2 is None or s2 < _SEARCH_PRUNE_FLOOR:
            continue
        combined = min(s1, s2)
        if combined > best_score:
            best_digits, best_score = d1 + d2, combined

    # Three-digit interpretations, only if the blob is wide enough to
    # plausibly hold a third glyph.
    if _MAX_DIGITS_PER_BLOB >= 3 and w > 2 * _SINGLE_DIGIT_MAX_WIDTH - _MIN_SPLIT_PIECE_WIDTH:
        for split1 in range(_MIN_SPLIT_PIECE_WIDTH, w - 2 * _MIN_SPLIT_PIECE_WIDTH):
            d1, s1 = _match_piece(blob[:, :split1], templates)
            if d1 is None or s1 < _SEARCH_PRUNE_FLOOR:
                continue
            for split2 in range(split1 + _MIN_SPLIT_PIECE_WIDTH, w - _MIN_SPLIT_PIECE_WIDTH):
                d2, s2 = _match_piece(blob[:, split1:split2], templates)
                if d2 is None or s2 < _SEARCH_PRUNE_FLOOR:
                    continue
                d3, s3 = _match_piece(blob[:, split2:], templates)
                if d3 is None or s3 < _SEARCH_PRUNE_FLOOR:
                    continue
                combined = min(s1, s2, s3)
                if combined > best_score:
                    best_digits, best_score = d1 + d2 + d3, combined

    return best_digits, best_score


def read_stepper_number(
    screen: np.ndarray,
    phys_x: int,
    phys_y: int,
    phys_w: int,
    phys_h: int,
) -> int | None:
    """
    Read a small numeric stepper field (e.g. the Hospital batch-quantity
    field) via per-digit template matching, NOT Tesseract.

    Live testing (2026-08-09) found this game's "1" glyph has a serif/flag
    that Tesseract - trained on standard fonts - consistently misreads as
    "4" (confirmed across every scale/psm/oem combination tried, and even
    with each digit isolated to its own OCR call). That's not a tunable
    preprocessing bug, it's a font this general-purpose OCR model was never
    trained on. Since the field only ever contains one of exactly 10 fixed
    glyph shapes in this one game font, template matching - what this whole
    project already relies on for everything else - is the correct tool:
    isolate each digit as its own connected component, resize to a common
    size, and match against 10 captured reference glyphs
    (templates/digits/digit_0.png .. digit_9.png).

    Returns the parsed integer, or None if the digit templates aren't
    available, the crop is empty, or any digit's best match confidence
    falls below the threshold (never guesses a low-confidence read).
    """
    templates = _load_digit_templates()
    if templates is None:
        print("[ocr] digit templates unavailable — cannot read stepper number")
        return None

    h, w = screen.shape[:2]
    x0 = max(0, phys_x)
    y0 = max(0, phys_y)
    x1 = min(w, phys_x + phys_w)
    y1 = min(h, phys_y + phys_h)
    crop = screen[y0:y1, x0:x1]
    if crop.size == 0:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    # Digits are near-black; background is a flat mid-gray (~193). A fixed
    # threshold well below the background level isolates dark fill/outline
    # pixels without depending on the brightness-sum heuristic tuned for
    # the opposite (white-text-on-dark) case elsewhere in this module.
    _, mask = cv2.threshold(gray, 110, 255, cv2.THRESH_BINARY_INV)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    raw_components = [
        (stats[i][0], stats[i][1], stats[i][2], stats[i][3])
        for i in range(1, n)
        if stats[i][4] >= _MIN_COMPONENT_AREA
    ]
    if not raw_components:
        print(f"[ocr] stepper number ({x0},{y0},{x1 - x0}x{y1 - y0}): no digit components found")
        return None
    components = _merge_overlapping_x(raw_components)

    digits = []
    worst_conf = 1.0
    for cx, cy, cw, ch in components:
        blob = mask[cy : cy + ch, cx : cx + cw]
        group_digits, group_score = _read_digits_from_blob(blob, templates)
        if group_digits is None or group_score < _MIN_DIGIT_CONFIDENCE:
            print(
                f"[ocr] stepper number ({x0},{y0},{x1 - x0}x{y1 - y0}): "
                f"unreadable digit group at x={cx} (best={group_digits!r} conf={group_score:.2f})"
            )
            return None
        digits.append(group_digits)
        worst_conf = min(worst_conf, group_score)

    text = "".join(digits)
    print(f"[ocr] stepper number ({x0},{y0},{x1 - x0}x{y1 - y0}): {text!r} (min conf={worst_conf:.2f})")
    return int(text)


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
