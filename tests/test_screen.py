"""Unit tests for dynamic screen/coordinate helpers."""
import sys
import threading
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
    def test_window_offset_click_frac(self, _mock):
        from lastz.config import window_offset_click
        # dismiss_outside_frac: [0.06, 0.28] → window-relative
        lx, ly = window_offset_click("dismiss_outside")
        self.assertAlmostEqual(lx, 1512 + 0.06 * 3440, delta=1)
        self.assertAlmostEqual(ly, -428 + 0.28 * 1410, delta=1)

    def test_scale_capture_rect(self):
        scaled = screen.scale_capture_rect([1200, 730, 1200, 130])
        self.assertEqual(scaled[0], int(1200 * 3440 / 3024))
        self.assertEqual(scaled[2], int(1200 * 3440 / 3024))

    @patch("lastz.screen.get_game_window_bounds", return_value=(0, 0, 1512, 982))
    def test_scale_ref_logical_delta(self, _mock):
        dx, dy = screen.scale_ref_logical_delta(200, -200)
        self.assertAlmostEqual(dx, 200.0)
        self.assertAlmostEqual(dy, -200.0)


class TestThreadIsolatedCaptureState(unittest.TestCase):
    """
    Regression tests for the race that fed stale Alliance-Gifts panel pixels
    into post-claim loot OCR: the watcher runs the helicopter BR-monitor as
    a background thread in the same process as the main click-driving flow,
    and both used to share one PID-keyed temp file plus module-global
    capture-size/display-bounds state. A background poll landing mid-flow
    could silently swap out the screenshot (or the active-display bounds)
    the main thread was about to read. Capture state must be fully
    thread-local so concurrent threads never see or clobber each other's.
    """

    def test_temp_screen_path_unique_per_thread(self):
        # Threads must all be alive *simultaneously* when they read their
        # path — like the real main-flow-thread vs. heli-monitor-thread
        # case, which are both long-lived and genuinely overlap. Fast,
        # non-overlapping threads can have their OS thread id recycled by
        # a later thread, which would be a test artifact, not a real bug.
        n = 4
        paths: dict[str, str] = {}
        lock = threading.Lock()
        barrier = threading.Barrier(n)

        def worker(name: str) -> None:
            barrier.wait()
            p = screen._temp_screen_path()
            with lock:
                paths[name] = p

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(set(paths.values())), len(paths), f"collided paths: {paths}")
        for p in paths.values():
            self.assertIn(f"_{__import__('os').getpid()}_", p)

    def test_capture_size_isolated_across_threads(self):
        """Simulates the real race: one thread's _run_capture()-style write
        must not be visible to (or overwritten by) another thread's."""
        results: dict[str, tuple[int, int]] = {}
        barrier = threading.Barrier(2)

        def worker(name: str, size: tuple[int, int]) -> None:
            screen._local.capture_size = size
            barrier.wait()  # force both threads to have written before either reads
            results[name] = screen._last_size()

        t1 = threading.Thread(target=worker, args=("main", (3440, 1440)))
        t2 = threading.Thread(target=worker, args=("heli_monitor", (1512, 982)))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results["main"], (3440, 1440))
        self.assertEqual(results["heli_monitor"], (1512, 982))

    def test_active_display_bounds_isolated_across_threads(self):
        results: dict[str, tuple] = {}
        barrier = threading.Barrier(2)

        def worker(name: str, bounds: tuple) -> None:
            screen._local.active_display_bounds = bounds
            barrier.wait()
            results[name] = screen.active_display_bounds()

        main_bounds = (0.0, 0.0, 3440.0, 1440.0)
        heli_bounds = (1512.0, -428.0, 1512.0, 982.0)
        t1 = threading.Thread(target=worker, args=("main", main_bounds))
        t2 = threading.Thread(target=worker, args=("heli_monitor", heli_bounds))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results["main"], main_bounds)
        self.assertEqual(results["heli_monitor"], heli_bounds)

    def test_falls_back_to_legacy_global_when_thread_local_unset(self):
        """A fresh thread that never captured falls back to the legacy
        module global (preserves existing single-threaded test behavior:
        `screen._last_capture_size = X` then call a helper, same thread)."""
        screen._last_capture_size = (2000, 1000)
        result = {}

        def worker() -> None:
            result["size"] = screen._last_size()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(result["size"], (2000, 1000))


if __name__ == "__main__":
    unittest.main()
