"""
Database Manager for ZeroRange
Handles SQLite persistence for challenges and score history.

The list of challenges is no longer hard-coded here: callers pass a catalog
(see ``app.catalog.build_catalog``) and :meth:`Database.sync_catalog`
inserts new challenges / refreshes names and points while preserving progress.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

CatalogRow = Tuple[int, str, str, str, int]  # id, module, name, description, points


class Database:
    """Manages the SQLite database for challenges and history."""

    def __init__(self, db_path: str = "scores.db",
                 catalog: Optional[Iterable[CatalogRow]] = None):
        self.db_path = str(db_path)
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            logger.info(f"Connected to database: {self.db_path}")
            self._create_tables()
            if catalog is not None:
                self.sync_catalog(catalog)
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _create_tables(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS challenges (
                    id INTEGER PRIMARY KEY,
                    module TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    points INTEGER NOT NULL,
                    completed BOOLEAN DEFAULT 0,
                    best_time INTEGER DEFAULT NULL
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    challenge_id INTEGER NOT NULL,
                    success BOOLEAN NOT NULL,
                    time_taken INTEGER NOT NULL,
                    FOREIGN KEY (challenge_id) REFERENCES challenges(id)
                )
            """)
        logger.debug("Database tables created/verified")

    # ------------------------------------------------------------------ catalog

    def sync_catalog(self, catalog: Iterable[CatalogRow]) -> Dict[str, int]:
        """Insert missing challenges and refresh metadata of existing ones.

        Progress (completed / best_time) is kept, except when an id now belongs
        to a *different* module: that is a renumbering mistake and the old
        progress would be credited to the wrong challenge, so it is reset.

        Returns counters ``{"added": n, "updated": n, "reassigned": n}``.
        """
        stats = {"added": 0, "updated": 0, "reassigned": 0}
        existing = {row["id"]: row for row in self.conn.execute(
            "SELECT id, module, name, description, points FROM challenges")}

        with self.conn:
            for cid, module, name, description, points in catalog:
                row = existing.get(cid)
                if row is None:
                    self.conn.execute(
                        "INSERT INTO challenges (id, module, name, description, points, completed, best_time) "
                        "VALUES (?, ?, ?, ?, ?, 0, NULL)",
                        (cid, module, name, description, points))
                    stats["added"] += 1
                elif row["module"] != module:
                    logger.warning(f"Challenge id {cid} moved from module '{row['module']}' "
                                   f"to '{module}' - its progress is reset")
                    self.conn.execute(
                        "UPDATE challenges SET module=?, name=?, description=?, points=?, "
                        "completed=0, best_time=NULL WHERE id=?",
                        (module, name, description, points, cid))
                    stats["reassigned"] += 1
                elif (row["name"], row["description"], row["points"]) != (name, description, points):
                    self.conn.execute(
                        "UPDATE challenges SET name=?, description=?, points=? WHERE id=?",
                        (name, description, points, cid))
                    stats["updated"] += 1

        if any(stats.values()):
            logger.info(f"Catalog synced: {stats}")
        return stats

    # ------------------------------------------------------------------ scores

    def get_total_score(self) -> int:
        """Sum of points of completed challenges."""
        try:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(points), 0) FROM challenges WHERE completed = 1").fetchone()
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get total score: {e}")
            return 0

    def get_max_score(self, module: Optional[str] = None) -> int:
        """Total points available (optionally for one module)."""
        try:
            if module:
                row = self.conn.execute(
                    "SELECT COALESCE(SUM(points), 0) FROM challenges WHERE module = ?",
                    (module,)).fetchone()
            else:
                row = self.conn.execute("SELECT COALESCE(SUM(points), 0) FROM challenges").fetchone()
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get max score: {e}")
            return 0

    def get_module_score(self, module: str) -> int:
        try:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(points), 0) FROM challenges WHERE completed = 1 AND module = ?",
                (module,)).fetchone()
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get module score: {e}")
            return 0

    def get_challenge_status(self, challenge_id: int) -> Optional[Dict]:
        """``{completed, points, best_time}`` or None if the id is unknown."""
        try:
            row = self.conn.execute(
                "SELECT completed, points, best_time FROM challenges WHERE id = ?",
                (challenge_id,)).fetchone()
            if row:
                return {
                    'completed': bool(row['completed']),
                    'points': row['points'],
                    'best_time': row['best_time'],
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get challenge status: {e}")
            return None

    def get_all_challenges(self) -> List[Dict]:
        try:
            rows = self.conn.execute("""
                SELECT id, module, name, description, points, completed, best_time
                FROM challenges ORDER BY id
            """).fetchall()
            return [dict(row, completed=bool(row['completed'])) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get challenges: {e}")
            return []

    def mark_completed(self, challenge_id: int, time_taken: int):
        """Mark challenge as completed and keep the best time."""
        try:
            row = self.conn.execute(
                "SELECT best_time FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
            if row is None:
                logger.warning(f"Challenge {challenge_id} not found")
                return
            with self.conn:
                self.conn.execute("""
                    UPDATE challenges
                    SET completed = 1,
                        best_time = CASE WHEN best_time IS NULL OR ? < best_time
                                         THEN ? ELSE best_time END
                    WHERE id = ?
                """, (time_taken, time_taken, challenge_id))
            logger.info(f"Challenge {challenge_id} completed in {time_taken}s")
        except Exception as e:
            logger.error(f"Failed to mark challenge completed: {e}")

    def add_history(self, challenge_id: int, success: bool, time_taken: int):
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO history (timestamp, challenge_id, success, time_taken) VALUES (?, ?, ?, ?)",
                    (datetime.now().isoformat(), challenge_id, bool(success), int(time_taken)))
            logger.info(f"Added history: Challenge {challenge_id}, success={success}, time={time_taken}s")
        except Exception as e:
            logger.error(f"Failed to add history: {e}")

    def get_stats(self) -> Dict:
        """``{total_score, max_score, completed_count, total_challenges,
        total_attempts, success_rate}``."""
        try:
            q = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
            total_attempts = q("SELECT COUNT(*) FROM history")
            success_count = q("SELECT COUNT(*) FROM history WHERE success = 1")
            return {
                'total_score': self.get_total_score(),
                'max_score': self.get_max_score(),
                'completed_count': q("SELECT COUNT(*) FROM challenges WHERE completed = 1"),
                'total_challenges': q("SELECT COUNT(*) FROM challenges"),
                'total_attempts': total_attempts,
                'success_rate': (success_count / total_attempts * 100) if total_attempts else 0,
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {'total_score': 0, 'max_score': 0, 'completed_count': 0,
                    'total_challenges': 0, 'total_attempts': 0, 'success_rate': 0}

    def reset_scores(self):
        """Reset all scores and clear history."""
        try:
            with self.conn:
                self.conn.execute("UPDATE challenges SET completed = 0, best_time = NULL")
                self.conn.execute("DELETE FROM history")
            logger.info("All scores reset and history cleared")
        except Exception as e:
            logger.error(f"Failed to reset scores: {e}")

    def close(self):
        try:
            self.conn.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Failed to close database: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s')
    from app.catalog import build_catalog
    from app.scenarios.registry import discover

    db = Database(":memory:", catalog=build_catalog(discover().scenarios))
    for ch in db.get_all_challenges():
        print(f"  {ch['id']:>3} {ch['module']:<8} {ch['name']:<20} {ch['points']}pts")
    db.add_history(1, True, 45)
    db.mark_completed(1, 45)
    print(db.get_stats())
    db.close()
