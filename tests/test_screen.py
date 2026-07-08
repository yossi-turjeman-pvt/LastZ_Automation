"""Unit tests for dynamic screen/coordinate helpers."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import lastz.screen as screen


class TestDynamicCoordinates(unittest.TestCase):
    def setUp(self):
        screen._last_capture_size = (3440, 1440)
        screen._active_display_bounds = (1512.0, -428.0, 3440.0, 1440.0)

    def test_physical_to_logical_ultrawide(self):
        lx, ly = screen.physical_to_logical(3356, 1380)
        self.assertAlmostEqual(lx, 4868.0, delta=2)
        self.assertAlmostEqual(ly, 952.0, delta=2)

    def test_physical_to_logical_retina(self):
        screen._last_capture_size = (3024, 1964)
        screen._active_display_bounds = (0.0, 0.0, 1512.0, 982.0)
        lx, ly = screen.physical_to_logical(1512, 982)
        self.assertAlmostEqual(lx, 756.0)
        self.assertAlmostEqual(ly, 491.0)

    @patch("lastz.screen.get_game_window_bounds", return_value=(1512, -428, 3440, 1410))
    def test_window_offset_click(self, _mock):
        from lastz.config import window_offset_click
        lx, ly = window_offset_click("dismiss_outside")
        self.assertAlmostEqual(lx, 1612.0)
        self.assertAlmostEqual(ly, -128.0)

    def test_scale_capture_rect(self):
        scaled = screen.scale_capture_rect([1200, 730, 1200, 130])
        self.assertEqual(scaled[0], int(1200 * 3440 / 3024))
        self.assertEqual(scaled[2], int(1200 * 3440 / 3024))

    @patch("lastz.screen.get_game_window_bounds", return_value=(0, 0, 1512, 982))
    def test_scale_ref_logical_delta(self, _mock):
        dx, dy = screen.scale_ref_logical_delta(200, -200)
        self.assertAlmostEqual(dx, 200.0)
        self.assertAlmostEqual(dy, -200.0)


if __name__ == "__main__":
    unittest.main()
