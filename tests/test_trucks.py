"""
Regression test for the Trucks "hidden top row" double-send bug.

Real incident (logs/runs.log, 2026-08-01):
  05:07:11  clean 4-lane scan, all empty, yf = 0.273/0.376/0.481/0.589
            -> correctly sent into the true upper slot (yf=0.273).
  05:44:29  only 3 lanes discovered (yf = 0.376/0.482/0.589, i.e. lanes
            2-4 unchanged) because the truck sent at 05:07 was still en
            route and rendered with no +/chest/color signature at all --
            lane 1 silently vanished from discovery instead of showing as
            "occupied". The bot mistook lane 2 (yf=0.376) for "the upper
            slot" and sent a second truck into it -> two trucks
            concurrently out, violating the one-truck-at-a-time rule.

This test drives the real `_upper_plus` / `_maybe_learn_top_row_yf` code
against synthetic SlotTrack scans built from those exact logged values.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lastz.flows import trucks as T

_H = 1440
_W = 3000


def _track(kind: str, yf: float, source: str) -> T.SlotTrack:
    return T.SlotTrack(kind, 100.0, yf * _H, 0.9, source)


class TestTrucksHiddenTopRow(unittest.TestCase):
    def setUp(self):
        # Isolate persisted calibration state per test.
        self._tmp_state = Path(self.id().split(".")[-1] + "_trucks_state.json")
        patcher = patch.object(T, "_trucks_state_path", return_value=self._tmp_state)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: self._tmp_state.unlink(missing_ok=True))
        self.addCleanup(
            lambda: self._tmp_state.with_suffix(".json.tmp").unlink(missing_ok=True)
        )

        self.gray = np.zeros((_H, _W), dtype=np.uint8)
        self.color = np.zeros((_H, _W, 3), dtype=np.uint8)

    def test_learns_top_row_from_clean_four_lane_scan(self):
        clean = [
            _track("empty", 0.273, "plus"),
            _track("empty", 0.376, "plus"),
            _track("empty", 0.481, "plus"),
            _track("empty", 0.589, "plus"),
        ]
        T._maybe_learn_top_row_yf(clean, (_H, _W))
        self.assertAlmostEqual(T._load_top_row_yf((_H, _W)), 0.273, delta=0.001)

    def test_refuses_send_when_top_row_is_hidden(self):
        clean = [
            _track("empty", 0.273, "plus"),
            _track("empty", 0.376, "plus"),
            _track("empty", 0.481, "plus"),
            _track("empty", 0.589, "plus"),
        ]
        T._maybe_learn_top_row_yf(clean, (_H, _W))

        # Real incident: lane 1 invisible, lanes 2-4 unchanged.
        hidden_row1 = [
            _track("empty", 0.376, "plus"),
            _track("empty", 0.482, "plus"),
            _track("empty", 0.589, "plus"),
        ]
        with patch.object(T, "_discover_all_tracks", return_value=hidden_row1):
            result = T._upper_plus(self.gray, self.color)
        self.assertIsNone(result, "must refuse instead of sending into lane 2")

    def test_still_sends_on_genuinely_clean_scan(self):
        clean = [
            _track("empty", 0.273, "plus"),
            _track("empty", 0.376, "plus"),
            _track("empty", 0.481, "plus"),
            _track("empty", 0.589, "plus"),
        ]
        with patch.object(T, "_discover_all_tracks", return_value=clean):
            result = T._upper_plus(self.gray, self.color)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.phys_y / _H, 0.273, delta=0.002)

    def test_still_refuses_when_upper_track_visibly_occupied(self):
        occupied_upper = [
            _track("occupied", 0.273, "chest"),
            _track("empty", 0.376, "plus"),
        ]
        with patch.object(T, "_discover_all_tracks", return_value=occupied_upper):
            result = T._upper_plus(self.gray, self.color)
        self.assertIsNone(result)

    def test_ignores_implausible_top_candidate_near_band_edge(self):
        # A spurious match right at the scan band's own top edge (yf0=0.10)
        # must not poison the learned baseline downward.
        band_yf0 = T._highway_band()[0]
        bogus = [
            _track("empty", band_yf0 + 0.005, "plus"),
            _track("empty", 0.376, "plus"),
            _track("empty", 0.481, "plus"),
            _track("empty", 0.589, "plus"),
        ]
        T._maybe_learn_top_row_yf(bogus, (_H, _W))
        self.assertEqual(T._load_top_row_yf((_H, _W)), T._DEFAULT_TOP_ROW_YF)


if __name__ == "__main__":
    unittest.main()
