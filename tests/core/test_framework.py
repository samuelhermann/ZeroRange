"""Registry, validator, catalog, runner and shared NFC helpers."""

import sys
import tempfile
import unittest
from pathlib import Path

from app.catalog import CLASSIC_MODULES, build_catalog, next_free_ids
from app.core.nfc_file import make_mfc1k, parse_nfc, render_nfc
from app.core.ui import Button
from app.scenarios.base import ScenarioDef, Stage, Tool
from app.scenarios.registry import Registry, discover
from app.scenarios.validate import validate_all, validate_scenario
from tests.fakes import make_runner

S, B = Button.SELECT, Button.BACK


class Boom(Stage):
    challenge_id = 900
    number = 1
    title = "Boom"

    def run(self):
        raise RuntimeError("kaboom")


class Easy(Stage):
    challenge_id = 901
    number = 2
    title = "Easy"
    points = 5

    def run(self):
        self.start_timer()
        return self.award()


class Helper(Tool):
    title = "Helper"

    def run(self):
        self.ui.show("helping", "", hold=1)
        return 99  # tools never score


DEMO = ScenarioDef(key="demo", title="Demo", stages=(Boom, Easy), tools=(Helper,),
                   complete_lines=("DEMO", "DONE!"))


class TestRegistry(unittest.TestCase):

    def test_discovers_bundled_scenarios_in_order(self):
        reg = discover()
        self.assertEqual(reg.keys()[:2], ["coffee", "garage"])
        self.assertEqual(reg.errors, {})

    def test_broken_scenario_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "zr_tmp_scenarios"
            for name, body in {
                "good": "from tests.core.test_framework import DEMO as d\n"
                        "from dataclasses import replace\nSCENARIO = replace(d, key='good')\n",
                "bad": "raise ImportError('missing lib')\n",
                "wrong": "SCENARIO = 42\n",
            }.items():
                (pkg / name).mkdir(parents=True)
                (pkg / name / "scenario.py").write_text(body)
            sys.path.insert(0, tmp)
            try:
                reg = discover(pkg, package="zr_tmp_scenarios")
            finally:
                sys.path.remove(tmp)
        self.assertEqual(reg.keys(), ["good"])
        self.assertEqual(set(reg.errors), {"bad", "wrong"})


class TestValidator(unittest.TestCase):

    def test_bundled_scenarios_have_no_errors(self):
        errors = [i for i in validate_all() if i.level == "error"]
        self.assertEqual(errors, [])

    def test_detects_problems(self):
        class Dup(Stage):
            challenge_id = 16        # taken by coffee
            number = 3
            title = "Way too long stage title"
            config_keys = ("needed",)
            file_keys = ("badge",)

            @classmethod
            def defaults(cls):
                return {"badge": "nope/missing.nfc"}

        bad = ScenarioDef(key="Bad-Key", title="A very long title", stages=(Dup,),
                          disclaimer=("x" * 20,))
        reg = Registry(scenarios=[discover().get("coffee"), bad])
        messages = [str(i) for i in validate_all(reg, config={})]
        joined = "\n".join(messages)
        for fragment in ("already used by coffee", "must match", "stage numbers",
                         "'Bad-Key.needed' is missing", "not found", "is 24 chars",
                         "LCD shows 16"):
            self.assertIn(fragment, joined)

    def test_placeholder_warning(self):
        coffee = discover().get("coffee")
        issues = validate_scenario(coffee, {"coffee": {"technician_uid": "REPLACE_ME"}})
        self.assertTrue(any(i.level == "warning" and "placeholder" in i.message for i in issues))


class TestCatalog(unittest.TestCase):

    def test_ids_are_unique(self):
        rows = build_catalog(discover().scenarios)
        ids = [r[0] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(m.max_points for m in CLASSIC_MODULES), 150)

    def test_next_free_ids(self):
        self.assertEqual(next_free_ids([(1, "", "", "", 1), (7, "", "", "", 1)], 3), [8, 9, 10])
        self.assertEqual(next_free_ids([], 1), [1])


class TestRunner(unittest.TestCase):

    def test_crashing_stage_is_isolated(self):
        runner, lcd, db = make_runner(DEMO, script=[S, B, B])
        self.assertEqual(runner.run(), 0)
        self.assertTrue(lcd.saw("Boom error!"))
        self.assertTrue(runner.sse.of("stage_error"))

    def test_tool_points_ignored_and_celebration(self):
        runner, lcd, db = make_runner(DEMO, script=[Button.DOWN, Button.DOWN, S,  # tool
                                                     Button.UP, S, B])           # Easy
        db.mark_completed(900, 1)
        self.assertEqual(runner.run(), 5)
        self.assertTrue(lcd.saw("helping"))
        self.assertTrue(lcd.saw("DONE! 15/15"))

    def test_footer_fits_lcd(self):
        runner, lcd, _ = make_runner(DEMO, script=[B])
        runner.run()
        self.assertEqual(lcd.screens[0], (">Boom", "U/D SEL=Go 0/15"))


class TestNfcFile(unittest.TestCase):

    def test_generated_badge_round_trips(self):
        blocks = make_mfc1k(bytes.fromhex("01020304"), keys_b={10: bytes.fromhex("A1A2A3A4A5A6")},
                            data={41: b"hello"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.nfc"
            path.write_text(render_nfc(blocks))
            parsed = parse_nfc(path)
        self.assertEqual(parsed, blocks)
        self.assertEqual(parsed[43][10:], bytes.fromhex("A1A2A3A4A5A6"))
        self.assertEqual(parsed[0][4], 0x01 ^ 0x02 ^ 0x03 ^ 0x04)  # BCC

    def test_reproduces_bundled_tech_room_badge(self):
        blocks = make_mfc1k(bytes.fromhex("04B73AC2"), keys_a={0: bytes.fromhex("F15EC0DE0017")},
                            data={1: b"GARAGE-TECH-ROOM"})
        self.assertEqual(blocks, parse_nfc("challenges/garage/badges/tech_room.nfc"))


if __name__ == "__main__":
    unittest.main()
