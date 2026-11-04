"""Main LCD app (zerorange.py) and web companion, without hardware."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.catalog import build_catalog
from app.core.ui import Button
from app.scenarios.registry import discover
from database import Database
from tests.fakes import FakeClock, FakeFlirc, FakeHackRF, FakeHID, FakeLCD, FakePM3, make_db
from zerorange import ZeroRange, score_line

S, B, D, U = Button.SELECT, Button.BACK, Button.DOWN, Button.UP
_EVENTS = tempfile.TemporaryDirectory()   # keep the repo's run/ untouched


def make_app(script=(), hid=None, init=True):
    registry = discover()
    clock = FakeClock()
    devices = {"proxmark": FakePM3(), "hackrf": FakeHackRF(), "flirc": FakeFlirc(),
               "hid_factory": (lambda: hid or FakeHID())}
    app = ZeroRange(lcd=FakeLCD(script, clock=clock), db=make_db(registry.scenarios),
                    registry=registry, clock=clock, devices=devices, events_dir=_EVENTS.name)
    if init:
        app.init_system()
        app.lcd.screens.clear()
    return app


class TestScoreLine(unittest.TestCase):

    def test_always_16_chars_max(self):
        for title in ("iButton", "Settings", "Extraordinary"):
            for score, max_score in ((0, 210), (210, 210), (1000, 10000)):
                line = score_line(title, score, max_score)
                self.assertLessEqual(len(line), 16, line)
                self.assertTrue(line.endswith(f"{score}/{max_score}"))


class TestZeroRange(unittest.TestCase):

    def test_menu_is_built_from_the_registry(self):
        titles = [e.title for e in make_app().menu_entries()]
        self.assertEqual(titles, ["iButton", "NFC", "RFID", "SubGHZ", "IR", "Coffee", "Garage",
                                  "Settings"])

    def test_main_menu_shows_real_max_score(self):
        app = make_app([S])
        app.main_menu()
        self.assertEqual(app.lcd.screens[0][0], ">iButton   0/210")

    def test_missing_reader_is_explained(self):
        app = make_app([S, S, B, B], hid=FakeHID(available=False))
        app.main_menu()()
        self.assertTrue(app.lcd.saw("iBtn reader N/A"))

    def test_ibutton_touch_through_the_whole_app(self):
        app = make_app([S, S, B, B], hid=FakeHID(["01-23456789ABCDEF"]))
        app.main_menu()()
        self.assertTrue(app.db.get_challenge_status(1)["completed"])
        self.assertEqual(app.db.get_total_score(), 10)

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

    def test_settings_lists_everything(self):
        labels = [label for label, _ in make_app().settings_items()]
        self.assertEqual(labels, ["Player:Player 1", "Statistics", "Leaderboard", "New session",
                                  "Reset scores", "Web login", "About"])

    def test_about_is_reachable(self):
        app = make_app([D] * 6 + [S, B])
        nxt = app.settings_screen()
        self.assertEqual(nxt, app.about_screen)
        nxt()
        self.assertTrue(app.lcd.saw("ZeroRange v"))

    def test_new_player_becomes_active_with_own_score(self):
        app = make_app([D, S])           # "+ New player"
        app.db.mark_completed(1, 5)
        app.player_screen()
        self.assertEqual(app.db.get_active_player()["name"], "Player 2")
        self.assertEqual(app.db.get_total_score(), 0)
        app.lcd.script.extend([U, S])     # back to Player 1
        app.player_screen()
        self.assertEqual(app.db.get_total_score(), 10)

    def test_leaderboard(self):
        app = make_app([B])
        app.db.mark_completed(1, 5)
        second = app.db.add_player("Bob")
        app.db.mark_completed(1, 3, player_id=second)
        app.db.mark_completed(2, 3, player_id=second)
        app.leaderboard_screen()
        self.assertEqual(app.lcd.screens[-1][0], ">1.Bob 20")

    def test_new_session_regenerates_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("app.core.session.SESSION_FILE", Path(tmp) / "s.json"), \
                mock.patch("app.core.session.SESSION_DIR", Path(tmp) / "s"):
            app = make_app([S, B])        # confirm new secrets, keep scores
            app.db.mark_completed(1, 5)
            app.session_screen()
            session = json.loads((Path(tmp) / "s.json").read_text())
            self.assertEqual(set(session["overrides"]), {"ibutton", "coffee", "garage"})
            self.assertEqual(app.db.get_total_score(), 10)
            self.assertTrue(app.lcd.saw("Session ready:"))

    def test_web_login_shows_password(self):
        app = make_app([B])
        with mock.patch("zerorange.get_trainer_password", return_value="abcd2345"):
            app.web_login_screen()
        self.assertEqual(app.lcd.screens[-1], ("user: trainer", "pass: abcd2345"))


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
        self.assertEqual(data["player"], "Player 1")
        self.assertEqual([s["completed"] for s in data["stages"]], [False, True, False])

    def test_pages(self):
        for url in ("/scenarios/coffee/", "/scenarios/garage/", "/scenarios/nfc/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        index = self.client.get("/").get_data(as_text=True)
        self.assertIn("/scenarios/coffee/", index)
        self.assertIn("/scenarios/ibutton/", index)
