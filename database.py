"""
Database Manager for ZeroRange — SQLite persistence.

Schema v2
---------
* ``challenges``  catalog (id, module, name, description, points), synced at
  boot from the scenarios (see ``app.catalog.build_catalog``).
* ``players``     learners; one of them is *active* (``settings.active_player``).
* ``progress``    per player and challenge: completed, earned points (partial
  credit and hint penalties), best time, hints used.
* ``history``     every attempt, tagged with the player.
* ``settings``    small key/value store.

Every score method works on the active player unless ``player_id`` is given,
so the LCD code never has to care about players.  A v1 database (progress
stored in ``challenges.completed``) is migrated to player "Player 1".
"""

import csv
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Iterable, List, Optional, TextIO, Tuple

logger = logging.getLogger(__name__)

CatalogRow = Tuple[int, str, str, str, int]  # id, module, name, description, points

SCHEMA_VERSION = 2
DEFAULT_PLAYER = "Player 1"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    """Manages the SQLite database for challenges, players and history."""

    def __init__(self, db_path: str = "scores.db",
                 catalog: Optional[Iterable[CatalogRow]] = None):
        self.db_path = str(db_path)
        try:
            self.conn = sqlite3.connect(self.db_path, timeout=5)
            self.conn.row_factory = sqlite3.Row
            if self.db_path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")  # LCD + web processes
            logger.info(f"Connected to database: {self.db_path}")
            self._create_tables()
            self._migrate()
            if catalog is not None:
                self.sync_catalog(catalog)
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    # ------------------------------------------------------------------ schema

    def _create_tables(self):
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS challenges (
                    id INTEGER PRIMARY KEY,
                    module TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    points INTEGER NOT NULL,
                    completed BOOLEAN DEFAULT 0,      -- v1 only, kept for downgrade
                    best_time INTEGER DEFAULT NULL    -- v1 only
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    challenge_id INTEGER NOT NULL,
                    success BOOLEAN NOT NULL,
                    time_taken INTEGER NOT NULL,
                    FOREIGN KEY (challenge_id) REFERENCES challenges(id)
                );
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS progress (
                    player_id INTEGER NOT NULL,
                    challenge_id INTEGER NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    earned INTEGER NOT NULL DEFAULT 0,
                    best_time INTEGER DEFAULT NULL,
                    hints_used INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT DEFAULT NULL,
                    PRIMARY KEY (player_id, challenge_id)
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

    def _migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        with self.conn:
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(history)")}
            if "player_id" not in cols:
                self.conn.execute("ALTER TABLE history ADD COLUMN player_id INTEGER NOT NULL DEFAULT 1")
            if not self.conn.execute("SELECT 1 FROM players LIMIT 1").fetchone():
                self.conn.execute("INSERT INTO players (id, name, created_at) VALUES (1, ?, ?)",
                                  (DEFAULT_PLAYER, _now()))
                # v1 progress lived in challenges.completed / best_time
                self.conn.execute("""
                    INSERT OR IGNORE INTO progress (player_id, challenge_id, completed, earned, best_time)
                    SELECT 1, id, 1, points, best_time FROM challenges WHERE completed = 1
                """)
            self.conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('active_player', '1')")
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        logger.info(f"Database schema migrated to v{SCHEMA_VERSION}")

    # ------------------------------------------------------------------ settings

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    # ------------------------------------------------------------------ players

    @property
    def active_player_id(self) -> int:
        try:
            pid = int(self.get_setting("active_player", "0"))
        except ValueError:
            pid = 0
        if pid and self.conn.execute("SELECT 1 FROM players WHERE id = ?", (pid,)).fetchone():
            return pid
        row = self.conn.execute("SELECT id FROM players ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return self.add_player(DEFAULT_PLAYER)
        return row["id"]

    def _pid(self, player_id: Optional[int]) -> int:
        return self.active_player_id if player_id is None else int(player_id)

    def get_active_player(self) -> Dict:
        pid = self.active_player_id
        row = self.conn.execute("SELECT id, name, created_at FROM players WHERE id = ?", (pid,)).fetchone()
        return dict(row)

    def set_active_player(self, player_id: int) -> None:
        if not self.conn.execute("SELECT 1 FROM players WHERE id = ?", (player_id,)).fetchone():
            raise ValueError(f"Unknown player {player_id}")
        self.set_setting("active_player", str(player_id))
        logger.info(f"Active player is now #{player_id}")

    def add_player(self, name: Optional[str] = None) -> int:
        """Create a player (default name "Player N") and return its id."""
        name = (name or "").strip()[:32]
        if not name:
            n = self.conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] + 1
            while self.conn.execute("SELECT 1 FROM players WHERE name = ?", (f"Player {n}",)).fetchone():
                n += 1
            name = f"Player {n}"
        with self.conn:
            cur = self.conn.execute("INSERT INTO players (name, created_at) VALUES (?, ?)", (name, _now()))
        return int(cur.lastrowid)

    def rename_player(self, player_id: int, name: str) -> None:
        name = name.strip()[:32]
        if not name:
            raise ValueError("Empty name")
        with self.conn:
            self.conn.execute("UPDATE players SET name = ? WHERE id = ?", (name, player_id))

    def delete_player(self, player_id: int) -> None:
        if self.conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] <= 1:
            raise ValueError("Cannot delete the last player")
        was_active = player_id == self.active_player_id
        with self.conn:
            self.conn.execute("DELETE FROM progress WHERE player_id = ?", (player_id,))
            self.conn.execute("DELETE FROM history WHERE player_id = ?", (player_id,))
            self.conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
        if was_active:
            self.set_active_player(self.conn.execute(
                "SELECT id FROM players ORDER BY id LIMIT 1").fetchone()["id"])

    def list_players(self) -> List[Dict]:
        rows = self.conn.execute("""
            SELECT p.id, p.name, p.created_at,
                   COALESCE(SUM(g.earned), 0) AS score,
                   COALESCE(SUM(g.completed), 0) AS completed
            FROM players p LEFT JOIN progress g ON g.player_id = p.id
            GROUP BY p.id ORDER BY p.id
        """).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ catalog

    def sync_catalog(self, catalog: Iterable[CatalogRow]) -> Dict[str, int]:
        """Insert missing challenges and refresh metadata of existing ones.

        Progress is kept, except when an id now belongs to a *different*
        module: the old progress would be credited to the wrong challenge, so
        it is dropped. Returns ``{"added": n, "updated": n, "reassigned": n}``.
        """
        stats = {"added": 0, "updated": 0, "reassigned": 0}
        existing = {row["id"]: row for row in self.conn.execute(
            "SELECT id, module, name, description, points FROM challenges")}

        with self.conn:
            for cid, module, name, description, points in catalog:
                row = existing.get(cid)
                if row is None:
                    self.conn.execute(
                        "INSERT INTO challenges (id, module, name, description, points) VALUES (?, ?, ?, ?, ?)",
                        (cid, module, name, description, points))
                    stats["added"] += 1
                elif row["module"] != module:
                    logger.warning(f"Challenge id {cid} moved from module '{row['module']}' "
                                   f"to '{module}' - its progress is reset")
                    self.conn.execute(
                        "UPDATE challenges SET module=?, name=?, description=?, points=?, "
                        "completed=0, best_time=NULL WHERE id=?",
                        (module, name, description, points, cid))
                    self.conn.execute("DELETE FROM progress WHERE challenge_id = ?", (cid,))
                    stats["reassigned"] += 1
                elif (row["name"], row["description"], row["points"]) != (name, description, points):
                    self.conn.execute(
                        "UPDATE challenges SET name=?, description=?, points=? WHERE id=?",
                        (name, description, points, cid))
                    self.conn.execute("UPDATE progress SET earned = MIN(earned, ?) WHERE challenge_id = ?",
                                      (points, cid))
                    stats["updated"] += 1

        if any(stats.values()):
            logger.info(f"Catalog synced: {stats}")
        return stats

    def _points(self, challenge_id: int) -> Optional[int]:
        row = self.conn.execute("SELECT points FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
        return row["points"] if row else None

    # ------------------------------------------------------------------ scores

    def get_total_score(self, player_id: Optional[int] = None) -> int:
        try:
            row = self.conn.execute("SELECT COALESCE(SUM(earned), 0) FROM progress WHERE player_id = ?",
                                    (self._pid(player_id),)).fetchone()
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get total score: {e}")
            return 0

    def get_max_score(self, module: Optional[str] = None) -> int:
        try:
            if module:
                row = self.conn.execute(
                    "SELECT COALESCE(SUM(points), 0) FROM challenges WHERE module = ?", (module,)).fetchone()
            else:
                row = self.conn.execute("SELECT COALESCE(SUM(points), 0) FROM challenges").fetchone()
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get max score: {e}")
            return 0

    def get_module_score(self, module: str, player_id: Optional[int] = None) -> int:
        try:
            row = self.conn.execute("""
                SELECT COALESCE(SUM(g.earned), 0) FROM progress g
                JOIN challenges c ON c.id = g.challenge_id
                WHERE g.player_id = ? AND c.module = ?
            """, (self._pid(player_id), module)).fetchone()
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get module score: {e}")
            return 0

    def get_challenge_status(self, challenge_id: int, player_id: Optional[int] = None) -> Optional[Dict]:
        """``{completed, points, earned, best_time, hints_used}`` or None if unknown id."""
        try:
            row = self.conn.execute("""
                SELECT c.points, COALESCE(g.completed, 0) AS completed, COALESCE(g.earned, 0) AS earned,
                       g.best_time, COALESCE(g.hints_used, 0) AS hints_used
                FROM challenges c
                LEFT JOIN progress g ON g.challenge_id = c.id AND g.player_id = ?
                WHERE c.id = ?
            """, (self._pid(player_id), challenge_id)).fetchone()
            if row is None:
                return None
            return {'completed': bool(row['completed']), 'points': row['points'],
                    'earned': row['earned'], 'best_time': row['best_time'],
                    'hints_used': row['hints_used']}
        except Exception as e:
            logger.error(f"Failed to get challenge status: {e}")
            return None

    def get_all_challenges(self, player_id: Optional[int] = None) -> List[Dict]:
        try:
            rows = self.conn.execute("""
                SELECT c.id, c.module, c.name, c.description, c.points,
                       COALESCE(g.completed, 0) AS completed, COALESCE(g.earned, 0) AS earned,
                       g.best_time, COALESCE(g.hints_used, 0) AS hints_used
                FROM challenges c
                LEFT JOIN progress g ON g.challenge_id = c.id AND g.player_id = ?
                ORDER BY c.id
            """, (self._pid(player_id),)).fetchall()
            return [dict(row, completed=bool(row['completed'])) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get challenges: {e}")
            return []

    def _ensure_progress(self, pid: int, challenge_id: int) -> None:
        self.conn.execute("INSERT OR IGNORE INTO progress (player_id, challenge_id) VALUES (?, ?)",
                          (pid, challenge_id))

    def mark_completed(self, challenge_id: int, time_taken: int, points: Optional[int] = None,
                       player_id: Optional[int] = None):
        """Mark a challenge solved. ``points`` (default: full points) is what
        the player earned after hint penalties; the best result is kept."""
        try:
            full = self._points(challenge_id)
            if full is None:
                logger.warning(f"Challenge {challenge_id} not found")
                return
            earned = full if points is None else max(0, min(int(points), full))
            pid = self._pid(player_id)
            with self.conn:
                self._ensure_progress(pid, challenge_id)
                self.conn.execute("""
                    UPDATE progress
                    SET completed = 1,
                        earned = MAX(earned, ?),
                        best_time = CASE WHEN best_time IS NULL OR ? < best_time THEN ? ELSE best_time END,
                        completed_at = COALESCE(completed_at, ?)
                    WHERE player_id = ? AND challenge_id = ?
                """, (earned, time_taken, time_taken, _now(), pid, challenge_id))
            logger.info(f"Challenge {challenge_id} completed in {time_taken}s ({earned}/{full} pts)")
        except Exception as e:
            logger.error(f"Failed to mark challenge completed: {e}")

    def record_partial(self, challenge_id: int, points: int, player_id: Optional[int] = None) -> None:
        """Credit part of a challenge (multi-part stages) without completing it."""
        full = self._points(challenge_id)
        if full is None:
            logger.warning(f"Challenge {challenge_id} not found")
            return
        pid = self._pid(player_id)
        with self.conn:
            self._ensure_progress(pid, challenge_id)
            self.conn.execute("UPDATE progress SET earned = MAX(earned, ?) WHERE player_id = ? AND challenge_id = ?",
                              (max(0, min(int(points), full)), pid, challenge_id))

    def use_hint(self, challenge_id: int, player_id: Optional[int] = None) -> int:
        """Count one more hint for this challenge; returns the new total."""
        pid = self._pid(player_id)
        with self.conn:
            self._ensure_progress(pid, challenge_id)
            self.conn.execute("UPDATE progress SET hints_used = hints_used + 1 "
                              "WHERE player_id = ? AND challenge_id = ?", (pid, challenge_id))
        return self.conn.execute("SELECT hints_used FROM progress WHERE player_id = ? AND challenge_id = ?",
                                 (pid, challenge_id)).fetchone()[0]

    def add_history(self, challenge_id: int, success: bool, time_taken: int,
                    player_id: Optional[int] = None):
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO history (timestamp, challenge_id, success, time_taken, player_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (_now(), challenge_id, bool(success), int(time_taken), self._pid(player_id)))
            logger.info(f"Added history: Challenge {challenge_id}, success={success}, time={time_taken}s")
        except Exception as e:
            logger.error(f"Failed to add history: {e}")

    def get_stats(self, player_id: Optional[int] = None) -> Dict:
        """``{total_score, max_score, completed_count, total_challenges,
        total_attempts, success_rate}`` for one player."""
        try:
            pid = self._pid(player_id)
            q = lambda sql, *a: self.conn.execute(sql, a).fetchone()[0]  # noqa: E731
            total_attempts = q("SELECT COUNT(*) FROM history WHERE player_id = ?", pid)
            success_count = q("SELECT COUNT(*) FROM history WHERE player_id = ? AND success = 1", pid)
            return {
                'total_score': self.get_total_score(pid),
                'max_score': self.get_max_score(),
                'completed_count': q("SELECT COUNT(*) FROM progress WHERE player_id = ? AND completed = 1", pid),
                'total_challenges': q("SELECT COUNT(*) FROM challenges"),
                'total_attempts': total_attempts,
                'success_rate': (success_count / total_attempts * 100) if total_attempts else 0,
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {'total_score': 0, 'max_score': 0, 'completed_count': 0,
                    'total_challenges': 0, 'total_attempts': 0, 'success_rate': 0}

    def reset_scores(self, player_id: Optional[int] = None):
        """Clear progress and history of one player (default: active)."""
        try:
            pid = self._pid(player_id)
            with self.conn:
                self.conn.execute("DELETE FROM progress WHERE player_id = ?", (pid,))
                self.conn.execute("DELETE FROM history WHERE player_id = ?", (pid,))
            logger.info(f"Scores reset for player #{pid}")
        except Exception as e:
            logger.error(f"Failed to reset scores: {e}")

    # ------------------------------------------------------------------ reporting

    def leaderboard(self) -> List[Dict]:
        """Players ranked by score, then by total solving time."""
        rows = self.conn.execute("""
            SELECT p.id AS player_id, p.name,
                   COALESCE(SUM(g.earned), 0) AS score,
                   COALESCE(SUM(g.completed), 0) AS completed,
                   COALESCE(SUM(CASE WHEN g.completed = 1 THEN g.best_time END), 0) AS total_time,
                   COALESCE(SUM(g.hints_used), 0) AS hints_used,
                   MAX(g.completed_at) AS last_solved
            FROM players p LEFT JOIN progress g ON g.player_id = p.id
            GROUP BY p.id
            ORDER BY score DESC, total_time ASC, p.name ASC
        """).fetchall()
        max_score = self.get_max_score()
        return [dict(r, rank=i + 1, max_score=max_score) for i, r in enumerate(rows)]

    def export_csv(self, out: TextIO) -> int:
        """Write one row per (player, challenge). Returns the number of rows."""
        writer = csv.writer(out)
        writer.writerow(["player", "module", "challenge_id", "challenge", "points", "earned",
                         "completed", "best_time_s", "hints_used", "completed_at"])
        rows = self.conn.execute("""
            SELECT p.name, c.module, c.id, c.name AS challenge, c.points,
                   COALESCE(g.earned, 0), COALESCE(g.completed, 0), g.best_time,
                   COALESCE(g.hints_used, 0), g.completed_at
            FROM players p CROSS JOIN challenges c
            LEFT JOIN progress g ON g.player_id = p.id AND g.challenge_id = c.id
            ORDER BY p.name, c.id
        """).fetchall()
        for r in rows:
            writer.writerow(list(r))
        return len(rows)

    def close(self):
        try:
            self.conn.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Failed to close database: {e}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s')
    from app.catalog import build_catalog
    from app.scenarios.registry import discover

    db = Database(":memory:", catalog=build_catalog(discover().scenarios))
    db.mark_completed(1, 45)
    print(db.get_stats())
    db.export_csv(sys.stdout)
    db.close()
