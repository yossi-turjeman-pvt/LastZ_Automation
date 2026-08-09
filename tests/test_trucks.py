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

import cv2
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


class TestTruckColorGrayWithOrangeDecoration(unittest.TestCase):
    """
    Regression test for the 2026-08-08 gray-truck-with-orange-decoration
    fix (commit b952817): a gray truck body with orange cargo/decorations
    had 2907 orange pixels and was misclassified as "orange" because the
    old code never checked whether gray/white dominated the ROI. Fixed by
    adding a gray/white mask and vetoing "orange" when it dominates (see
    _sample_picker_color's docstring/comments in lastz/flows/trucks.py).

    Note: this fixture is the same blue/silver "D"-badge truck art re-used
    by TestTruckColorRoiSmokeContamination below — it turns out this exact
    truck art was *live-accepted* as "orange" and sent on 2026-08-01 and
    2026-08-08 (runs.log: "Sending truck color=orange") despite visibly not
    being orange, because background HUD icons inside the old, wider ROI box
    were miscounted as truck-body orange. The 2026-08-09 ROI fix (see below)
    is what actually closes that gap for the live capture path; this
    fixture-based check alone can look "fixed" (half-scale annotated PNG vs.
    the real full-resolution capture) without reflecting live behavior.
    """

    _REAL_FIXTURE = (
        Path(__file__).resolve().parent.parent
        / "logs/debug/trucks/color/20260808_051243_832546_r0_initial_orange_frame.png"
    )

    def test_real_gray_truck_capture_not_classified_orange(self):
        # Real capture from today's testing session (gitignored debug
        # output, so only present locally) - a gray-bodied truck. Confirms
        # the current (fixed) code correctly rejects it as "other".
        if not self._REAL_FIXTURE.exists():
            self.skipTest("Real debug capture not present locally (gitignored)")
        color = cv2.imread(str(self._REAL_FIXTURE))
        sample = T._sample_picker_color(color)
        self.assertEqual(sample.kind, "other")

    def test_synthetic_gray_body_with_orange_decoration_not_orange(self):
        # Always runs, independent of the gitignored real capture: builds an
        # image whose picker ROI is gray/white dominant (low saturation)
        # with a small orange patch sized to reproduce the documented
        # incident's ~2907 orange pixel count.
        h, w = 1000, 2000
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (200, 200, 200)  # low-saturation gray truck body

        y0, y1, x0, x1 = T._picker_roi_box(h, w)
        orange_bgr = cv2.cvtColor(np.uint8([[[16, 200, 200]]]), cv2.COLOR_HSV2BGR)[0][0].tolist()
        py0, px0 = y0 + 5, x0 + 5
        img[py0 : py0 + 54, px0 : px0 + 54] = orange_bgr  # ~2916 orange px

        sample = T._sample_picker_color(img)
        self.assertEqual(sample.kind, "other")
        self.assertGreater(sample.orange_px, 2000)  # confirms it's not just "too few px to matter"


class TestTruckColorRoiSmokeContamination(unittest.TestCase):
    """
    Regression test for the 2026-08-09 ROI/threshold fix.

    Real incident (logs/runs.log, menu 2 watcher, overnight 2026-08-08/09):
    the same visibly orange "S"-badge truck art was captured and rejected as
    "other" at least twice (05:30:44 and 05:33:03, ~19 min apart, same
    account) with "gray/white body dominates" — the old ROI box
    (yf=[0.10,0.36] xf=[0.32,0.68]) mostly sampled the dark smoke/cloud
    vignette behind the truck card rather than the truck body, so the smoke
    (low-saturation gray) tripped the gray/white veto meant to guard against
    *gray trucks with orange decorations*, not orange trucks with a smoky
    background. The bot refreshed this truck away repeatedly instead of
    sending it, all night, and the user had to click Go manually.

    Narrowing the ROI to the cab (where body paint is least likely to be
    smoke-obscured) and switching thresholds from absolute pixel floors to
    fractions of the (now much smaller) ROI area fixes this without
    reintroducing the 2026-08-08 gray-truck-with-orange-decoration bug or a
    new purple-truck false-negative (chrome trim reads as "gray/white" on
    every truck regardless of body color, so purple must be checked ahead
    of that veto -- see docstring on _sample_picker_color).
    """

    _FIXTURE_DIR = Path(__file__).resolve().parent.parent / "logs/debug/trucks/color"

    _ORANGE_MISCLASSIFIED_AS_OTHER = [
        "20260809_053044_159150_r3_after_refresh_3_other_frame.png",
        "20260809_053303_710394_r8_after_stale_tips_8_other_frame.png",
    ]
    _BLUE_TRUCK_MISCLASSIFIED_AS_ORANGE = [
        "20260801_050719_365902_r0_initial_orange_frame.png",
        "20260808_051248_107248_r-1_pre_go_recheck_orange_frame.png",
    ]
    _PURPLE_STILL_DETECTED = [
        "20260807_051947_834317_r2_after_refresh_2_purple_frame.png",
        "20260804_051418_567109_r1_after_refresh_1_purple_frame.png",
    ]

    def _classify(self, filename):
        path = self._FIXTURE_DIR / filename
        if not path.exists():
            self.skipTest(f"Real debug capture not present locally (gitignored): {filename}")
        return T._sample_picker_color(cv2.imread(str(path)))

    def test_real_orange_truck_no_longer_rejected_as_other(self):
        for filename in self._ORANGE_MISCLASSIFIED_AS_OTHER:
            with self.subTest(filename=filename):
                self.assertEqual(self._classify(filename).kind, "orange")

    def test_blue_truck_still_correctly_rejected(self):
        for filename in self._BLUE_TRUCK_MISCLASSIFIED_AS_ORANGE:
            with self.subTest(filename=filename):
                self.assertEqual(self._classify(filename).kind, "other")

    def test_purple_still_detected_despite_chrome_trim(self):
        for filename in self._PURPLE_STILL_DETECTED:
            with self.subTest(filename=filename):
                self.assertEqual(self._classify(filename).kind, "purple")


if __name__ == "__main__":
    unittest.main()
