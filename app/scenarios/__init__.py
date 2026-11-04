"""Scenario framework: declare a scenario in ``challenges/<key>/scenario.py``
and it shows up on the LCD menu, in the scores DB and on the web companion.

See docs/SCENARIO_GUIDE.md.
"""

from app.scenarios.base import KNOWN_DEVICES, ScenarioDef, Stage, Step, Tool  # noqa: F401

__all__ = ["KNOWN_DEVICES", "ScenarioDef", "Stage", "Step", "Tool"]
