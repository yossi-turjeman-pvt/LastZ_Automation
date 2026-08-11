"""
Unit tests for the HQ Farm Resources flow (lastz/flows/farm_resources.py).

Follows tests/test_alliance_gifts.py's style: patch functions on the flow
module object (farm_resources.py imports them directly into its own
namespace, so patching the source module wouldn't take effect), build
synthetic capture-sized screens, and construct MatchWithBBox fixtures
placed inside/outside the relevant spatial bands rather than driving a
real game or real screenshots.

Design under test (corrected 2026-08-11, twice):

1. Clicking ANY ONE farm badge — round or full, any resource type —
   collects every farm building's production across the whole base. So the
   flow only needs to find and click a single match, then stop; it does not
   need to visit every resource type.
2. A synthetic click can silently fail to register in the game (verified
   live: a badge sat unchanged after being "clicked" several times in a
   row). The flow must verify a click actually worked (the badge is gone on
   re-scan) before trusting it, retrying a few times before giving up on
   that particular match — never reporting success on faith.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lastz.flows import farm_resources as FR
from lastz.flows.ui_bands import BAND_HQ_MAP
from lastz.vision import MatchWithBBox

_H, _W = 1440, 3440


def _match(xf: float, yf: float, *, conf: float = 0.85, w: int = 60, h: int = 40) -> MatchWithBBox:
    return MatchWithBBox(phys_x=xf * _W, phys_y=yf * _H, phys_w=w, phys_h=h, confidence=conf)


def _mid_hq_band(*, conf: float = 0.85) -> MatchWithBBox:
    y0, y1, x0, x1 = BAND_HQ_MAP
    return _match((x0 + x1) / 2, (y0 + y1) / 2, conf=conf)


class _BaseFarmResourcesTest(unittest.TestCase):
    """Shared setUp: stub every external interaction point (no real game)."""

    def setUp(self):
        import lastz.screen as screen

        self.color = np.zeros((_H, _W, 3), dtype=np.uint8)
        self.gray = np.zeros((_H, _W), dtype=np.uint8)
        screen._last_capture_size = (_W, _H)
        screen._active_display_bounds = (0.0, 0.0, float(_W), float(_H))

        self.drag_calls: list[tuple] = []
        self.click_calls: list[tuple] = []

        def fake_drag(x1, y1, x2, y2, **kwargs):
            self.drag_calls.append((x1, y1, x2, y2))

        def fake_click(x, y):
            self.click_calls.append((x, y))

        patches = {
            "ensure_game_running": lambda: None,
            "focus_game": lambda: None,
            "reset_ui": lambda **kwargs: None,
            "navigate_to_hq": lambda screen_: True,
            "is_hq_mode": lambda screen_: True,
            "navigate_to_wilderness": lambda: None,
            "capture_both": lambda: (self.color, self.gray),
            "window_click": lambda fx, fy: (100.0, 100.0),
            "scale_ref_logical_delta": lambda dx, dy: (float(dx), float(dy)),
            "scroll_wheel": lambda *a, **k: None,
            "drag": fake_drag,
            "click": fake_click,
        }
        for name, fn in patches.items():
            p = patch.object(FR, name, fn)
            p.start()
            self.addCleanup(p.stop)

        sleep_patcher = patch("time.sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)


def _stateful_match_mock(template_name: str, match: MatchWithBBox, click_calls: list):
    """
    find_all_templates fake that returns `match` for `template_name` until a
    click has fired (simulating a real, successfully-collected badge), then
    returns nothing — i.e. the click worked and removed it.
    """
    def fake_find_all(gray, name, thresh, exclude_regions=None):
        if name == template_name and not click_calls:
            return [match]
        return []
    return fake_find_all


class TestFindAnyFarmBadge(_BaseFarmResourcesTest):
    """_find_any_farm_badge: BAND_HQ_MAP filtering + best-of-all-templates pick."""

    def test_match_outside_hq_band_is_rejected(self):
        # Top HUD strip (yf ~0.03) is above BAND_HQ_MAP's y0=0.06 floor.
        hud_fp = _match(0.5, 0.03)

        with patch.object(FR, "find_all_templates", return_value=[hud_fp]):
            result = FR._find_any_farm_badge(self.gray, [], dedupe_radius=80)

        self.assertIsNone(result)

    def test_match_inside_hq_band_is_accepted(self):
        real = _mid_hq_band()

        with patch.object(FR, "find_all_templates", return_value=[real]):
            result = FR._find_any_farm_badge(self.gray, [], dedupe_radius=80)

        self.assertIsNotNone(result)
        label, match = result
        self.assertIn(label, FR._DETECT_TEMPLATES)
        self.assertAlmostEqual(match.phys_x, real.phys_x)

    def test_picks_highest_confidence_across_templates(self):
        # Every template "finds" a match at the same spot but with
        # different confidences — the winner should be the highest one,
        # regardless of which template label it came from.
        low = _mid_hq_band(conf=0.80)
        high = MatchWithBBox(
            phys_x=low.phys_x, phys_y=low.phys_y,
            phys_w=low.phys_w, phys_h=low.phys_h, confidence=0.95,
        )

        def fake_find_all(gray, name, thresh, exclude_regions=None):
            # exp_round -> low, exp_full -> high, others -> nothing
            if name == "farm_exp_round.png":
                return [low]
            if name == "farm_exp_full.png":
                return [high]
            return []

        with patch.object(FR, "find_all_templates", side_effect=fake_find_all):
            label, match = FR._find_any_farm_badge(self.gray, [], dedupe_radius=80)

        self.assertEqual(label, "exp_full")
        self.assertAlmostEqual(match.confidence, 0.95)

    def test_no_templates_match_returns_none(self):
        with patch.object(FR, "find_all_templates", return_value=[]):
            result = FR._find_any_farm_badge(self.gray, [], dedupe_radius=80)

        self.assertIsNone(result)


class TestClickAndVerify(_BaseFarmResourcesTest):
    """
    The core fix: a click that doesn't actually register must not be
    reported as a success. Live-verified real bug (2026-08-11) — a badge
    sat completely unchanged, pixel-for-pixel, after being "clicked"
    multiple times in a row.
    """

    def test_click_that_removes_the_badge_verifies_as_success(self):
        match = _mid_hq_band()
        cfg = FR.farm_resources_cfg()

        with patch.object(
            FR, "find_all_templates",
            side_effect=_stateful_match_mock("farm_exp_full.png", match, self.click_calls),
        ):
            ok = FR._click_and_verify("exp_full", match, 1440, [], cfg)

        self.assertTrue(ok)
        self.assertEqual(len(self.click_calls), 1)

    def test_click_that_does_not_remove_the_badge_retries_then_gives_up(self):
        match = _mid_hq_band()
        cfg = FR.farm_resources_cfg()

        # Badge is ALWAYS still there, no matter how many times we click —
        # simulates the real silent-click-failure bug.
        with patch.object(FR, "find_all_templates", return_value=[match]):
            ok = FR._click_and_verify("exp_full", match, 1440, [], cfg, max_attempts=3)

        self.assertFalse(ok)
        self.assertEqual(len(self.click_calls), 3)

    def test_succeeds_on_a_later_retry_not_just_the_first(self):
        match = _mid_hq_band()
        cfg = FR.farm_resources_cfg()
        calls = {"n": 0}

        def fake_find_all(gray, name, thresh, exclude_regions=None):
            calls["n"] += 1
            # Still present for the first re-check (after click #1), gone
            # by the second re-check (after click #2).
            return [match] if calls["n"] <= 1 else []

        with patch.object(FR, "find_all_templates", side_effect=fake_find_all):
            ok = FR._click_and_verify("exp_full", match, 1440, [], cfg, max_attempts=3)

        self.assertTrue(ok)
        self.assertEqual(len(self.click_calls), 2)


class TestFindAndCollect(_BaseFarmResourcesTest):
    def test_no_matches_anywhere_clicks_nothing(self):
        with patch.object(FR, "find_all_templates", return_value=[]):
            found = FR._find_and_collect()

        self.assertIsNone(found)
        self.assertEqual(self.click_calls, [])

    def test_match_at_center_clicks_once_and_stops(self):
        match = _mid_hq_band()

        with patch.object(
            FR, "find_all_templates",
            side_effect=_stateful_match_mock("farm_exp_round.png", match, self.click_calls),
        ):
            found = FR._find_and_collect()

        self.assertEqual(found, "exp_round")
        self.assertEqual(len(self.click_calls), 1)
        # Found at the very first (center) capture -> no pan drags needed to
        # locate it, only the recenter-on-the-way-out (0 walked = 0 drags).
        self.assertEqual(self.drag_calls, [])

    def test_match_only_at_a_pan_position_still_found(self):
        match = _mid_hq_band()
        calls = {"n": 0}

        def fake_find_all(gray, name, thresh, exclude_regions=None):
            calls["n"] += 1
            # Nothing at center (first 4 calls, one per template); a match
            # appears starting from the first pan position's checks, and
            # disappears for good once a click has fired.
            if calls["n"] > 4 and name == "farm_exp_round.png" and not self.click_calls:
                return [match]
            return []

        with patch.object(FR, "find_all_templates", side_effect=fake_find_all):
            found = FR._find_and_collect()

        self.assertEqual(found, "exp_round")
        self.assertEqual(len(self.click_calls), 1)
        # Recenter reverses exactly the pans actually walked to reach the hit.
        self.assertGreater(len(self.drag_calls), 0)

    def test_stops_at_first_hit_does_not_walk_full_grid(self):
        match = _mid_hq_band()

        with patch.object(
            FR, "find_all_templates",
            side_effect=_stateful_match_mock("farm_exp_round.png", match, self.click_calls),
        ):
            FR._find_and_collect()

        # Found at center; recenter with 0 walked steps means 0 drag calls
        # total (never even walked the first pan direction).
        self.assertEqual(self.drag_calls, [])

    def test_a_click_that_never_verifies_does_not_get_reported_as_found(self):
        # The real 2026-08-11 bug, at the _find_and_collect level: a match
        # that never actually clears after clicking must not make the whole
        # cycle report success.
        match = _mid_hq_band()

        with patch.object(FR, "find_all_templates", return_value=[match]):
            found = FR._find_and_collect()

        self.assertIsNone(found)
        # Every position attempted it (3 retries each) before giving up.
        self.assertGreater(len(self.click_calls), 3)


class TestRunFarmResourcesFlow(_BaseFarmResourcesTest):
    def test_disabled_in_config_skips_without_touching_the_game(self):
        disabled_cfg = dict(FR.farm_resources_cfg())
        disabled_cfg["enabled"] = False

        with patch.object(FR, "farm_resources_cfg", return_value=disabled_cfg):
            status = FR.run_farm_resources_flow(skip_reset=True)

        self.assertIn("Skipped", status)
        self.assertEqual(self.click_calls, [])

    def test_hq_nav_failure_returns_skip_status(self):
        with patch.object(FR, "is_hq_mode", return_value=False), \
             patch.object(FR, "navigate_to_hq", return_value=False), \
             patch.object(FR, "find_all_templates", return_value=[]):
            status = FR.run_farm_resources_flow(skip_reset=True)

        self.assertIn("Skipped", status)
        self.assertEqual(self.click_calls, [])

    def test_collects_when_any_badge_is_found(self):
        match = _mid_hq_band()

        with patch.object(
            FR, "find_all_templates",
            side_effect=_stateful_match_mock("farm_food_full.png", match, self.click_calls),
        ):
            status = FR.run_farm_resources_flow(skip_reset=True)

        self.assertTrue(status.startswith("Collected"))
        self.assertIn("food_full", status)

    def test_no_badges_found_is_a_clean_skip(self):
        with patch.object(FR, "find_all_templates", return_value=[]):
            status = FR.run_farm_resources_flow(skip_reset=True)

        self.assertIn("Skipped", status)
        self.assertEqual(self.click_calls, [])


if __name__ == "__main__":
    unittest.main()
