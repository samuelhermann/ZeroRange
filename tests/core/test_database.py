import unittest

from database import Database


class TestDatabase(unittest.TestCase):

    def setUp(self):
        self.db = Database(":memory:", catalog=[(1, "a", "One", "d1", 10), (2, "b", "Two", "d2", 5)])

    def tearDown(self):
        self.db.close()

    def test_scores(self):
        self.assertEqual(self.db.get_max_score(), 15)
        self.assertEqual(self.db.get_max_score("b"), 5)
        self.db.mark_completed(1, 30)
        self.assertEqual(self.db.get_total_score(), 10)
        self.assertEqual(self.db.get_module_score("a"), 10)

    def test_best_time_kept(self):
        self.db.mark_completed(1, 30)
        self.db.mark_completed(1, 50)
        self.assertEqual(self.db.get_challenge_status(1)["best_time"], 30)
        self.db.mark_completed(1, 10)
        self.assertEqual(self.db.get_challenge_status(1)["best_time"], 10)

    def test_sync_preserves_progress_and_updates_metadata(self):
        self.db.mark_completed(1, 30)
        stats = self.db.sync_catalog([(1, "a", "Renamed", "d1", 20), (2, "b", "Two", "d2", 5),
                                      (3, "c", "Three", "", 10)])
        self.assertEqual(stats, {"added": 1, "updated": 1, "reassigned": 0})
        status = self.db.get_challenge_status(1)
        self.assertTrue(status["completed"])
        self.assertEqual(status["points"], 20)

    def test_sync_resets_progress_when_id_changes_module(self):
        self.db.mark_completed(2, 30)
        stats = self.db.sync_catalog([(2, "other", "X", "", 5)])
        self.assertEqual(stats["reassigned"], 1)
        self.assertFalse(self.db.get_challenge_status(2)["completed"])

    def test_stats_and_reset(self):
        self.db.add_history(1, True, 3)
        self.db.add_history(1, False, 4)
        self.db.mark_completed(1, 3)
        stats = self.db.get_stats()
        self.assertEqual((stats["total_score"], stats["max_score"], stats["completed_count"],
                          stats["total_challenges"], stats["total_attempts"]), (10, 15, 1, 2, 2))
        self.assertEqual(stats["success_rate"], 50)
        self.db.reset_scores()
        self.assertEqual(self.db.get_stats()["total_attempts"], 0)
        self.assertEqual(self.db.get_total_score(), 0)

    def test_get_all_challenges(self):
        rows = self.db.get_all_challenges()
        self.assertEqual([r["id"] for r in rows], [1, 2])
        self.assertIs(rows[0]["completed"], False)
