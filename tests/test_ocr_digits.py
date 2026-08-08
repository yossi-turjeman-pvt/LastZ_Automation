"""
Regression tests for lastz.ocr.read_stepper_number's digit-template reader.

Real incident (2026-08-09): Tesseract consistently misread this game's "1"
glyph as "4" (a font-rendering quirk no preprocessing fixed - confirmed
across every scale/psm/oem combination tried), so the healing batch-size
field was replaced with per-digit template matching instead of OCR. That
surfaced two further real bugs, both covered here:

1. Digits with an enclosed loop (0, 9) render as TWO disconnected
   foreground blobs under 8-connectivity (the outer ring plus a thin inner
   artifact), which were briefly treated as two separate "digits".
2. Adjacent digits can be pixel-touching in this font (e.g. "5" and "0"'s
   top curves touch), merging them into ONE connected component that a
   naive single lowest-density-column split mis-segments. Fixed with a
   brute-force multi-split search that scores every plausible
   segmentation and keeps the best-scoring whole read.

These tests build synthetic field images from the real captured digit
templates (templates/digits/digit_0.png .. digit_9.png) rather than
depending on a specific gitignored screenshot, so they run anywhere.
"""
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import lastz.ocr as ocr

_DIGITS_DIR = PROJECT_ROOT / "templates" / "digits"


def _load_digit_mask(d: int) -> np.ndarray:
    img = cv2.imread(str(_DIGITS_DIR / f"digit_{d}.png"), cv2.IMREAD_GRAYSCALE)
    assert img is not None, f"missing templates/digits/digit_{d}.png"
    return img


def _build_field(digits: list[int], gap: int, canvas_w: int = 120, canvas_h: int = 49) -> np.ndarray:
    """
    Compose a synthetic "quantity field" BGR image: flat mid-gray background
    (~193, matching the real field) with the given digit glyphs painted in
    dark ink (~20), spaced by `gap` pixels (negative = overlapping/touching).
    """
    canvas = np.full((canvas_h, canvas_w, 3), 193, dtype=np.uint8)
    x, y = 10, 10
    for d in digits:
        mask = _load_digit_mask(d)
        th, tw = mask.shape
        region_gray = cv2.cvtColor(canvas[y : y + th, x : x + tw], cv2.COLOR_BGR2GRAY)
        region_gray[mask > 0] = 20
        canvas[y : y + th, x : x + tw] = cv2.cvtColor(region_gray, cv2.COLOR_GRAY2BGR)
        x += tw + gap
    return canvas


class TestReadStepperNumber(unittest.TestCase):
    def setUp(self):
        ocr._digit_templates = None  # force a fresh load per test

    def test_reads_each_single_digit_correctly(self):
        for d in range(10):
            field = _build_field([d], gap=0)
            h, w = field.shape[:2]
            with self.subTest(digit=d):
                self.assertEqual(ocr.read_stepper_number(field, 0, 0, w, h), d)

    def test_reads_touching_digits_5_and_0(self):
        # gap=-6 reproduces the real incident: "5" and "0" pixel-touch at
        # their top curves, merging into one connected component.
        field = _build_field([5, 0], gap=-6)
        h, w = field.shape[:2]
        n, _, stats, _ = cv2.connectedComponentsWithStats(
            cv2.threshold(cv2.cvtColor(field, cv2.COLOR_BGR2GRAY), 110, 255, cv2.THRESH_BINARY_INV)[1],
            connectivity=8,
        )
        # Sanity-check the synthetic image actually reproduces the touching
        # scenario (a naive one-component-per-digit reader would corrupt
        # this read) before asserting the fix handles it.
        self.assertLessEqual(n - 1, 2, "test setup should produce a merged/touching blob, not clean separate digits")
        self.assertEqual(ocr.read_stepper_number(field, 0, 0, w, h), 50)

    def test_reads_two_cleanly_separated_digits(self):
        field = _build_field([1, 2], gap=6)
        h, w = field.shape[:2]
        self.assertEqual(ocr.read_stepper_number(field, 0, 0, w, h), 12)

    def test_reads_digit_with_enclosed_loop_as_one_digit_not_two(self):
        # "0" alone renders as 2 disconnected components (ring + inner
        # artifact) - must still read as a single digit "0", not "?0" or
        # fail outright.
        field = _build_field([0], gap=0)
        h, w = field.shape[:2]
        self.assertEqual(ocr.read_stepper_number(field, 0, 0, w, h), 0)

    def test_blank_field_returns_none(self):
        blank = np.full((49, 80, 3), 193, dtype=np.uint8)
        self.assertIsNone(ocr.read_stepper_number(blank, 0, 0, 80, 49))

    def test_random_noise_does_not_produce_false_positive(self):
        rng = np.random.default_rng(42)
        noise = rng.integers(0, 255, (49, 80, 3), dtype=np.uint8)
        # Must not crash; whatever it reads (almost certainly None) must not
        # be silently trusted by a caller expecting a real digit read.
        result = ocr.read_stepper_number(noise, 0, 0, 80, 49)
        self.assertIsNone(result)

    def test_digit_templates_available(self):
        self.assertTrue(ocr.digit_templates_available())


if __name__ == "__main__":
    unittest.main()
