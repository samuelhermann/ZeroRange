"""Simulation mode: inbox, simulated devices, terminal LCD."""

import tempfile
import unittest
from pathlib import Path

from app.core.nfc_file import parse_nfc
from app.sim import build_sim_environment
from app.sim.inbox import Inbox, SimHub
from app.sim.lcd import BACK, SELECT, TerminalLCD
from challenges.coffee.stage2_dump import Stage2
from challenges.coffee.stage3_refill import Stage3
from challenges.coffee.value_block import encode
from tests.fakes import make_stage


class TestSim(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox_path = Path(self.tmp.name) / "inbox.jsonl"
        self.env = build_sim_environment(lcd=TerminalLCD(interactive=False, mirror_dir=Path(self.tmp.name)),
                                         inbox=self.inbox_path,
                                         flag=Path(self.tmp.name) / "flag")
        self.inbox = Inbox(self.inbox_path)

    def tearDown(self):
        self.env.close()
        self.tmp.cleanup()

    def test_flag_lifecycle(self):
        self.assertTrue(self.env.flag.exists())
        self.env.close()
        self.assertFalse(self.env.flag.exists())

    def test_inbox_validation_and_routing(self):
        with self.assertRaises(ValueError):
            self.inbox.push("nfc")
        with self.assertRaises(ValueError):
            self.inbox.push("laser", power=9000)
        self.inbox.push("ibutton", uid="01AA")
        self.inbox.push("nfc", uid="04BB")
        hid = self.env.devices["hid_factory"]()
        self.assertEqual(hid.take_uid(), "01AA")
        self.assertIsNone(hid.take_uid())
        self.assertEqual(self.env.devices["proxmark"].nfc_scan()["uid"], "04BB")

    def test_partial_lines_are_not_lost(self):
        hub = SimHub(self.inbox_path)
        with open(self.inbox_path, "a") as fh:
            fh.write('{"kind": "ibutton", "uid": "01')
        self.assertIsNone(hub.take("ibutton"))
        with open(self.inbox_path, "a") as fh:
            fh.write('CC"}\n')
        self.assertEqual(hub.take("ibutton")["uid"], "01CC")

    def test_pm3_checks_keys_of_the_emulated_badge(self):
        pm3 = self.env.devices["proxmark"]
        pm3.emulate_mfc_from_file("challenges/coffee/badges/credit_low.nfc")
        good = pm3.read_block(40, bytes.fromhex("B4EEC0FFEE11"), "B")
        self.assertEqual(good, parse_nfc("challenges/coffee/badges/credit_low.nfc")[40])
        with self.assertRaises(RuntimeError) as ctx:
            pm3.read_block(40, bytes.fromhex("FFFFFFFFFFFF"), "B")
        self.assertIn("Auth", type(ctx.exception).__name__)

    def test_coffee_stage2_manual_verify_in_sim(self):
        stage, lcd, db, _ = make_stage(Stage2, script=[SELECT, BACK], hw=self.env.devices["proxmark"],
                                       config={"master_key_b_hex": "B4EEC0FFEE11"})
        self.assertEqual(stage.run(), 10)

    def test_coffee_stage3_with_injected_card_and_block(self):
        self.inbox.push("pm3_card", path="challenges/coffee/badges/credit_low.nfc")
        self.inbox.push("pm3_block", block=40, data=encode(9000, 40).hex())
        stage, lcd, _, _ = make_stage(Stage3, script=[SELECT, BACK], hw=self.env.devices["proxmark"])
        self.assertEqual(stage.run(), 10)
        self.assertTrue(lcd.saw("90,00 EUR OK!"))

    def test_rf_and_ir(self):
        self.inbox.push("rf", strength=-30)
        self.inbox.push("ir", keycode="KEY_1", protocol="RC5")
        ok, path, info = self.env.devices["hackrf"].capture_signal(frequency=433_920_000)
        self.assertTrue(ok and Path(path).exists())
        self.assertEqual(info["signal_strength"], -30)
        received, event = self.env.devices["flirc"].receive_ir(timeout=1)
        self.assertEqual((received, event["protocol"]), (True, "RC5"))

    def test_terminal_lcd_keys_expire_and_mirror(self):
        lcd = self.env.lcd
        lcd.write_line(0, "hello")
        lcd.press(SELECT)
        self.assertFalse(lcd.button_pressed(BACK))
        self.assertTrue(lcd.button_pressed(SELECT))
        self.assertFalse(lcd.button_pressed(SELECT))
        self.assertEqual(lcd.lines[0], "hello".ljust(16))
        import json
        state = json.loads((Path(self.tmp.name) / "lcd_state.json").read_text())
        self.assertEqual(state["line1"], "hello".ljust(16))
        (Path(self.tmp.name) / "web_button.json").write_text('{"button": 5}')
        self.assertTrue(lcd.button_pressed(BACK))   # web LCD buttons drive the sim too


class TestSimDatabaseSwitch(unittest.TestCase):

    def test_web_follows_the_sim_database(self):
        from unittest import mock
        from app.core import paths
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "sim_mode"
            with mock.patch.object(paths, "SIM_FLAG", flag):
                self.assertEqual(paths.active_db_path(), paths.DB_PATH)
                flag.write_text("1")
                self.assertEqual(paths.active_db_path(), paths.SIM_DB_PATH)
