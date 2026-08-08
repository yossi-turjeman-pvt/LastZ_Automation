"""
Regression tests for the healing flow's safety fixes (2026-08-08 code review).

Two P1 bugs fixed here:
1. check_and_heal_once used to log a WARNING and click Heal anyway when
   _set_batch_size() failed, potentially healing with a stale leftover
   quantity from a previous session instead of the configured batch_size.
2. _set_batch_size used to rapid-click "-" a fixed 300 times and TRUST that
   reached 0, with no verification - if the field's leftover value exceeded
   300 (troop counts well into the hundreds are common), the final quantity
   would silently be `leftover_beyond_300 + batch_size`, not batch_size.

Both now abort the cycle (press Escape, return False, retry next poll)
rather than guessing, verified via OCR reading the actual field value.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lastz.flows import healing as HL
from lastz.vision import Match, MatchWithBBox

_H, _W = 1440, 3440
_BAND = [0.75, 1.0, 0.0, 0.20]


def _bbox(x, y, w=51, h=50, conf=0.9) -> MatchWithBBox:
    return MatchWithBBox(phys_x=x, phys_y=y, phys_w=w, phys_h=h, confidence=conf)


class HealingTestBase(unittest.TestCase):
    """Common patching for functions healing.py imports into its own namespace."""

    def setUp(self):
        self.color = np.zeros((_H, _W, 3), dtype=np.uint8)
        for target, ret in (
            ("capture", self.color),
            ("ensure_template_scale", None),
            ("click", None),
            ("press_escape", None),
            ("rapid_click", None),
        ):
            patcher = patch.object(HL, target, return_value=ret)
            patcher.start()
            self.addCleanup(patcher.stop)

        logical_patcher = patch.object(HL, "physical_to_logical", side_effect=lambda x, y: (x, y))
        logical_patcher.start()
        self.addCleanup(logical_patcher.stop)

        sleep_patcher = patch("time.sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)


class TestAbortOnBatchSizeFailure(HealingTestBase):
    """Finding 1: never click Heal with an unverified/failed batch size."""

    def test_check_and_heal_once_aborts_when_set_batch_size_fails(self):
        with patch.object(HL, "_find_healing_icon", return_value=(100.0, 200.0)), \
             patch.object(HL, "_set_batch_size", return_value=False):
            result = HL.check_and_heal_once(_BAND, batch_size=50)

        self.assertFalse(result)
        HL.press_escape.assert_called_once()

    def test_set_batch_size_returns_false_when_steppers_not_found(self):
        with patch.object(HL, "find_all_templates", return_value=[]):
            result = HL._set_batch_size(50)

        self.assertFalse(result)


class TestZeroOutStepper(HealingTestBase):
    """Finding 2: OCR-verify the stepper actually reaches 0, bounded retries, abort if not."""

    def test_verifies_zero_after_first_round(self):
        plus = _bbox(200, 100)
        with patch.object(HL, "tesseract_available", return_value=True), \
             patch.object(HL, "read_stepper_number", return_value=0):
            result = HL._zero_out_stepper(50.0, 100.0, plus, batch_size=50)

        self.assertTrue(result)
        self.assertEqual(HL.rapid_click.call_count, 1)
        _, kwargs = HL.rapid_click.call_args
        self.assertEqual(kwargs.get("count"), 50 + HL._ZERO_MARGIN)

    def test_retries_then_verifies_zero(self):
        plus = _bbox(200, 100)
        with patch.object(HL, "tesseract_available", return_value=True), \
             patch.object(HL, "read_stepper_number", side_effect=[12, 3, 0]):
            result = HL._zero_out_stepper(50.0, 100.0, plus, batch_size=50)

        self.assertTrue(result)
        # 1 initial burst + 2 retry-round clicks before the 3rd read verifies 0.
        self.assertEqual(HL.rapid_click.call_count, 3)

    def test_aborts_when_never_reaches_zero(self):
        plus = _bbox(200, 100)
        with patch.object(HL, "tesseract_available", return_value=True), \
             patch.object(HL, "read_stepper_number", return_value=7):
            result = HL._zero_out_stepper(50.0, 100.0, plus, batch_size=50)

        self.assertFalse(result)
        # Initial burst + exactly _ZERO_VERIFY_ROUNDS retry rounds, never more.
        self.assertEqual(HL.rapid_click.call_count, 1 + HL._ZERO_VERIFY_ROUNDS)

    def test_aborts_when_tesseract_unavailable(self):
        plus = _bbox(200, 100)
        with patch.object(HL, "tesseract_available", return_value=False):
            result = HL._zero_out_stepper(50.0, 100.0, plus, batch_size=50)

        self.assertFalse(result)
        HL.rapid_click.assert_not_called()


class TestSetToTargetVerified(HealingTestBase):
    """
    _set_to_target_verified: rapid_click can drop clicks under a fast burst
    (confirmed live: a batch_size=50 click burst landed on 47) - the final
    "+" count must be OCR-verified and topped up, not trusted outright.
    """

    def test_verifies_target_after_first_burst(self):
        plus = _bbox(200, 100)
        with patch.object(HL, "read_stepper_number", return_value=50):
            result = HL._set_to_target_verified(50.0, 100.0, plus, batch_size=50)

        self.assertTrue(result)
        # Just the initial burst - no top-up needed.
        self.assertEqual(HL.rapid_click.call_count, 1)

    def test_tops_up_shortfall_from_dropped_clicks(self):
        plus = _bbox(200, 100)
        with patch.object(HL, "read_stepper_number", side_effect=[47, 50]):
            result = HL._set_to_target_verified(50.0, 100.0, plus, batch_size=50)

        self.assertTrue(result)
        self.assertEqual(HL.rapid_click.call_count, 2)
        # Second call tops up exactly the shortfall (50 - 47 = 3).
        _, kwargs = HL.rapid_click.call_args
        self.assertEqual(kwargs.get("count"), 3)

    def test_aborts_on_overshoot(self):
        plus = _bbox(200, 100)
        with patch.object(HL, "read_stepper_number", return_value=53):
            result = HL._set_to_target_verified(50.0, 100.0, plus, batch_size=50)

        self.assertFalse(result)

    def test_aborts_when_never_verifiable(self):
        plus = _bbox(200, 100)
        with patch.object(HL, "read_stepper_number", return_value=None):
            result = HL._set_to_target_verified(50.0, 100.0, plus, batch_size=50)

        self.assertFalse(result)


class TestCheckAndHealOnceSuccessPath(HealingTestBase):
    def test_full_success_path_returns_true(self):
        def fake_find_icon(icon_name, band, thr, debug=False):
            if icon_name == "healing_wounded.png":
                return (100.0, 200.0)
            if icon_name == "healing_ask_help.png":
                return (140.0, 210.0)
            return None

        heal_match = Match(phys_x=900.0, phys_y=600.0, confidence=0.99)

        with patch.object(HL, "_find_healing_icon", side_effect=fake_find_icon), \
             patch.object(HL, "_set_batch_size", return_value=True), \
             patch("lastz.vision.find_template", return_value=heal_match):
            result = HL.check_and_heal_once(_BAND, batch_size=50)

        self.assertTrue(result)
        HL.press_escape.assert_not_called()


class TestCollectHealing(HealingTestBase):
    """check_and_collect_healing must check every healing_complete*.png variant."""

    def test_iterates_all_complete_variants_and_collects_on_match(self):
        def fake_find_icon(icon_name, band, thr, debug=False):
            if icon_name == "healing_complete_2.png":
                return (150.0, 250.0)
            return None

        with patch.object(
            HL, "_complete_icon_names",
            return_value=["healing_complete.png", "healing_complete_2.png", "healing_complete_3.png"],
        ), patch.object(HL, "_find_healing_icon", side_effect=fake_find_icon):
            result = HL.check_and_collect_healing(_BAND)

        self.assertTrue(result)
        HL.click.assert_called_once_with(150.0, 250.0)

    def test_returns_false_when_no_variant_matches(self):
        with patch.object(HL, "_complete_icon_names", return_value=["healing_complete.png"]), \
             patch.object(HL, "_find_healing_icon", return_value=None):
            result = HL.check_and_collect_healing(_BAND)

        self.assertFalse(result)
        HL.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
