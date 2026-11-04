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
from app.core.paths import DB_PATH, EVENTS_DIR
from app.scenarios.base import ScenarioDef


def read_progress(scenario: ScenarioDef, db_path: Path = DB_PATH) -> Dict[str, Any]:
    """Scenario metadata + completion flags (read-only DB access)."""
    data = scenario.to_public_dict()
    completed: Dict[int, bool] = {}
    if Path(db_path).is_file():
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2) as conn:
                ids = [s["challenge_id"] for s in data["stages"]]
                marks = ",".join("?" * len(ids))
                for cid, done in conn.execute(
                        f"SELECT id, completed FROM challenges WHERE id IN ({marks})", ids):
                    completed[cid] = bool(done)
        except sqlite3.Error:
            pass
    score = 0
    for stage in data["stages"]:
        stage["completed"] = completed.get(stage["challenge_id"], False)
        score += stage["points"] if stage["completed"] else 0
    data["score"] = score
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
        return jsonify(read_progress(scenario, db_path or DB_PATH))

    return bp
