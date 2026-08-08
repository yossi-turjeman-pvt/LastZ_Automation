"""
Regression test for the helicopter march-ring coordinate-space bug.

Real bug (found during 2026-08-08 code review of that day's commits):
_step_march_formation() picked a click point as a GAME-WINDOW fraction
(fx, fy), then re-found a "march ring" template match afterward and
accepted/rejected it by comparing `candidate.phys_x / w` - where `w` is the
FULL-CAPTURE width (capture_both() is a full-display screenshot, not
window-cropped) - directly against `fx`. Those are two different reference
frames whenever the game window doesn't fill the whole display/capture
(e.g. this repo's own ultrawide dev setup, see test_screen.py's letterboxed
fixture), so a match that landed exactly on the intended window-relative
click point could still be wrongly rejected as "too far away".

This test reproduces that exact shape: a candidate whose FULL-CAPTURE
fraction disagrees with fx (what the old buggy comparison used) but whose
WINDOW fraction agrees with fx (what the comparison should use), and
asserts the fixed helper (_phys_to_window_frac) reports the window
fraction - i.e. the fix actually changes the accept/reject outcome, not
just a refactor.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import lastz.screen as screen
from lastz.flows import helicopter as H


class TestPhysToWindowFrac(unittest.TestCase):
    def setUp(self):
        # A wide capture (e.g. spanning/covering more than just the game
        # window) mapped 1:1 to logical space for simplicity.
        screen._last_capture_size = (3440, 1440)
        screen._active_display_bounds = (0.0, 0.0, 3440.0, 1440.0)

    @patch("lastz.screen.get_game_window_bounds", return_value=(0, 0, 1720, 1440))
    def test_window_center_not_full_capture_center(self, _mock):
        # Game window fills only the LEFT HALF of the full capture (a
        # stand-in for real letterboxing). A candidate sitting at the
        # window's exact horizontal center is phys_x=860 (860/1720 == 0.5
        # in window-fraction terms) but only 860/3440 == 0.25 in
        # full-capture-fraction terms - the value the old buggy code used.
        cand_fx, cand_fy = H._phys_to_window_frac(860, 720)

        self.assertAlmostEqual(cand_fx, 0.5, delta=0.01)
        self.assertAlmostEqual(cand_fy, 0.5, delta=0.01)

        # Reproduce the OLD buggy comparison to prove it disagrees - this
        # is what would have caused a valid match to be rejected.
        old_buggy_frac = 860 / 3440
        self.assertNotAlmostEqual(old_buggy_frac, 0.5, delta=0.01)

    @patch("lastz.screen.get_game_window_bounds", return_value=(0, 0, 1720, 1440))
    def test_accept_reject_outcome_changes_with_fix(self, _mock):
        # fx/fy as _step_march_formation would compute them for the default
        # empty-land offset (window-center-ish click target).
        fx, fy = 0.50, 0.52
        candidate_phys_x, candidate_phys_y = 860, 748.8  # exact window target

        # Old (buggy) comparison: full-capture fraction vs window fraction.
        w, h = 3440, 1440
        old_accept = (
            abs(candidate_phys_x / w - fx) < 0.18
            and abs(candidate_phys_y / h - fy) < 0.22
        )
        self.assertFalse(old_accept, "old comparison should wrongly reject this valid match")

        # New (fixed) comparison: both sides in window-fraction space.
        cand_fx, cand_fy = H._phys_to_window_frac(candidate_phys_x, candidate_phys_y)
        new_accept = abs(cand_fx - fx) < 0.18 and abs(cand_fy - fy) < 0.22
        self.assertTrue(new_accept, "fixed comparison should correctly accept this valid match")

    @patch("lastz.screen.get_game_window_bounds", return_value=(0, 0, 0, 0))
    def test_degenerate_window_bounds_falls_back_safely(self, _mock):
        # Zero-size window bounds must not raise (ZeroDivisionError etc.).
        cand_fx, cand_fy = H._phys_to_window_frac(100, 100)
        self.assertEqual((cand_fx, cand_fy), (0.5, 0.5))


if __name__ == "__main__":
    unittest.main()
