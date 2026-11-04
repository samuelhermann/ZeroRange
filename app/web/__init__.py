"""ZeroRange web companion — Flask application factory.

Scenario pages are generated from the scenario registry: dropping a new
``challenges/<key>/scenario.py`` is enough to get ``/scenarios/<key>/``.
A module ``app/web/routes/<key>.py`` may expose ``extend(bp)`` to add
scenario-specific routes.
"""

import importlib
import logging

from flask import Flask

from app.scenarios.registry import Registry, discover
from app.web.scenario_blueprint import make_scenario_blueprint

logger = logging.getLogger(__name__)


def create_app(registry: Registry = None, *, db_path=None, events_dir=None, **settings) -> Flask:
    """``settings`` -> ``app.config["ZR_<NAME>"]`` (tests point files to a tmp dir)."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    registry = registry if registry is not None else discover()
    app.config["ZR_REGISTRY"] = registry
    if db_path is not None:
        app.config["ZR_DB_PATH"] = str(db_path)
    for key, value in settings.items():
        app.config[f"ZR_{key.upper()}"] = value
    blueprint_kwargs = {"db_path": db_path, "events_dir": events_dir}

    for scenario in registry:
        bp = make_scenario_blueprint(scenario, **blueprint_kwargs)
        try:
            extra = importlib.import_module(f"app.web.routes.{scenario.key}")
        except ModuleNotFoundError:
            extra = None
        if extra is not None and hasattr(extra, "extend"):
            extra.extend(bp)
        app.register_blueprint(bp, url_prefix=f"/scenarios/{scenario.key}")

    from app.web.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")

    from app.web.routes.index import index_bp
    app.register_blueprint(index_bp, url_prefix="/")
    return app
