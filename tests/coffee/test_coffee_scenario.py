"""Coffee scenario: stages, prep tool and runner behaviour, all hardware faked."""

import unittest
from pathlib import Path

from app.core.ui import Button
from challenges.coffee.prep_badges import PrepBadges
from challenges.coffee.scenario import SCENARIO
from challenges.coffee.stage1_technician import Stage1
from challenges.coffee.stage2_dump import Stage2
from challenges.coffee.stage3_refill import Stage3
from challenges.coffee.value_block import encode
from tests.fakes import FakeHID, FakePM3, Idle, make_runner, make_stage

B, S, D = Button.BACK, Button.SELECT, Button.DOWN

CFG = {
    "technician_uid": "0100C0FFEE7E11AB",
    "master_key_b_hex": "B4EEC0FFEE11",
    "credit_threshold_cents": 5000,
    "value_block_addr": 40,
    "max_wrong_reads_stage1": 3,
    "badge_paths": {
        "low": "challenges/coffee/badges/credit_low.nfc",
        "high": "challenges/coffee/badges/credit_high.nfc",
    },
}


def completed(db, cid):
    return db.get_challenge_status(cid)["completed"]


class TestStage1Technician(unittest.TestCase):

    def run_stage(self, uids, script, **kw):
        stage, lcd, db, events = make_stage(Stage1, script=script, config=CFG,
                                            hw=FakeHID(uids), scenarios=[SCENARIO], **kw)
        return stage.run(), lcd, db, events

    def test_correct_uid_awards_10_pts_and_leaks_key(self):
        pts, lcd, db, events = self.run_stage(["01-00-C0-FF-EE-7E-11-AB"], [B])
        self.assertEqual(pts, 10)
        self.assertTrue(completed(db, 16))
        self.assertTrue(lcd.saw("B4EE C0FF EE11"))
        self.assertIn({"stage": 1, "status": "success", "points": 10}, events)
        self.assertEqual(events.of("key_leaked")[0]["key_b_hex"], "B4EEC0FFEE11")

    def test_wrong_uid_no_award(self):
        pts, lcd, db, _ = self.run_stage(["DEADBEEF00000000"], [B])
        self.assertEqual(pts, 0)
        self.assertFalse(completed(db, 16))
        self.assertTrue(lcd.saw("2 tries left"))

    def test_three_wrong_reads_show_hint_then_retry(self):
        pts, lcd, db, _ = self.run_stage(["AA", "BB", "CC"], [S, B])
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Check the token"))

    def test_back_during_read_exits_immediately(self):
        # Regression: BACK used to be mistaken for a timeout ("No token seen").
        pts, lcd, _, _ = self.run_stage([], [B])
        self.assertEqual(pts, 0)
        self.assertFalse(lcd.saw("No token seen"))

    def test_timeout_offers_retry(self):
        pts, lcd, _, _ = self.run_stage([], [Idle(61), B])
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("No token seen"))
        self.assertTrue(lcd.saw("◄=Back [1s]"))

    def test_already_complete_shows_leak_no_reaward(self):
        stage, lcd, db, _ = make_stage(Stage1, config=CFG, hw=FakeHID(), scenarios=[SCENARIO])
        db.mark_completed(16, 30)
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("Leaked log:"))
        self.assertEqual(db.get_challenge_status(16)["best_time"], 30)

    def test_reader_missing(self):
        stage, lcd, _, _ = make_stage(Stage1, script=[B], config=CFG,
                                      hw=FakeHID(available=False), scenarios=[SCENARIO])
        self.assertEqual(stage.run(), 0)
        self.assertTrue(lcd.saw("iBtn reader N/A"))


class TestStage2Dump(unittest.TestCase):

    def run_stage(self, pm3, script):
        stage, lcd, db, events = make_stage(Stage2, script=script, config=CFG, hw=pm3,
                                            scenarios=[SCENARIO])
        return stage.run(), lcd, db, events

    def test_auto_detect_from_sim_log(self):
        pm3 = FakePM3(log_lines=[f"Auth sector {s} key B B4 EE C0 FF EE 11" for s in range(8, 15)])
        pts, lcd, db, events = self.run_stage(pm3, [B])
        self.assertEqual(pts, 10)
        self.assertTrue(completed(db, 17))
        self.assertTrue(pm3.emulation.stopped)
        self.assertEqual(events.of("sector_unlocked")[-1]["sectors"], list(range(8, 15)))
        self.assertTrue(Path(pm3.emulated[0]).is_absolute())

    def test_log_with_wrong_key_is_ignored(self):
        pm3 = FakePM3(log_lines=[f"Auth sector {s} key B FFFFFFFFFFFF" for s in range(8, 15)])
        pts, _, db, _ = self.run_stage(pm3, [B])
        self.assertEqual(pts, 0)
        self.assertFalse(completed(db, 17))
        self.assertTrue(pm3.emulation.stopped)

    def test_manual_verify_reads_every_sector_with_key_b(self):
        pm3 = FakePM3()
        pts, _, _, _ = self.run_stage(pm3, [S, B])
        self.assertEqual(pts, 10)
        self.assertEqual([r[0] for r in pm3.reads], [32, 36, 40, 44, 48, 52, 56])
        self.assertEqual({(r[1].hex().upper(), r[2]) for r in pm3.reads}, {("B4EEC0FFEE11", "B")})

    def test_manual_verify_failure(self):
        pts, lcd, _, _ = self.run_stage(FakePM3(fail_auth=True), [S, B])
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Not all sectors"))

    def test_pm3_in_simulation_mode(self):
        pts, lcd, _, _ = self.run_stage(FakePM3(simulation_mode=True), [B])
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Proxmark3 needed"))


class TestStage3Refill(unittest.TestCase):

    def run_with_block(self, raw, script=(S, B), threshold=5000, **pm3_kw):
        pm3 = FakePM3({40: raw}, **pm3_kw)
        cfg = dict(CFG, credit_threshold_cents=threshold)
        stage, lcd, db, events = make_stage(Stage3, script=script, config=cfg, hw=pm3,
                                            scenarios=[SCENARIO])
        return stage.run(), lcd, db, events

    def test_valid_high_credit_awards_10(self):
        pts, lcd, db, events = self.run_with_block(encode(5000, 40))
        self.assertEqual(pts, 10)
        self.assertTrue(completed(db, 18))
        self.assertTrue(lcd.saw("50,00 EUR OK!"))
        self.assertEqual(events.of("credit_observed")[0]["value_cents"], 5000)

    def test_below_threshold_no_award(self):
        pts, lcd, db, _ = self.run_with_block(encode(4999, 40))
        self.assertEqual(pts, 0)
        self.assertFalse(completed(db, 18))
        self.assertTrue(lcd.saw("Value too low!"))

    def test_bad_inv_v_shows_error(self):
        bad = bytearray(encode(5000, 40))
        bad[5] ^= 0x01
        pts, lcd, _, _ = self.run_with_block(bytes(bad))
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Bad ~V"))

    def test_bad_addr_shows_error(self):
        bad = bytearray(encode(5000, 40))
        bad[12] ^= 0x01
        pts, lcd, _, _ = self.run_with_block(bytes(bad))
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Bad addr"))

    def test_auth_failure(self):
        pts, lcd, _, events = self.run_with_block(b"", fail_auth=True)
        self.assertEqual(pts, 0)
        self.assertTrue(lcd.saw("Auth failed!"))
        self.assertEqual(events.of("credit_observed")[0]["error"], "auth_failed")

    def test_already_complete_no_reaward(self):
        pm3 = FakePM3()
        stage, _, db, _ = make_stage(Stage3, config=CFG, hw=pm3, scenarios=[SCENARIO])
        db.mark_completed(18, 60)
        self.assertEqual(stage.run(), 0)
        self.assertEqual(pm3.reads, [])


class TestPrepBadges(unittest.TestCase):

    def test_emulate_low_badge_toggle_key_and_stop(self):
        pm3 = FakePM3()
        tool, lcd, _, _ = make_stage(PrepBadges, script=[S, S, B, B], config=CFG, hw=pm3)
        self.assertEqual(tool.run(), 0)
        self.assertTrue(str(pm3.emulated[0]).endswith("credit_low.nfc"))
        self.assertTrue(lcd.saw("B4EE C0FF EE11"))
        self.assertTrue(pm3.emulation.stopped)

    def test_high_badge(self):
        pm3 = FakePM3()
        tool, _, _, _ = make_stage(PrepBadges, script=[D, S, B, B], config=CFG, hw=pm3)
        tool.run()
        self.assertTrue(str(pm3.emulated[0]).endswith("credit_high.nfc"))


class TestCoffeeRunner(unittest.TestCase):

    def test_score_reflects_completed_challenges(self):
        runner, _, db = make_runner(SCENARIO, config=CFG)
        self.assertEqual(runner.get_module_score(), 0)
        db.mark_completed(16, 10)
        db.mark_completed(17, 20)
        self.assertEqual(runner.get_module_score(), 20)
        self.assertEqual(runner.max_points, 30)

    def test_menu_marks_completed_stage(self):
        runner, lcd, db = make_runner(SCENARIO, config=CFG, script=[B])
        db.mark_completed(16, 10)
        runner.run()
        self.assertEqual(lcd.screens[0], (">Stage1:iButton✓", "U/D SEL=Go 10/30"))

    def test_celebration_only_when_really_complete(self):
        # Regression: Stage 3 used to print "COMPLETE! 30/30" unconditionally.
        pm3 = FakePM3({40: encode(6000, 40)})
        runner, lcd, _ = make_runner(SCENARIO, config=CFG, pm3=pm3, script=[D, D, S, S, B, B])
        self.assertEqual(runner.run(), 10)
        self.assertFalse(lcd.saw("COFFEE MODULE"))

        runner, lcd, db = make_runner(SCENARIO, config=CFG, pm3=FakePM3({40: encode(6000, 40)}),
                                      script=[D, D, S, S, B, B])
        db.mark_completed(16, 1)
        db.mark_completed(17, 1)
        runner.run()
        self.assertTrue(lcd.saw("COFFEE MODULE"))
        self.assertTrue(runner.sse.of("scenario_complete"))

    def test_hid_opened_and_closed(self):
        hid = FakeHID()
        runner, _, _ = make_runner(SCENARIO, config=CFG, hid=hid, script=[B])
        runner.run()
        self.assertTrue(hid.closed)


if __name__ == "__main__":
    unittest.main()
