"""iButton, NFC, RFID, SubGHZ and IR modules (ex "classic" handlers)."""

import random
import tempfile
import unittest
from pathlib import Path

from app.core.session import dallas_crc8, new_session, random_ds1990_uid
from app.core.ui import Button
from app.scenarios.registry import discover
from challenges.ibutton import stages as ib
from challenges.ibutton.scenario import SCENARIO as IBUTTON
from challenges.ir import stages as ir
from challenges.nfc import stages as nfc
from challenges.rfid import stages as rfid
from challenges.subghz import stages as sub
from tests.fakes import FakeFlirc, FakeHackRF, FakeHID, FakePM3, Idle, make_stage

S, B, R = Button.SELECT, Button.BACK, Button.RIGHT


def done(db, cid):
    return db.get_challenge_status(cid)["completed"]


class TestIButton(unittest.TestCase):

    def test_touch(self):
        stage, lcd, db, _ = make_stage(ib.TouchRead, script=[B], hw=FakeHID(["01-AABBCCDDEEFF00"]))
        self.assertEqual(stage.run(), 10)
        self.assertTrue(done(db, 1))

    def test_touch_timeout_then_back(self):
        stage, lcd, db, _ = make_stage(ib.TouchRead, script=[Idle(61), B], hw=FakeHID())
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("TIMEOUT"))

    def test_retry_is_a_loop_not_recursion(self):
        # 50 timeouts + retries used to grow the Python stack (recursive retry).
        script = [x for _ in range(50) for x in (Idle(61), S)] + [Idle(61), B]
        stage, _, _, _ = make_stage(ib.TouchRead, script=script, hw=FakeHID())
        self.assertEqual(stage.run(), 0)

    def test_clone_success_and_mismatch(self):
        stage, _, db, _ = make_stage(ib.Clone, script=[B], hw=FakeHID(["01-11", "01-11"]))
        self.assertEqual(stage.run(), 10)
        stage, lcd, db, _ = make_stage(ib.Clone, script=[B], hw=FakeHID(["01-11", "01-22"]))
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("WRONG ID"))

    def test_emulate_target_accepts_both_byte_orders(self):
        for uid in ("01CAFE11111111D4", "01-11111111FECAD4"):
            stage, _, _, _ = make_stage(ib.EmulateTarget, script=[B], hw=FakeHID([uid]))
            self.assertEqual(stage.run(), 10, uid)

    def test_emulate_target_wrong_id_keeps_waiting(self):
        stage, lcd, _, _ = make_stage(ib.EmulateTarget, script=[Idle(5), B],
                                      config={"ch3_target_uid": "01AA"},
                                      hw=FakeHID(["01BB", None, None, "01AA"]))
        self.assertEqual(stage.run(), 10)
        self.assertTrue(lcd.saw("Wrong, retry..."))

    def test_random_target_is_a_valid_ds1990(self):
        uid = random_ds1990_uid(random.Random(1))
        body = bytes.fromhex(uid[:14])
        self.assertEqual(uid[:2], "01")
        self.assertEqual(int(uid[14:], 16), dallas_crc8(body))
        self.assertEqual(dallas_crc8(bytes.fromhex("01CAFE11111111")), 0xD4)  # historic target
        self.assertEqual(ib.reader_order("01CAFE11111111D4"), "0111111111FECAD4")


class TestHints(unittest.TestCase):

    def test_hint_costs_points_once_and_restores_screen(self):
        # RIGHT -> "Hint 1/2? -2pt" SEL=buy -> BACK=close page -> "Hint 2/2?" BACK=no
        # -> the UID arrives -> success -> BACK leaves the result screen
        hid = FakeHID([None, "01-AA"])
        stage, lcd, db, events = make_stage(ib.TouchRead, script=[R, S, B, B, B], hw=hid)
        self.assertEqual(stage.run(), 8)
        self.assertEqual(db.get_challenge_status(1)["earned"], 8)
        self.assertEqual(db.get_challenge_status(1)["hints_used"], 1)
        self.assertTrue(lcd.saw("Hint 1/2"))
        self.assertTrue(events.of("hint_used"))

    def test_penalty_is_capped_at_half(self):
        stage, _, db, _ = make_stage(ib.TouchRead, hw=FakeHID())
        for _ in range(9):
            db.use_hint(1)
        self.assertEqual(stage.penalty(), 5)

    def test_hint_viewer_pages_long_text(self):
        stage, lcd, _, _ = make_stage(ib.TouchRead, script=[S, S, B], hw=FakeHID())
        stage._page("Hint 1/2", "word " * 12)
        self.assertGreaterEqual(len(lcd.screens), 2)
        self.assertTrue(all(len(a) <= 16 and len(b) <= 16 for a, b in lcd.screens))


class TestNfc(unittest.TestCase):

    def test_detect(self):
        pm3 = FakePM3(cards=[None, {"uid": "04A3F5B2", "type": "MIFARE Classic"}])
        stage, lcd, db, _ = make_stage(nfc.Detect, script=[Idle(5), B], hw=pm3)
        self.assertEqual(stage.run(), 10)
        self.assertTrue(lcd.saw("UID:04A3F5B2"))

    def test_clone_needs_same_uid(self):
        pm3 = FakePM3(cards=[{"uid": "04 A3", "type": "MIFARE Classic"}, {"uid": "04A3"}], dump={0: "00"})
        stage, lcd, _, _ = make_stage(nfc.Clone, script=[B], hw=pm3)
        self.assertEqual(stage.run(), 10)
        self.assertTrue(lcd.saw("1 blocks OK"))

    def test_attack_requires_classic(self):
        pm3 = FakePM3(cards=[{"uid": "04", "type": "NTAG"}], dump=None)
        stage, lcd, _, _ = make_stage(nfc.MifareAttack, script=[Idle(70), B], hw=pm3)
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("Not MIFARE!"))

    def test_pm3_missing(self):
        stage, lcd, _, _ = make_stage(nfc.Detect, script=[B], hw=FakePM3(simulation_mode=True))
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("NFC - No PM3!"))


class TestRfid(unittest.TestCase):

    def test_clone_t5577(self):
        pm3 = FakePM3(tags=[{"id": "1122334455", "type": "HID Prox"}, {"id": "1122334455"}])
        stage, _, _, _ = make_stage(rfid.CloneT5577, script=[S, B], hw=pm3)
        self.assertEqual(stage.run(), 10)
        self.assertEqual(pm3.cloned, [("1122334455", "HID")])

    def test_simulate_needs_em410x_and_confirmation(self):
        pm3 = FakePM3(tags=[{"id": "AA", "type": "EM410x"}])
        stage, _, _, _ = make_stage(rfid.SimulateEM, script=[S, B], hw=pm3)
        self.assertEqual(stage.run(), 10)
        self.assertEqual(pm3.simulated, ["AA"])


class TestSubGhz(unittest.TestCase):

    def test_detect_threshold(self):
        hackrf = FakeHackRF(captures=[-80, -40])
        stage, lcd, _, _ = make_stage(sub.Detect, script=[Idle(5), B], hw=hackrf)
        self.assertEqual(stage.run(), 10)
        self.assertTrue(lcd.saw("Signal:-40dBm"))
        self.assertTrue(all(not Path(p).exists() for p in hackrf.files))  # captures cleaned up

    def test_replay(self):
        hackrf = FakeHackRF(captures=[-30])
        stage, _, _, _ = make_stage(sub.Replay, script=[B], hw=hackrf)
        self.assertEqual(stage.run(), 10)
        self.assertEqual(hackrf.replayed[0][1], None)

    def test_analyze(self):
        stage, lcd, _, _ = make_stage(sub.Analyze, script=[B], hw=FakeHackRF(captures=[-30]))
        self.assertEqual(stage.run(), 10)
        self.assertTrue(lcd.saw("Proto:Princeton"))

    def test_disconnected_hackrf(self):
        hackrf = FakeHackRF(simulation_mode=False)
        hackrf.device_connected = False
        stage, lcd, _, _ = make_stage(sub.Detect, script=[B], hw=hackrf)
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("SubGHz-No HackRF"))


class TestIr(unittest.TestCase):
    KEY = {"keycode": "KEY_POWER", "scancode": "0x1", "protocol": "NEC"}

    def test_detect(self):
        stage, lcd, _, _ = make_stage(ir.Detect, script=[B], hw=FakeFlirc([self.KEY]))
        self.assertEqual(stage.run(), 10)
        self.assertTrue(lcd.saw("Key:KEY_POWER"))

    def test_replay_match_and_mismatch(self):
        stage, _, _, _ = make_stage(ir.Replay, script=[B], hw=FakeFlirc([self.KEY, self.KEY]))
        self.assertEqual(stage.run(), 10)
        other = {"keycode": "KEY_1", "scancode": "0x2"}
        stage, lcd, _, _ = make_stage(ir.Replay, script=[B], hw=FakeFlirc([self.KEY, other]))
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("MISMATCH!"))

    def test_protocols(self):
        events = [self.KEY, dict(self.KEY, protocol="RC5"), self.KEY]
        stage, lcd, _, _ = make_stage(ir.Protocols, script=[B], hw=FakeFlirc(events))
        self.assertEqual(stage.run(), 10)
        self.assertTrue(lcd.saw("2 protocol(s)"))


class TestSessionSecrets(unittest.TestCase):

    def test_new_session_randomizes_and_generates_files(self):
        registry = discover()
        with tempfile.TemporaryDirectory() as tmp:
            session = new_session(registry.scenarios, rng=random.Random(42),
                                  path=Path(tmp) / "session.json", directory=Path(tmp) / "files",
                                  config={})
            coffee = registry.get("coffee").resolve_config({}, session=session)
            garage = registry.get("garage").resolve_config(None, session=session)  # + config.json
            ibutton = IBUTTON.resolve_config({}, session=session)

            from app.core.nfc_file import parse_nfc
            from app.core.paths import resolve
            low = parse_nfc(resolve(coffee["badge_paths"]["low"]))
            self.assertEqual(low[35][10:].hex().upper(), coffee["master_key_b_hex"])
            self.assertNotEqual(coffee["master_key_b_hex"], "B4EEC0FFEE11")
            self.assertEqual(low[40], parse_nfc("challenges/coffee/badges/credit_low.nfc")[40])

            tech = parse_nfc(resolve(garage["badge_path"]))
            self.assertEqual(tech[3][:6].hex().upper(), garage["tech_room_key_a_hex"])
            self.assertTrue(resolve(garage["signal_paths"]["press_N"]).is_file())
            self.assertNotEqual(garage["rolling"]["seed_hex"], "C0 FF EE 11")
            self.assertEqual(garage["rolling"]["initial_counter"], 100)  # untouched keys kept

            self.assertNotEqual(ibutton["ch3_target_uid"], "01CAFE11111111D4")

    def test_secrets_are_used_by_stages(self):
        session = {"overrides": {"ibutton": {"ch3_target_uid": "01AB"}}}
        cfg = IBUTTON.resolve_config({}, session=session)
        stage, _, _, _ = make_stage(ib.EmulateTarget, script=[B], config=cfg, hw=FakeHID(["01AB"]))
        self.assertEqual(stage.run(), 10)


if __name__ == "__main__":
    unittest.main()
