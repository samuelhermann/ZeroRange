"""Trainer dashboard: players, leaderboard, sessions, exports, simulator.

Everything under ``/dashboard`` requires HTTP Basic auth (user ``trainer``,
password from app/core/auth.py — shown on the LCD under Settings > Web login).
State-changing requests also need a CSRF token, because browsers replay Basic
credentials on cross-site form posts.
"""

import functools
import hmac
import io
import json
import secrets
from datetime import date
from pathlib import Path

from flask import (Blueprint, Response, abort, current_app, redirect, render_template, request,
                   send_file, url_for)

from app.core.auth import TRAINER_USER, check_credentials
from app.core.paths import SIM_FLAG, active_db_path
from app.core import session as sessions
from database import Database

dashboard_bp = Blueprint("dashboard", __name__, template_folder="templates")


def _unauthorized() -> Response:
    return Response("Trainer login required (see LCD > Settings > Web login).\n", 401,
                    {"WWW-Authenticate": 'Basic realm="ZeroRange trainer"'})


def _authenticated() -> bool:
    auth = request.authorization
    return bool(auth) and check_credentials(auth.username, auth.password)


def requires_trainer_no_csrf(view):
    """Basic auth only — for fetch() endpoints that cannot carry a form token
    (they only produce cosmetic events)."""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        return view(*args, **kwargs) if _authenticated() else _unauthorized()
    return wrapper


def requires_trainer(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not _authenticated():
            return _unauthorized()
        if request.method == "POST":
            token = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(token.encode(), _csrf_token().encode()):
                abort(400, "Bad CSRF token - reload the page")
        return view(*args, **kwargs)
    return wrapper


def _csrf_token() -> str:
    cfg = current_app.config
    if "ZR_CSRF" not in cfg:
        cfg["ZR_CSRF"] = secrets.token_urlsafe(24)
    return cfg["ZR_CSRF"]


def _db() -> Database:
    return Database(str(current_app.config.get("ZR_DB_PATH") or active_db_path()))


def _registry():
    return current_app.config["ZR_REGISTRY"]


def _session_paths():
    cfg = current_app.config
    return Path(cfg.get("ZR_SESSION_FILE", sessions.SESSION_FILE)), \
        Path(cfg.get("ZR_SESSION_DIR", sessions.SESSION_DIR))


def _sim_flag() -> Path:
    return Path(current_app.config.get("ZR_SIM_FLAG", SIM_FLAG))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@dashboard_bp.route("/")
@requires_trainer
def index():
    db = _db()
    try:
        board = db.leaderboard()
        active = db.active_player_id
        max_score = db.get_max_score()
    finally:
        db.close()
    session_file, session_dir = _session_paths()
    session = sessions.load_session(session_file)
    files = []
    if session_dir.is_dir():
        files = sorted(str(p.relative_to(session_dir)) for p in session_dir.rglob("*") if p.is_file())
    return render_template("dashboard/index.html", board=board, active=active, max_score=max_score,
                           session=session, files=files, csrf=_csrf_token(),
                           sim=_sim_flag().exists(), user=TRAINER_USER,
                           scenarios=list(_registry()))


@dashboard_bp.route("/certificate/<int:player_id>")
@requires_trainer
def certificate(player_id: int):
    db = _db()
    try:
        row = next((r for r in db.leaderboard() if r["player_id"] == player_id), None)
        if row is None:
            abort(404)
        challenges = [c for c in db.get_all_challenges(player_id) if c["completed"]]
    finally:
        db.close()
    titles = {s.key: s.title for s in _registry()}
    return render_template("dashboard/certificate.html", player=row, challenges=challenges,
                           titles=titles, today=date.today().isoformat())


@dashboard_bp.route("/export.csv")
@requires_trainer
def export_csv():
    buf = io.StringIO()
    db = _db()
    try:
        db.export_csv(buf)
    finally:
        db.close()
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=zerorange-{date.today().isoformat()}.csv"})


@dashboard_bp.route("/session/files/<path:name>")
@requires_trainer
def session_file(name: str):
    _, session_dir = _session_paths()
    path = (session_dir / name).resolve()
    if session_dir.resolve() not in path.parents or not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _back():
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/players", methods=["POST"])
@requires_trainer
def add_player():
    db = _db()
    try:
        pid = db.add_player(request.form.get("name", ""))
        if request.form.get("activate"):
            db.set_active_player(pid)
    except Exception as exc:
        abort(400, str(exc))
    finally:
        db.close()
    return _back()


@dashboard_bp.route("/players/<int:player_id>/<action>", methods=["POST"])
@requires_trainer
def player_action(player_id: int, action: str):
    db = _db()
    try:
        if action == "activate":
            db.set_active_player(player_id)
        elif action == "rename":
            db.rename_player(player_id, request.form.get("name", ""))
        elif action == "reset":
            db.reset_scores(player_id)
        elif action == "delete":
            db.delete_player(player_id)
        else:
            abort(404)
    except ValueError as exc:
        abort(400, str(exc))
    finally:
        db.close()
    return _back()


@dashboard_bp.route("/session/<action>", methods=["POST"])
@requires_trainer
def session_action(action: str):
    session_file, session_dir = _session_paths()
    if action == "new":
        sessions.new_session(_registry().scenarios, path=session_file, directory=session_dir)
        if request.form.get("reset_scores"):
            db = _db()
            try:
                for player in db.list_players():
                    db.reset_scores(player["id"])
            finally:
                db.close()
    elif action == "clear":
        sessions.clear_session(session_file, session_dir)
    else:
        abort(404)
    return _back()


@dashboard_bp.route("/sim/inject", methods=["POST"])
@requires_trainer
def sim_inject():
    """Simulator panel: forward an event to the simulated devices (``--sim``)."""
    from app.sim.inbox import Inbox
    if not _sim_flag().exists():
        abort(409, "ZeroRange is not running with --sim")
    kind = request.form.get("kind", "")
    payload = {k: v for k, v in request.form.items() if k not in ("csrf", "kind") and v != ""}
    try:
        Inbox(current_app.config.get("ZR_SIM_INBOX")).push(kind, **payload)
    except ValueError as exc:
        abort(400, str(exc))
    return _back()


def session_summary(session: dict) -> str:
    """Secrets as pretty JSON (template helper)."""
    return json.dumps(session.get("overrides", {}), indent=2)


dashboard_bp.add_app_template_filter(session_summary, "session_summary")
