"""Garage scenario: stages and runner behaviour, all hardware faked."""

import os
import unittest

from app.core.ui import Button
from challenges.garage.scenario import SCENARIO
from challenges.garage.stage1_rolling import Stage1
from challenges.garage.stage2_pedestrian import Stage2
from challenges.garage.stage3_tech_room import Stage3
from tests.fakes import FakeHackRF, FakeHID, FakePM3, make_runner, make_stage

B, S = Button.BACK, Button.SELECT

CFG = {
    "rolling": {
        "device_id_hex": "DEADBEEF",
        "seed_hex": "C0FFEE11",
        "freq_hz": 433920000,
        "press_gap_ms": 100,
        "counter_window": 16,
        "initial_counter": 100,
    },
    "pedestrian_uid": "0100C0FFEE7E11AB",
    "tech_room_key_a_hex": "F15EC0DE0017",
    "badge_path": "challenges/garage/badges/tech_room.nfc",
    "max_wrong_reads_stage2": 3,
}


def completed(db, cid):
    return db.get_challenge_status(cid)["completed"]


class TestStage1Rolling(unittest.TestCase):

    def make(self, script, hackrf=None, **kw):
        return make_stage(Stage1, script=script, config=CFG,
                          hw=hackrf if hackrf is not None else FakeHackRF(),
                          scenarios=[SCENARIO], **kw)

    def test_full_rolljam_awards_10(self):
        # SEL = "Got REJECTED? yes", SEL = "Ready for 1b? go", BACK = leave summary
        stage, lcd, db, events = self.make([S, S, B])
        self.assertEqual(stage.run(), 10)
        self.assertTrue(completed(db, 19))
        self.assertTrue(lcd.saw("Replay rejected"))
        self.assertTrue(lcd.saw("Gate OPEN!"))
        replays = events.of("replay_received")
        self.assertEqual([e["accepted"] for e in replays], [True, False, True])
        self.assertIn({"stage": 1, "status": "success", "points": 10}, events)

    def test_skipping_1b_persists_nothing(self):
        stage, lcd, db, events = self.make([S, B])
        self.assertEqual(stage.run(), 0)
        self.assertFalse(completed(db, 19))
        self.assertTrue(events.of("substage_complete"))
        # The web page must not mark stage 1 as solved after 1a only.
        self.assertFalse(events.of("stage_complete"))

    def test_back_at_1a_confirmation(self):
        stage, _, db, _ = self.make([B])
        self.assertEqual(stage.run(), 0)
        self.assertFalse(completed(db, 19))

    def test_no_hackrf_returns_zero(self):
        stage, lcd, _, _ = make_stage(Stage1, script=[B], config=CFG, hw=None, scenarios=[SCENARIO])
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("HackRF not found"))

    def test_already_complete_returns_zero(self):
        stage, _, db, events = self.make([])
        db.mark_completed(19, 5)
        self.assertEqual(stage.run(), 0)
        self.assertEqual(events, [])

    def test_real_hackrf_tx_uses_temp_files_and_cleans_up(self):
        hackrf = FakeHackRF(simulation_mode=False)
        stage, _, _, _ = self.make([S, S, B], hackrf=hackrf)
        self.assertEqual(stage.run(), 10)
        self.assertEqual(len(hackrf.replayed), 5)  # N, replay N, N+1, N+2, replay N+1
        self.assertTrue(all(freq == 433920000 for _, freq in hackrf.replayed))
        self.assertFalse(any(os.path.exists(p) for p, _ in hackrf.replayed))


class TestStage2Pedestrian(unittest.TestCase):

    def run_stage(self, uids, script, config=CFG, hid=None):
        stage, lcd, db, events = make_stage(Stage2, script=script, config=config,
                                            hw=hid or FakeHID(uids), scenarios=[SCENARIO])
        return stage.run(), lcd, db, events

    def test_correct_uid_awards_10_and_leaks_key(self):
        pts, lcd, db, events = self.run_stage(["0100C0FFEE7E11AB"], [B])
        self.assertEqual(pts, 10)
        self.assertTrue(completed(db, 20))
        self.assertIn({"stage": 2, "status": "success", "points": 10}, events)
        self.assertEqual(events.of("key_leaked")[0]["key_a_hex"], "F15EC0DE0017")
        self.assertTrue(lcd.saw("F15E C0DE 0017"))

    def test_wrong_uid_does_not_award(self):
        pts, _, db, _ = self.run_stage(["WRONG00000000000"], [B])
        self.assertEqual(pts, 0)
        self.assertFalse(completed(db, 20))

    def test_three_wrong_shows_hint(self):
        pts, lcd, _, _ = self.run_stage(["AAAA", "BBBB", "CCCC"], [B])
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Try another fob"))

    def test_no_hid_returns_zero(self):
        pts, lcd, _, _ = self.run_stage([], [B], hid=FakeHID(available=False))
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("iBtn reader N/A"))

    def test_placeholder_uid_is_reported(self):
        cfg = dict(CFG, pedestrian_uid="REPLACE_WITH_DS1990_UID")
        pts, lcd, _, _ = self.run_stage(["0100C0FFEE7E11AB"], [B], config=cfg)
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Stage not set up"))

    def test_already_complete_replays_leak(self):
        stage, lcd, db, _ = make_stage(Stage2, config=CFG, hw=FakeHID(), scenarios=[SCENARIO])
        db.mark_completed(20, 9)
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("Post-it on door:"))


class TestStage3TechRoom(unittest.TestCase):

    def run_stage(self, pm3, script):
        stage, lcd, db, events = make_stage(Stage3, script=script, config=CFG, hw=pm3,
                                            scenarios=[SCENARIO])
        return stage.run(), lcd, db, events

    def test_manual_confirm_awards_10(self):
        pm3 = FakePM3()
        pts, _, db, events = self.run_stage(pm3, [S, B])
        self.assertEqual(pts, 10)
        self.assertTrue(completed(db, 21))
        self.assertEqual(pm3.reads, [(0, bytes.fromhex("F15EC0DE0017"), "A")])
        self.assertIn({"stage": 3, "status": "success", "points": 10}, events)

    def test_auto_detect_from_log(self):
        pm3 = FakePM3(log_lines=["[=] Authenticated block 2 with key A"])
        pts, _, _, _ = self.run_stage(pm3, [B])
        self.assertEqual(pts, 10)

    def test_failed_auth_and_other_sectors_are_ignored(self):
        # "block 10" used to match "block 1" (substring test) and failures counted as auth.
        pm3 = FakePM3(log_lines=["auth failed block 0", "Authenticated block 10 key A"])
        pts, _, db, _ = self.run_stage(pm3, [B])
        self.assertEqual(pts, 0)
        self.assertFalse(completed(db, 21))

    def test_emulation_stopped_on_exit(self):
        pm3 = FakePM3()
        self.run_stage(pm3, [B])
        self.assertTrue(pm3.emulation.stopped)

    def test_no_pm3_returns_zero(self):
        pts, lcd, _, _ = self.run_stage(FakePM3(simulation_mode=True), [B])
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Proxmark3 needed"))

    def test_already_complete_returns_zero(self):
        pm3 = FakePM3()
        stage, _, db, _ = make_stage(Stage3, config=CFG, hw=pm3, scenarios=[SCENARIO])
        db.mark_completed(21, 3)
        self.assertEqual(stage.run(), 0)
        self.assertEqual(pm3.emulated, [])


class TestGarageRunner(unittest.TestCase):

    def test_module_score(self):
        runner, _, db = make_runner(SCENARIO, config=CFG)
        self.assertEqual(runner.get_module_score(), 0)
        for cid in (19, 20, 21):
            db.mark_completed(cid, 1)
        self.assertEqual(runner.get_module_score(), 30)

    def test_close_cleans_up_hid(self):
        hid = FakeHID()
        runner, _, _ = make_runner(SCENARIO, config=CFG, hid=hid, script=[B])
        runner.run()
        self.assertTrue(hid.closed)
        self.assertIsNone(runner._hid)


if __name__ == "__main__":
    unittest.main()
