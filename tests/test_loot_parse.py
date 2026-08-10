"""
Regression tests for the Alliance Gifts "Claim All reports fake loot" bug.

Real incident (logs/runs.log + logs/debug/flow/, 2026-08-03 overnight run):
`_try_claim_all` clicked the real Claim All button (template match
conf=0.985), waited a fixed 1.25s, then OCR'd the same on-screen region a
"Congratulations!" reward popup would appear in — and reported whatever it
found as claimed loot, with no check that a real popup was ever there.

Alliance Gifts' Common tab leaves an always-on "boomer spoils" activity-log
panel in that exact region when the actual reward popup hasn't rendered
yet (or never will, if the click didn't do anything). OCR-ing that panel
produced nonsense item keys (`attacked_boomer=3`,
`aussielana_teamed_up_and=2`, ...) which got logged every single cycle as
"Claimed All (Instant); loot: ...", regardless of whether the game
actually granted anything — proven live by comparing the pre/post-click
screenshots: the item list, badge count, and Claim All button were
byte-for-byte unchanged after the "successful" claim.

`read_congrats_popup()` / `_try_claim_all()` must only trust parsed items
when the real "Congratulations!" header was actually OCR'd, and must
retry the capture a few times before giving up (background heli-monitor
thread contention or plain game lag can delay the popup's render).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lastz.flows import alliance_gifts as AG
from lastz.flows.loot_parse import read_congrats_popup, parse_congrats_grid
from lastz.vision import Match

_H, _W = 1440, 3440


def _ocr_text(has_header: bool) -> str:
    if has_header:
        return "Congratulations!\n1 min Training Speedup\n1"
    # The real activity-log text scraped from the incident logs.
    return (
        "Level 21\n1.8M/69.2M\n6\nCommon Rare\nLv.10 Boomer Spoils\n23:58:12\n"
        "PICHDADON teamed up and\nattacked Boomer."
    )


class TestReadCongratsPopupHeaderVerification(unittest.TestCase):
    def setUp(self):
        self.color = np.zeros((_H, _W, 3), dtype=np.uint8)

    def test_real_popup_confirmed(self):
        with patch("lastz.flows.loot_parse._ocr_region", return_value=_ocr_text(True)):
            confirmed, items = read_congrats_popup(self.color, debug=False)
        self.assertTrue(confirmed)
        self.assertTrue(items)

    def test_activity_log_text_not_confirmed_even_though_it_parses(self):
        """The buggy behavior: activity-log text still parses into
        (garbage) items even though no real popup is showing. Confirmed
        must be False so callers know not to trust it."""
        with patch("lastz.flows.loot_parse._ocr_region", return_value=_ocr_text(False)):
            confirmed, items = read_congrats_popup(self.color, debug=False)
        self.assertFalse(confirmed)
        # Documents the actual failure mode: parsing "succeeds" on
        # unrelated text, which is exactly why popup_confirmed must gate
        # trust, not `items` truthiness.
        self.assertTrue(items)

    def test_backcompat_wrapper_still_returns_items_regardless(self):
        """parse_congrats_grid() (used by drone_gift.py, which always
        shows a real popup) must keep its existing permissive behavior."""
        with patch("lastz.flows.loot_parse._ocr_region", return_value=_ocr_text(False)):
            items = parse_congrats_grid(self.color, debug=False)
        self.assertTrue(items)


class TestTryClaimAllPopupVerification(unittest.TestCase):
    def setUp(self):
        import lastz.screen as screen

        screen._last_capture_size = (_W, _H)
        screen._active_display_bounds = (0.0, 0.0, float(_W), float(_H))
        self.color = np.zeros((_H, _W, 3), dtype=np.uint8)
        self.gray = np.zeros((_H, _W), dtype=np.uint8)
        claim_btn = Match(phys_x=1719.0, phys_y=1380.0, confidence=0.985)

        for target, ret in (
            ("capture", self.gray),
            ("capture_both", (self.color, self.gray)),
            ("find_any", claim_btn),
            ("click", None),
            ("log_click", None),
            ("dismiss_overlay", None),
        ):
            patcher = patch.object(AG, target, return_value=ret)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleep_patcher = patch("time.sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def test_confirmed_popup_on_first_try_reports_real_loot(self):
        with patch.object(
            AG, "read_congrats_popup", return_value=(True, {"speedup_training_1m": 1.0})
        ):
            status = AG._try_claim_all(tab_name="Common")

        self.assertIn("Claimed All (Instant)", status)
        self.assertIn("speedup_training_1m", status)

    def test_unconfirmed_popup_does_not_fabricate_loot(self):
        """The real-incident shape: every attempt reads garbage from the
        activity-log panel (non-empty items, popup never confirmed). Must
        not be reported as a successful loot claim."""
        garbage = {"attacked_boomer": 3.0, "aussielana_teamed_up_and": 2.0}
        with patch.object(AG, "read_congrats_popup", return_value=(False, garbage)):
            status = AG._try_claim_all(tab_name="Common")

        self.assertNotIn("loot:", status)
        self.assertIn("unconfirmed", status)

    def test_retries_before_confirming(self):
        """Popup renders late (attempt 3) — must not give up after one try."""
        attempts = [
            (False, {}),
            (False, {}),
            (True, {"food": 1000.0}),
        ]
        with patch.object(AG, "read_congrats_popup", side_effect=attempts):
            status = AG._try_claim_all(tab_name="Common")

        self.assertIn("Claimed All (Instant)", status)
        self.assertIn("food", status)


if __name__ == "__main__":
    unittest.main()
