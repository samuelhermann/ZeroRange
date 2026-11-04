"""Trainer dashboard: auth, CSRF, players, session, exports, simulator panel."""

import base64
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.catalog import build_catalog
from app.scenarios.registry import discover
from database import Database

try:
    import flask  # noqa: F401
    HAVE_FLASK = True
except ImportError:  # pragma: no cover
    HAVE_FLASK = False


def basic(user="trainer", password="s3cret"):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@unittest.skipUnless(HAVE_FLASK, "flask not installed")
class TestDashboard(unittest.TestCase):

    def setUp(self):
        from app.web import create_app
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "scores.db"
        registry = discover()
        db = Database(str(self.db_path), catalog=build_catalog(registry.scenarios))
        db.rename_player(1, "Alice")
        db.mark_completed(1, 30)
        db.close()
        self.files = {"session_file": root / "session.json", "session_dir": root / "session",
                      "sim_flag": root / "sim_mode", "sim_inbox": root / "inbox.jsonl"}
        self.env = mock.patch.dict("os.environ", {"ZERORANGE_TRAINER_PASSWORD": "s3cret"})
        self.env.start()
        self.app = create_app(registry, db_path=self.db_path, events_dir=root, **self.files)
        self.client = self.app.test_client()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def db(self):
        return Database(str(self.db_path))

    def csrf(self):
        html = self.client.get("/dashboard/", headers=basic()).get_data(as_text=True)
        return re.search(r'name="csrf" value="([^"]+)"', html).group(1)

    def post(self, url, **data):
        data.setdefault("csrf", self.csrf())
        return self.client.post(url, data=data, headers=basic())

    # auth ---------------------------------------------------------------

    def test_requires_login(self):
        self.assertEqual(self.client.get("/dashboard/").status_code, 401)
        self.assertEqual(self.client.get("/dashboard/", headers=basic(password="nope")).status_code, 401)
        self.assertEqual(self.client.get("/dashboard/export.csv").status_code, 401)
        r = self.client.get("/dashboard/", headers=basic())
        self.assertEqual(r.status_code, 200)
        self.assertIn("Alice", r.get_data(as_text=True))

    def test_post_without_csrf_is_rejected(self):
        r = self.client.post("/dashboard/players", data={"name": "Eve"}, headers=basic())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(self.db().list_players()), 1)

    def test_garage_debug_route_needs_login(self):
        self.assertEqual(self.client.post("/scenarios/garage/debug/send-press").status_code, 401)
        r = self.client.post("/scenarios/garage/debug/send-press", headers=basic())
        self.assertEqual(r.status_code, 204)

    # players ------------------------------------------------------------

    def test_player_lifecycle(self):
        self.assertEqual(self.post("/dashboard/players", name="Bob", activate="1").status_code, 302)
        db = self.db()
        bob = next(p for p in db.list_players() if p["name"] == "Bob")
        self.assertEqual(db.active_player_id, bob["id"])
        self.post(f"/dashboard/players/{bob['id']}/rename", name="Bobby")
        self.post("/dashboard/players/1/activate")
        self.post("/dashboard/players/1/reset")
        db = self.db()
        self.assertEqual(db.get_total_score(1), 0)
        self.assertEqual(db.active_player_id, 1)
        self.assertIn("Bobby", [p["name"] for p in db.list_players()])
        self.post(f"/dashboard/players/{bob['id']}/delete")
        self.assertEqual([p["name"] for p in self.db().list_players()], ["Alice"])
        # the last player cannot be deleted
        self.assertEqual(self.post("/dashboard/players/1/delete").status_code, 400)

    def test_csv_and_certificate(self):
        csv_text = self.client.get("/dashboard/export.csv", headers=basic()).get_data(as_text=True)
        self.assertIn("player,module,challenge_id", csv_text)
        self.assertIn("Alice,ibutton,1,Touch & Read,10,10,1,30", csv_text)
        cert = self.client.get("/dashboard/certificate/1", headers=basic()).get_data(as_text=True)
        self.assertIn("Certificate of completion", cert)
        self.assertIn("Alice", cert)
        self.assertIn("Touch &amp; Read", cert)
        self.assertEqual(self.client.get("/dashboard/certificate/99", headers=basic()).status_code, 404)

    # sessions -----------------------------------------------------------

    def test_new_session_shows_secrets_and_files(self):
        self.post("/dashboard/session/new", reset_scores="1")
        session = json.loads(self.files["session_file"].read_text())
        self.assertIn("coffee", session["overrides"])
        self.assertEqual(self.db().get_total_score(1), 0)
        html = self.client.get("/dashboard/", headers=basic()).get_data(as_text=True)
        self.assertIn(session["overrides"]["coffee"]["master_key_b_hex"], html)
        r = self.client.get("/dashboard/session/files/garage/press_N.sub", headers=basic())
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Flipper SubGhz RAW File", r.data)
        r = self.client.get("/dashboard/session/files/../scores.db", headers=basic())
        self.assertEqual(r.status_code, 404)
        self.post("/dashboard/session/clear")
        self.assertFalse(self.files["session_file"].exists())

    # simulator ------------------------------------------------------------

    def test_simulator_panel(self):
        self.assertEqual(self.post("/dashboard/sim/inject", kind="ibutton", uid="01AB").status_code, 409)
        self.files["sim_flag"].write_text("1")
        self.assertIn("Simulator", self.client.get("/dashboard/", headers=basic()).get_data(as_text=True))
        self.assertEqual(self.post("/dashboard/sim/inject", kind="ibutton", uid="01AB").status_code, 302)
        event = json.loads(self.files["sim_inbox"].read_text().splitlines()[-1])
        self.assertEqual((event["kind"], event["uid"]), ("ibutton", "01AB"))
        self.assertEqual(self.post("/dashboard/sim/inject", kind="bogus").status_code, 400)


class TestAuth(unittest.TestCase):

    def test_generated_password_is_persisted(self):
        from app.core.auth import check_credentials, get_trainer_password
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ZERORANGE_TRAINER_PASSWORD", None)
            path = Path(tmp) / "pw"
            first = get_trainer_password({}, path=path)
            self.assertEqual(len(first), 8)
            self.assertEqual(get_trainer_password({}, path=path), first)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(check_credentials("trainer", first, config={}, path=path))
            self.assertFalse(check_credentials("trainer", "wrong", config={}, path=path))
            self.assertFalse(check_credentials("trainer", "é", config={}, path=path))
            self.assertEqual(get_trainer_password({"web": {"trainer_password": "cfg"}}, path=path), "cfg")
