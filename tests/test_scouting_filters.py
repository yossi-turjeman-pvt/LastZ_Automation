"""Unit tests for scouting filters, registry, and OCR parsers."""
from __future__ import annotations

import time
import unittest

from lastz.ocr import is_blacklisted, parse_alliance_tag, parse_city_label, parse_map_hq_label, parse_power_value
from lastz.scouting.filters import evaluate_map_label, evaluate_modal
from lastz.scouting.models import FilterConfig, MapLabel, ModalFields
from lastz.scouting.registry import already_scouted, mark_scouted_target


class TestOcrParsers(unittest.TestCase):
    def test_parse_alliance_tag(self):
        self.assertEqual(parse_alliance_tag("[RT63]Alexsimono"), "RT63")
        self.assertEqual(parse_alliance_tag("Alliance: [vlnz]"), "VLNZ")
        self.assertIsNone(parse_alliance_tag("PlainPlayer"))

    def test_parse_map_hq_label(self):
        parsed = parse_map_hq_label("[RT63]Alexsimono\n23")
        self.assertEqual(parsed["alliance_tag"], "RT63")
        self.assertEqual(parsed["player_name"], "Alexsimono")
        self.assertEqual(parsed["hq_level"], 23)

    def test_parse_power_value(self):
        self.assertEqual(parse_power_value("Power 38,500"), 38500)
        self.assertEqual(parse_power_value("38500"), 38500)
        self.assertEqual(parse_power_value("Power: 40000"), 40000)

    def test_is_blacklisted(self):
        self.assertTrue(is_blacklisted("RT63", ["rt63", "ABC"]))
        self.assertFalse(is_blacklisted("XYZ", ["RT63"]))


class TestFilters(unittest.TestCase):
    def _cfg(self) -> FilterConfig:
        return FilterConfig(
            own_alliance="MYTAG",
            alliance_blacklist=["RT63"],
            max_hq_level=24,
            max_power=40000,
        )

    def test_own_alliance_skipped(self):
        label = MapLabel(alliance_tag="MYTAG", player_name="ally", hq_level=20)
        d = evaluate_map_label(label, self._cfg())
        self.assertFalse(d.allowed)
        self.assertEqual(d.status, "skipped_own_alliance")

    def test_blacklist_skipped(self):
        label = MapLabel(alliance_tag="RT63", player_name="enemy", hq_level=20)
        d = evaluate_map_label(label, self._cfg())
        self.assertFalse(d.allowed)
        self.assertEqual(d.status, "skipped_blacklist")

    def test_level_cap(self):
        label = MapLabel(alliance_tag="ABC", player_name="high", hq_level=25)
        d = evaluate_map_label(label, self._cfg())
        self.assertFalse(d.allowed)
        self.assertEqual(d.status, "skipped_level")

    def test_level_ok(self):
        label = MapLabel(alliance_tag="ABC", player_name="ok", hq_level=23)
        d = evaluate_map_label(label, self._cfg())
        self.assertTrue(d.allowed)

    def test_power_cap_modal(self):
        modal = ModalFields(alliance_tag="ABC", power=50000)
        d = evaluate_modal(modal, self._cfg())
        self.assertFalse(d.allowed)
        self.assertEqual(d.status, "skipped_power")

    def test_power_ok_modal(self):
        modal = ModalFields(alliance_tag="ABC", power=38500)
        d = evaluate_modal(modal, self._cfg())
        self.assertTrue(d.allowed)


class TestRegistry(unittest.TestCase):
    def test_skip_already_scouted_permanent(self):
        state = {"scouted": {}}
        mark_scouted_target(state, player_key="bob", display_name="[ABC]bob", alliance="ABC", hq_level=20)
        self.assertTrue(already_scouted("bob", state))
        self.assertFalse(already_scouted("other", state))


if __name__ == "__main__":
    unittest.main()
