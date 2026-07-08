"""
Unit tests for HQ Resource Collection (Flow 5).

Tests cover:
  - parse_resource_amount: string → integer parsing for all formats
  - State machine transitions: pass 1 storage, pass 2 collect, disagree, OCR fail
  - find_all_templates + cluster_matches (vision layer, no game required)

Run from project root:
    python -m pytest tests/test_hq_resources.py -v
or:
    python tests/test_hq_resources.py
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lastz.ocr import parse_resource_amount
from lastz.vision import MatchWithBBox, cluster_matches


class TestParseResourceAmount(unittest.TestCase):
    """parse_resource_amount must handle all game label formats."""

    def _p(self, s):
        return parse_resource_amount(s)

    def test_plain_integer(self):
        self.assertEqual(self._p("291"), 291)
        self.assertEqual(self._p("660"), 660)
        self.assertEqual(self._p("1000"), 1000)

    def test_decimal_k_suffix(self):
        self.assertEqual(self._p("198.7K"), 198700)
        self.assertEqual(self._p("691.2K"), 691200)

    def test_k_suffix_with_space(self):
        self.assertEqual(self._p("198.7 K"), 198700)
        self.assertEqual(self._p("1.3k"), 1300)
        self.assertEqual(self._p("12K"), 12000)
        self.assertEqual(self._p("12.5K"), 12500)

    def test_m_suffix(self):
        self.assertEqual(self._p("1M"), 1_000_000)
        self.assertEqual(self._p("2.1M"), 2_100_000)

    def test_b_suffix(self):
        self.assertEqual(self._p("1B"), 1_000_000_000)

    def test_comma_thousands_separator(self):
        self.assertEqual(self._p("1,300"), 1300)
        self.assertEqual(self._p("12,500"), 12500)

    def test_none_on_garbage(self):
        self.assertIsNone(self._p(""))
        self.assertIsNone(self._p("N/A"))
        self.assertIsNone(self._p("??"))
        self.assertIsNone(self._p("abc"))

    def test_ocr_misread_tolerance(self):
        # A common Tesseract misread: "1.BK" — should return None (not crash)
        self.assertIsNone(self._p("1.BK"))

    def test_whitespace_stripped(self):
        self.assertEqual(self._p(" 1.3K "), 1300)


class TestClusterMatches(unittest.TestCase):
    """cluster_matches deduplicates icons seen in overlapping pan frames."""

    def _m(self, x, y, conf=0.9):
        return MatchWithBBox(phys_x=x, phys_y=y, phys_w=100, phys_h=100, confidence=conf)

    def test_empty(self):
        self.assertEqual(cluster_matches([]), [])

    def test_single(self):
        m = self._m(100, 200)
        self.assertEqual(cluster_matches([m]), [m])

    def test_identical_positions_collapse(self):
        m1 = self._m(100, 200, conf=0.8)
        m2 = self._m(102, 198, conf=0.9)  # within default radius
        result = cluster_matches([m1, m2], radius_px=60)
        self.assertEqual(len(result), 1)
        # Best confidence wins
        self.assertAlmostEqual(result[0].confidence, 0.9)

    def test_distant_matches_kept_separate(self):
        m1 = self._m(100, 200)
        m2 = self._m(500, 200)  # far apart
        result = cluster_matches([m1, m2], radius_px=60)
        self.assertEqual(len(result), 2)

    def test_cluster_keeps_best_confidence(self):
        m1 = self._m(100, 100, conf=0.7)
        m2 = self._m(110, 105, conf=0.95)
        m3 = self._m(115, 95,  conf=0.85)
        result = cluster_matches([m1, m2, m3], radius_px=60)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].confidence, 0.95)


class TestStateMachineLogic(unittest.TestCase):
    """
    Test the two-pass gating logic without running the game.

    We import _passes_gating from hq_resources and test its decision table.
    """

    def setUp(self):
        # Import here to avoid affecting other test classes that don't need it
        from lastz.flows.hq_resources import ScanResult, _passes_gating
        self.ScanResult = ScanResult
        self._passes = _passes_gating

    def _current(self, status="consensus", count=1300, icons=3, conf=0.85):
        m = MatchWithBBox(100, 100, 50, 50, conf)
        return self.ScanResult(
            status=status, count=count, raw="1.3K", icons_seen=icons,
            best_match=m, max_conf=conf,
        )

    def _stored(self, count=1300, icons=3, agreed=True, pan_steps=5, conf=0.85):
        return {
            "consensus_count": count,
            "consensus_raw": "1.3K",
            "scan_id": 1,
            "icons_seen": icons,
            "all_visible_agreed": agreed,
            "pan_positions_completed": pan_steps,
            "max_conf": conf,
            "ts": time.time() - 200,
            "last_collect_at": None,
        }

    def test_collects_when_both_passes_agree(self):
        cur = self._current()
        stored = self._stored()
        self.assertTrue(self._passes(cur, stored, scan_id=2, pan_steps=5))

    def test_no_collect_on_first_pass(self):
        cur = self._current()
        self.assertFalse(self._passes(cur, None, scan_id=1, pan_steps=5))

    def test_no_collect_when_counts_differ(self):
        cur = self._current(count=1300)
        stored = self._stored(count=1200)  # count changed
        self.assertFalse(self._passes(cur, stored, scan_id=2, pan_steps=5))

    def test_no_collect_when_rising(self):
        # current count > stored count means still filling
        cur = self._current(count=1400)
        stored = self._stored(count=1300)
        self.assertFalse(self._passes(cur, stored, scan_id=2, pan_steps=5))

    def test_no_collect_when_ocr_incomplete(self):
        cur = self._current(status="ocr_incomplete", count=None)
        stored = self._stored()
        self.assertFalse(self._passes(cur, stored, scan_id=2, pan_steps=5))

    def test_no_collect_when_still_filling(self):
        cur = self._current(status="still_filling", count=None)
        stored = self._stored()
        self.assertFalse(self._passes(cur, stored, scan_id=2, pan_steps=5))

    def test_no_collect_when_not_enough_icons(self):
        from unittest.mock import patch
        cur = self._current(icons=1)
        stored = self._stored(icons=1)
        with patch("lastz.flows.hq_resources._min_icons", return_value=2):
            self.assertFalse(self._passes(cur, stored, scan_id=2, pan_steps=5))

    def test_no_collect_when_stored_pan_incomplete(self):
        cur = self._current()
        stored = self._stored(pan_steps=2)  # only 2 of 5 pan positions done
        self.assertFalse(self._passes(cur, stored, scan_id=2, pan_steps=5))

    def test_collects_via_icon_presence_when_ocr_unavailable(self):
        cur = self._current(status="icon_ready", count=None, icons=2, conf=0.75)
        stored = self._stored(count=None, icons=2, agreed=False, conf=0.72)
        self.assertTrue(self._passes(cur, stored, scan_id=2, pan_steps=5))

    def test_no_collect_when_stored_did_not_agree(self):
        cur = self._current()
        stored = self._stored(agreed=False)
        self.assertFalse(self._passes(cur, stored, scan_id=2, pan_steps=5))


class TestStateFilePersistence(unittest.TestCase):
    """State file read/write round-trip test."""

    def test_round_trip(self):
        from lastz.flows.hq_resources import _load_state, _save_state
        import unittest.mock as mock

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            types = {
                "food": {
                    "consensus_count": 1300,
                    "consensus_raw": "1.3K",
                    "scan_id": 42,
                    "icons_seen": 4,
                    "all_visible_agreed": True,
                    "pan_positions_completed": 5,
                    "ts": 1718123456.0,
                    "last_collect_at": None,
                }
            }
            with mock.patch("lastz.flows.hq_resources._state_file", return_value=tmp_path):
                _save_state(types, last_full_sweep_at=1718123456.0)
                loaded = _load_state()

            self.assertEqual(loaded["food"]["consensus_count"], 1300)
            self.assertEqual(loaded["food"]["consensus_raw"], "1.3K")
            self.assertTrue(loaded["food"]["all_visible_agreed"])
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_corrupt_state_returns_empty(self):
        from lastz.flows.hq_resources import _load_state
        import unittest.mock as mock

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("NOT VALID JSON !!!")
            tmp_path = Path(f.name)

        try:
            with mock.patch("lastz.flows.hq_resources._state_file", return_value=tmp_path):
                result = _load_state()
            self.assertEqual(result, {})
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
