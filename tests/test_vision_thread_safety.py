"""
Regression tests for the template-scale calibration race flagged by sub-agent
review of the screen.py capture-state thread-safety fix: `lastz/vision.py`'s
`_ensure_scale_calibrated()` used to read/write plain module globals
(`_calibrated_for`, `_scale_center`) shared between the main flow thread and
the heli-BR-monitor background thread (see lastz/flows/helicopter.py
start_heli_monitor(), which polls a WINDOW-shaped capture concurrently with
the main flow's DISPLAY-shaped captures for the lifetime of the watcher).

Same bug class as the screen.py capture-state race: one thread's calibration
for its own capture shape could stomp the other's mid-flow, and
`template_scales()` reading `_scale_center` in a separate statement after
`_ensure_scale_calibrated()` returns could read a value written by the
*other* thread's concurrent calibration — building the wrong resolution's
scale search band right in the middle of a live click-driving flow.
"""
import sys
import threading
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import lastz.vision as vision


class TestScaleCalibrationThreadIsolation(unittest.TestCase):
    def test_scale_center_isolated_across_threads(self):
        """Two threads calibrating to different resolutions' scales must
        never see each other's value — mirrors the real main-flow-thread
        (full display) vs. heli-monitor-thread (game window) split."""
        results: dict[str, float] = {}
        barrier = threading.Barrier(2)

        def worker(name: str, scale: float) -> None:
            vision._local.scale_center = scale
            vision._local.calibrated_for = (1, 1)
            barrier.wait()  # force both writes before either read
            results[name] = vision._get_scale_center()

        t1 = threading.Thread(target=worker, args=("main_flow", 0.775))
        t2 = threading.Thread(target=worker, args=("heli_monitor", 0.512))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results["main_flow"], 0.775)
        self.assertEqual(results["heli_monitor"], 0.512)

    def test_calibrated_for_isolated_across_threads(self):
        results: dict[str, tuple] = {}
        barrier = threading.Barrier(2)

        def worker(name: str, shape: tuple) -> None:
            vision._local.calibrated_for = shape
            barrier.wait()
            results[name] = vision._local.calibrated_for

        t1 = threading.Thread(target=worker, args=("main_flow", (3440, 1440)))
        t2 = threading.Thread(target=worker, args=("heli_monitor", (1512, 982)))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results["main_flow"], (3440, 1440))
        self.assertEqual(results["heli_monitor"], (1512, 982))

    def test_template_scales_uses_single_consistent_read(self):
        """A fresh thread that never calibrated falls back to the legacy
        default (1.0) rather than raising or reading another thread's
        thread-local, and template_scales()/current_template_scale() must
        agree with each other within the same thread."""
        result = {}

        def worker() -> None:
            vision._local.scale_center = 0.9
            result["current"] = vision.current_template_scale()
            result["scales"] = vision.template_scales()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        self.assertEqual(result["current"], 0.9)
        self.assertIn(0.9, result["scales"])
        # Always includes 1.0 as a safety net regardless of center.
        self.assertIn(1.0, result["scales"])

    def test_fresh_thread_defaults_to_legacy_global(self):
        """No prior calibration in this thread -> falls back to the
        module-level default (1.0), not an exception or a stale value left
        over from another thread's local storage."""
        result = {}

        def worker() -> None:
            result["scale"] = vision._get_scale_center()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(result["scale"], 1.0)


if __name__ == "__main__":
    unittest.main()
