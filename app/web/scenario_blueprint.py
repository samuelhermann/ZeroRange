"""One Flask blueprint factory for every scenario.

Each scenario gets, under ``/scenarios/<key>/``:

* ``/``            its bespoke page ``templates/scenarios/<key>.html`` if present,
                   otherwise the generic ``templates/scenarios/_generic.html``;
* ``/events``      Server-Sent Events following ``run/events/<key>.jsonl``
                   (written by the LCD process — see app/core/events.py);
* ``/api/status``  current progress read from scores.db, so a page opened
                   mid-session shows already-solved stages.
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, Response, jsonify, render_template, stream_with_context
from jinja2 import TemplateNotFound

from app.core.events import EventBus, channel_path, sse_stream
from app.core.paths import EVENTS_DIR, active_db_path
from app.scenarios.base import ScenarioDef
from database import Database


def read_progress(scenario: ScenarioDef, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Scenario metadata + the active player's progress."""
    db_path = Path(db_path or active_db_path())
    data = scenario.to_public_dict()
    statuses: Dict[int, Dict[str, Any]] = {}
    player = None
    if Path(db_path).is_file():
        try:
            db = Database(str(db_path))
            try:
                player = db.get_active_player()["name"]
                for stage in data["stages"]:
                    statuses[stage["challenge_id"]] = db.get_challenge_status(stage["challenge_id"]) or {}
            finally:
                db.close()
        except sqlite3.Error:
            pass
    score = 0
    for stage in data["stages"]:
        status = statuses.get(stage["challenge_id"], {})
        stage["completed"] = bool(status.get("completed"))
        stage["earned"] = int(status.get("earned", 0))
        stage["hints_used"] = int(status.get("hints_used", 0))
        score += stage["earned"]
    data["score"] = score
    data["player"] = player
    return data


def make_scenario_blueprint(scenario: ScenarioDef, *, events_dir: Optional[Path] = None,
                            db_path: Optional[Path] = None) -> Blueprint:
    bp = Blueprint(
        scenario.key,
        __name__,
        static_folder="static",
        static_url_path="/static",
        template_folder="templates",
    )
    events_file = channel_path(scenario.key, events_dir or EVENTS_DIR)
    # Publisher for scenario-specific routes added via routes/<key>.py:extend(bp)
    bp.event_bus = EventBus(scenario.key, events_dir or EVENTS_DIR)

    @bp.route("/")
    def page():
        try:
            return render_template(f"scenarios/{scenario.key}.html", scenario=scenario)
        except TemplateNotFound:
            return render_template("scenarios/_generic.html", scenario=scenario)

    @bp.route("/events")
    def events():
        return Response(
            stream_with_context(sse_stream(events_file)),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @bp.route("/api/status")
    def status():
        return jsonify(read_progress(scenario, db_path))

    return bp
