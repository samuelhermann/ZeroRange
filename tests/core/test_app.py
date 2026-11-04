"""Main LCD app (zerorange.py) and web companion, without hardware."""

import json
import tempfile
import unittest
from pathlib import Path

from app.catalog import CLASSIC_MODULES, build_catalog
from app.core.ui import Button
from app.scenarios.registry import discover
from database import Database
from tests.fakes import FakeClock, FakeLCD, make_db
from zerorange import ZeroRange, score_line

S, B, D = Button.SELECT, Button.BACK, Button.DOWN


def make_app(script=()):
    registry = discover()
    clock = FakeClock()
    app = ZeroRange(lcd=FakeLCD(script, clock=clock), db=make_db(registry.scenarios),
                    registry=registry, clock=clock)
    return app


class TestScoreLine(unittest.TestCase):

    def test_always_16_chars_max(self):
        for title in ("iButton", "Settings", "Extraordinary"):
            for score, max_score in ((0, 210), (210, 210), (1000, 10000)):
                line = score_line(title, score, max_score)
                self.assertLessEqual(len(line), 16, line)
                self.assertTrue(line.endswith(f"{score}/{max_score}"))


class TestZeroRange(unittest.TestCase):

    def test_menu_is_data_driven(self):
        app = make_app()
        titles = [e.title for e in app.menu_entries()]
        # scenario runners are only built by init_system()
        self.assertEqual(titles, ["iButton", "NFC", "RFID", "SubGHZ", "IR", "Settings"])

    def test_main_menu_shows_real_max_score(self):
        app = make_app([S])
        app.main_menu()
        self.assertEqual(app.lcd.screens[0][0], ">iButton   0/210")

    def test_unavailable_module_explains(self):
        app = make_app([S, B])
        screen = app.main_menu()
        self.assertEqual(screen(), app.main_menu)
        self.assertTrue(app.lcd.saw("iBtn Not Ready"))

    def test_classic_challenge_success_is_recorded(self):
        class Handler:
            def challenge_1_touch(self):
                return 10
        app = make_app()
        module = CLASSIC_MODULES[0]
        self.assertEqual(app.run_classic_challenge(Handler(), module.challenges[0]), 10)
        self.assertTrue(app.db.get_challenge_status(1)["completed"])
        self.assertEqual(app.db.get_stats()["total_attempts"], 1)

    def test_classic_module_menu_runs_selected_challenge(self):
        calls = []

        class Handler:
            def challenge_2_clone(self):
                calls.append("clone")
                return 0
        app = make_app([D, S, B])
        app.ibutton = Handler()
        app._module_screen(CLASSIC_MODULES[0])()
        self.assertEqual(calls, ["clone"])

    def test_stats_screen_uses_real_totals(self):
        app = make_app([B])
        app.db.mark_completed(1, 5)
        app.stats_screen()
        self.assertEqual(app.lcd.screens[-1], ("Score:10/210", "1/21 Tries:0"))

    def test_reset_requires_confirmation(self):
        app = make_app([B])
        app.db.mark_completed(1, 5)
        self.assertEqual(app.reset_screen(), app.settings_screen)
        self.assertEqual(app.db.get_total_score(), 10)
        app = make_app([S])
        app.db.mark_completed(1, 5)
        app.reset_screen()
        self.assertEqual(app.db.get_total_score(), 0)

    def test_settings_about_is_reachable(self):
        app = make_app([D, D, S, B])
        nxt = app.settings_screen()
        self.assertEqual(nxt, app.about_screen)
        nxt()
        self.assertTrue(app.lcd.saw("ZeroRange v"))


class TestWeb(unittest.TestCase):

    def setUp(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("flask not installed")
        from app.web import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "scores.db"
        registry = discover()
        db = Database(str(self.db_path), catalog=build_catalog(registry.scenarios))
        db.mark_completed(17, 12)
        db.close()
        self.events_dir = Path(self.tmp.name)
        self.client = create_app(registry, events_dir=self.events_dir,
                                 db_path=self.db_path).test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_reflects_database(self):
        data = self.client.get("/scenarios/coffee/api/status").get_json()
        self.assertEqual(data["score"], 10)
        self.assertEqual([s["completed"] for s in data["stages"]], [False, True, False])

    def test_pages(self):
        for url in ("/scenarios/coffee/", "/scenarios/garage/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        index = self.client.get("/").get_data(as_text=True)
        self.assertIn("/scenarios/coffee/", index)
        self.assertIn("/scenarios/garage/", index)

    def test_garage_debug_route_publishes_event(self):
        self.assertEqual(self.client.post("/scenarios/garage/debug/send-press").status_code, 204)
        line = (self.events_dir / "garage.jsonl").read_text().splitlines()[-1]
        self.assertEqual(json.loads(line)["event"], "press_emitted")
