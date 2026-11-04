"""Core types of the scenario framework.

A *scenario* (Coffee, Garage, ...) is a themed chain of scored *stages* plus
optional unscored *tools* (e.g. "Prep Badges").  A scenario is declared, not
programmed: ``challenges/<key>/scenario.py`` exposes ``SCENARIO = ScenarioDef(...)``
and the generic :class:`~app.scenarios.runner.ScenarioRunner` provides the
disclaimer, menu, scoring, hardware wiring, crash isolation and web events.

Writing a stage means subclassing :class:`Stage` (or one of the ready-made
types in :mod:`app.scenarios.stages`) and implementing :meth:`Stage.run`.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List, Optional, Sequence, Tuple, Type

from app.core.config import config_section as _config_section, deep_merge, lookup
from app.core.paths import resolve
from app.core.ui import UI, Clock, normalize_hex

logger = logging.getLogger(__name__)

EventSink = Callable[[Dict[str, Any]], None]

#: Hardware a step can ask for. The runner injects the matching object as ``self.hw``.
KNOWN_DEVICES = ("hid", "proxmark", "hackrf")


def _noop(_event: Dict[str, Any]) -> None:
    return None


class Step:
    """Anything that appears in a scenario menu (scored or not)."""

    #: Menu label (row 0 shows ">" + title + "✓", so keep it <= 14 chars).
    title: ClassVar[str] = ""
    #: One of KNOWN_DEVICES or None. Injected as ``self.hw``.
    requires: ClassVar[Optional[str]] = None
    #: Config keys (dotted) the step reads; checked by tools/validate_scenarios.py.
    config_keys: ClassVar[Tuple[str, ...]] = ()
    #: Config keys whose value is a file path that must exist.
    file_keys: ClassVar[Tuple[str, ...]] = ()

    def __init__(self, lcd, db, config: Optional[Dict[str, Any]], hw=None,
                 sse_emit: Optional[EventSink] = None, *, clock: Optional[Clock] = None):
        self.lcd = lcd
        self.db = db
        self.cfg: Dict[str, Any] = config or {}
        self.hw = hw
        self.sse: EventSink = _noop if sse_emit is None else sse_emit
        self.ui = UI(lcd, clock)

    # -- config helpers -----------------------------------------------------

    def cfg_get(self, key: str, default: Any = None) -> Any:
        return lookup(self.cfg, key, default)

    def cfg_hex(self, key: str, default: str = "") -> str:
        return normalize_hex(self.cfg_get(key, default) or "")

    def cfg_path(self, key: str, default: str = "") -> Path:
        return resolve(self.cfg_get(key, default) or default)

    # -- events -------------------------------------------------------------

    def emit(self, payload: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        """Publish an event for the web companion. Never raises."""
        data = dict(payload or {}, **fields)
        try:
            self.sse(data)
        except Exception as exc:  # the web mirror must never break a stage
            logger.debug("Event emit failed: %s", exc)

    # -- hardware -----------------------------------------------------------

    def hardware_ready(self, allow_simulation: bool = False) -> bool:
        if self.hw is None:
            return False
        if getattr(self.hw, "available", True) is False:
            return False
        if not allow_simulation and getattr(self.hw, "simulation_mode", False):
            return False
        return True

    def require_hardware(self, line0: str, line1: str = "Connect it! ◄",
                         allow_simulation: bool = False) -> bool:
        """Return True if hardware is usable, otherwise explain and wait for BACK."""
        if self.hardware_ready(allow_simulation):
            return True
        logger.info("%s: required hardware %r not available", type(self).__name__, self.requires)
        self.ui.notice(line0, line1)
        return False

    @classmethod
    def defaults(cls) -> Dict[str, Any]:
        """Fallback values for ``config_keys`` (used by the validator)."""
        return {}

    def run(self) -> int:  # pragma: no cover - abstract
        raise NotImplementedError


class Stage(Step):
    """A scored step backed by one row of the ``challenges`` table."""

    #: Stable DB id (never reuse or renumber: progress is stored against it).
    challenge_id: ClassVar[int] = 0
    #: Position in the scenario (1, 2, 3...). Sent as ``"stage"`` in web events.
    number: ClassVar[int] = 0
    #: DB / web name and description.
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    points: ClassVar[int] = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._t0: Optional[float] = None

    # -- progress -----------------------------------------------------------

    def already_complete(self) -> bool:
        status = self.db.get_challenge_status(self.challenge_id)
        return bool(status and status.get("completed"))

    def start_timer(self) -> None:
        self._t0 = self.ui.now()

    def elapsed(self) -> int:
        if self._t0 is None:
            return 0
        return max(0, int(self.ui.now() - self._t0))

    def award(self, *extra_events: Dict[str, Any]) -> int:
        """Persist success, notify the web companion, return the points."""
        elapsed = self.elapsed()
        self.db.add_history(self.challenge_id, True, elapsed)
        self.db.mark_completed(self.challenge_id, elapsed)
        logger.info("%s solved in %ss (+%s pts)", type(self).__name__, elapsed, self.points)
        self.emit(stage=self.number, status="success", points=self.points)
        self.emit(event="stage_complete", stage=self.number, points=self.points)
        for event in extra_events:
            self.emit(event)
        return self.points

    # -- common screens -----------------------------------------------------

    def show_already_solved(self, hold: float = 2.0) -> None:
        self.ui.show(f"Stage {self.number} done!", "Already solved ✓", hold=hold)

    def finish(self, line0: Optional[str] = None, line1: str = "◄=Back to menu") -> None:
        self.ui.notice(line0 or f"Stage {self.number} done!", line1)


class Tool(Step):
    """An unscored helper shown in the scenario menu (trainer prep, demos...)."""

    def run(self) -> int:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass(frozen=True)
class ScenarioDef:
    """Declarative description of a scenario. See docs/SCENARIO_GUIDE.md."""

    key: str                                  # package name & DB module, e.g. "coffee"
    title: str                                # main-menu label (<= 9 chars)
    stages: Sequence[Type[Stage]]
    brand: str = ""                           # row 0 of the disclaimer (<= 16 chars)
    description: str = ""
    disclaimer: Sequence[str] = ()            # row-1 lines (<= 16 chars each)
    tools: Sequence[Type[Tool]] = ()
    config_section: Optional[str] = None      # defaults to key
    complete_lines: Tuple[str, str] = ("SCENARIO", "COMPLETE!")
    order: int = 100                          # main-menu position
    #: Scenario-level config defaults; config.json[section] overrides them.
    defaults: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def resolve_config(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """``defaults`` deep-merged with ``config.json[section]`` (+ local overlay)."""
        return deep_merge(self.defaults, _config_section(self.section, config))

    @property
    def section(self) -> str:
        return self.config_section or self.key

    @property
    def max_points(self) -> int:
        return sum(s.points for s in self.stages)

    @property
    def steps(self) -> List[Type[Step]]:
        return [*self.stages, *self.tools]

    def devices(self) -> set:
        return {s.requires for s in self.steps if s.requires}

    def catalog_rows(self) -> List[Tuple[int, str, str, str, int]]:
        """Rows for ``Database.sync_catalog``: (id, module, name, description, points)."""
        return [(s.challenge_id, self.key, s.name or s.title, s.description, s.points)
                for s in self.stages]

    def to_public_dict(self) -> Dict[str, Any]:
        """JSON-safe metadata (used by the web companion)."""
        return {
            "key": self.key,
            "title": self.title,
            "brand": self.brand,
            "description": self.description,
            "max_points": self.max_points,
            "stages": [
                {"number": s.number, "title": s.title, "name": s.name or s.title,
                 "description": s.description, "points": s.points,
                 "challenge_id": s.challenge_id, "requires": s.requires}
                for s in self.stages
            ],
        }
