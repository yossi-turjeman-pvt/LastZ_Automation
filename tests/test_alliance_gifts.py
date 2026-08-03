"""
Regression test for the "Alliance Gifts panel never actually opened" bug.

Real incident (logs/runs.log, 2026-08-02 ~02:45): the Alliance Gifts tile
click registered (high-confidence template match, click fired), but the
Gifts sub-panel (Common/Rare tabs) never actually opened. The flow then
silently ran Common/Rare claim searches against the plain Alliance grid for
the rest of the step, found nothing, and logged it as "Claimed 0" --
indistinguishable in the log from a legitimately-empty tab. A
`rare_tab.png` false-positive against a green checkmark icon in the
Alliance description text (same on-screen band the real Rare tab uses,
conf=0.80 vs threshold 0.78) then let a bogus "Rare switched" report
through too, confirmed via an offline replay of the actual failure
screenshot.

This test drives the real `log_gifts_modal_state` / `_switch_to_rare_tab`
code against synthetic vision matches built to reproduce exactly that
false-positive shape, without needing a live game or real screenshots.
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
from lastz.flows.ui_bands import BAND_ALLIANCE_GRID, BAND_RARE_TAB
from lastz.runlog import log_gifts_modal_state
from lastz.vision import Match

_H, _W = 1440, 3440


def _mid(band: tuple[float, float, float, float]) -> Match:
    """A match centered inside the given (yf0, yf1, xf0, xf1) band."""
    y0, y1, x0, x1 = band
    return Match(
        phys_x=((x0 + x1) / 2) * _W,
        phys_y=((y0 + y1) / 2) * _H,
        confidence=0.80,
    )


class TestGiftsModalStateFalsePositive(unittest.TestCase):
    """
    Reproduces the real false positive: a rare_tab-shaped match lands
    inside BAND_RARE_TAB while we're still looking at the plain Alliance
    grid (its own Gifts tile is also visible in BAND_ALLIANCE_GRID).
    """

    def setUp(self):
        self.color = np.zeros((_H, _W, 3), dtype=np.uint8)
        self.gray = np.zeros((_H, _W), dtype=np.uint8)
        # log_gifts_modal_state imports capture_both/find_template/find_any
        # locally (inside the function body), so patch the source modules.
        patcher = patch(
            "lastz.screen.capture_both", return_value=(self.color, self.gray)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_grid_tile_visible_overrides_false_positive_rare_tab(self):
        rare_fp = _mid(BAND_RARE_TAB)
        grid_tile = _mid(BAND_ALLIANCE_GRID)

        def fake_find_template(gray, name, thr):
            if name == "rare_tab.png":
                return rare_fp
            if name == "alliance_gifts_precise.png":
                return grid_tile
            return None

        with patch("lastz.vision.find_template", side_effect=fake_find_template), \
             patch("lastz.vision.find_any", return_value=None):
            state = log_gifts_modal_state("test_false_positive")

        self.assertEqual(state, "alliance_grid_visible_gifts_likely_closed")

    def test_real_open_panel_not_rejected(self):
        rare_real = _mid(BAND_RARE_TAB)

        def fake_find_template(gray, name, thr):
            if name == "rare_tab.png":
                return rare_real
            return None  # grid tile absent -- real Gifts panel covers it

        with patch("lastz.vision.find_template", side_effect=fake_find_template), \
             patch("lastz.vision.find_any", return_value=Match(1.0, 1.0, 0.9)):
            state = log_gifts_modal_state("test_healthy")

        self.assertEqual(state, "gifts_modal_open")


class TestSwitchToRareTabFalsePositive(unittest.TestCase):
    def setUp(self):
        import lastz.screen as screen

        self.color = np.zeros((_H, _W, 3), dtype=np.uint8)
        self.gray = np.zeros((_H, _W), dtype=np.uint8)
        screen._last_capture_size = (_W, _H)
        screen._active_display_bounds = (0.0, 0.0, float(_W), float(_H))
        for target in ("capture_both", "click", "annotate_and_save"):
            patcher = patch.object(
                AG, target,
                return_value=(self.color, self.gray) if target == "capture_both" else None,
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_refuses_to_click_false_positive_rare_tab(self):
        rare_fp = _mid(BAND_RARE_TAB)
        grid_tile = _mid(BAND_ALLIANCE_GRID)

        def fake_find_template(gray, name, thr):
            return rare_fp if name == "rare_tab.png" else None

        def fake_find_all_templates(gray, name, thr):
            return [grid_tile] if name == "alliance_gifts_precise.png" else []

        with patch.object(AG, "find_template", side_effect=fake_find_template), \
             patch.object(AG, "find_all_templates", side_effect=fake_find_all_templates):
            result = AG._switch_to_rare_tab()

        self.assertFalse(result)
        AG.click.assert_not_called()

    def test_clicks_real_rare_tab_when_grid_not_visible(self):
        rare_real = _mid(BAND_RARE_TAB)

        def fake_find_template(gray, name, thr):
            return rare_real if name == "rare_tab.png" else None

        def fake_find_all_templates(gray, name, thr):
            return []  # no grid tile -- real panel is open

        with patch.object(AG, "find_template", side_effect=fake_find_template), \
             patch.object(AG, "find_all_templates", side_effect=fake_find_all_templates), \
             patch.object(AG, "find_any", return_value=Match(1.0, 1.0, 0.9)):
            result = AG._switch_to_rare_tab()

        self.assertTrue(result)
        AG.click.assert_called_once()


class TestOpenAllianceMenuVerification(unittest.TestCase):
    """
    Real overnight incident (2026-08-02, same night as the above fix): the
    shield click was logged as succeeding, but 6 retries of the Alliance
    Gifts tile search all found nothing, and the eventual crash screenshot
    showed the plain wilderness map -- the Alliance menu itself had never
    actually opened. `_open_alliance_menu` must not report success just
    because the shield click fired.
    """

    def setUp(self):
        import lastz.screen as screen

        self.color = np.zeros((_H, _W, 3), dtype=np.uint8)
        self.gray = np.zeros((_H, _W), dtype=np.uint8)
        screen._last_capture_size = (_W, _H)
        screen._active_display_bounds = (0.0, 0.0, float(_W), float(_H))
        for target in ("capture_both", "capture", "click"):
            patcher = patch.object(
                AG, target,
                return_value=(self.color, self.gray) if target == "capture_both"
                else (self.gray if target == "capture" else None),
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_refuses_success_when_grid_never_appears(self):
        shield = _mid(AG.BAND_HUD_SHIELD)

        with patch.object(AG, "find_all_templates", return_value=[shield]), \
             patch.object(AG, "find_template", return_value=None), \
             patch("time.sleep"):
            result = AG._open_alliance_menu(attempts=3, delay=0.0)

        self.assertFalse(result)

    def test_confirms_success_when_grid_appears(self):
        shield = _mid(AG.BAND_HUD_SHIELD)
        grid_tile = _mid(BAND_ALLIANCE_GRID)

        def fake_find_template(gray, name, thr):
            return grid_tile if name == "alliance_gifts_precise.png" else None

        with patch.object(AG, "find_all_templates", return_value=[shield]), \
             patch.object(AG, "find_template", side_effect=fake_find_template), \
             patch("time.sleep"):
            result = AG._open_alliance_menu(attempts=3, delay=0.0)

        self.assertTrue(result)
        AG.click.assert_called_once()


if __name__ == "__main__":
    unittest.main()
