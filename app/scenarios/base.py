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
import random
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List, Optional, Sequence, Tuple, Type

from app.core.config import config_section as _config_section, deep_merge, lookup
from app.core.paths import resolve
from app.core.session import session_overrides
from app.core.ui import UI, Button, Clock, normalize_hex

logger = logging.getLogger(__name__)

EventSink = Callable[[Dict[str, Any]], None]

#: Hardware a step can ask for. The runner injects the matching object as ``self.hw``.
KNOWN_DEVICES = ("hid", "proxmark", "hackrf", "flirc")


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
        # HIDReader.available / HackRF & FLIRC .device_connected
        if any(getattr(self.hw, attr, True) is False for attr in ("available", "device_connected")):
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
    #: Hints shown with the RIGHT (►) key, one at a time, each costing
    #: ``hint_penalty`` points (at most half of the points in total).
    hints: ClassVar[Sequence[str]] = ()
    hint_penalty: ClassVar[int] = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._t0: Optional[float] = None
        self.awarded: Optional[int] = None
        if self.hints:
            self.ui.hint_handler = self.show_hints

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

    def _status(self) -> Dict[str, Any]:
        return self.db.get_challenge_status(self.challenge_id) or {}

    def earned(self) -> int:
        """Points already credited (partial credit included)."""
        return int(self._status().get("earned", 0))

    def hints_used(self) -> int:
        return int(self._status().get("hints_used", 0))

    def penalty(self) -> int:
        return min(self.hints_used() * self.hint_penalty, self.points // 2)

    def award(self, *extra_events: Dict[str, Any]) -> int:
        """Persist success (minus hint penalty), notify the web companion,
        return the points earned."""
        elapsed = self.elapsed()
        points = self.points - self.penalty()
        self.db.add_history(self.challenge_id, True, elapsed)
        self.db.mark_completed(self.challenge_id, elapsed, points)
        self.awarded = points
        logger.info("%s solved in %ss (+%s/%s pts)", type(self).__name__, elapsed, points, self.points)
        self.emit(stage=self.number, status="success", points=points)
        self.emit(event="stage_complete", stage=self.number, points=points)
        for event in extra_events:
            self.emit(event)
        return points

    def award_partial(self, points: int, part: str) -> None:
        """Credit part of the stage (e.g. "1a") without completing it."""
        self.db.record_partial(self.challenge_id, points)
        logger.info("%s part %s: %s pts credited", type(self).__name__, part, points)
        self.emit(event="substage_complete", stage=part, points=points)

    # -- waiting for the learner ------------------------------------------------

    def wait_for(self, probe: Callable[[], Any], *, timeout: float,
                 interval: float = 0.2, row: int = 1) -> Tuple[Any, str]:
        """Poll ``probe()`` until it returns something truthy.

        Shows a ``◄=Back [42s]`` countdown on *row*. Returns ``(value, "ok")``,
        ``(None, "back")`` or ``(None, "timeout")``. RIGHT opens the hints.
        """
        start = self.ui.now()
        shown = None
        while True:
            value = probe()
            if value:
                return value, "ok"
            if self.ui.poll(Button.BACK):
                return None, "back"
            remaining = int(timeout - (self.ui.now() - start))
            if remaining <= 0:
                return None, "timeout"
            if remaining != shown:
                self.ui.line(row, f"◄=Back [{remaining}s]")
                shown = remaining
            self.ui.sleep(interval)

    def retry(self, line0: str) -> bool:
        """``line0`` + "SEL=Retry ◄=Back"; True to try again."""
        return self.ui.confirm(line0, "SEL=Retry ◄=Back")

    # -- hints --------------------------------------------------------------

    def show_hints(self) -> None:
        """RIGHT-key handler: show unlocked hints, offer to buy the next one."""
        used = min(self.hints_used(), len(self.hints))
        if used == 0:
            if not self._buy_hint(1):
                return
            used = 1
        while True:
            self._page(f"Hint {used}/{len(self.hints)}", self.hints[used - 1])
            if used >= len(self.hints) or not self._buy_hint(used + 1):
                return
            used += 1

    def _buy_hint(self, n: int) -> bool:
        cost = f"-{self.hint_penalty}pt" if self.penalty() + self.hint_penalty <= self.points // 2 \
            else "free"
        if not self.ui.confirm(f"Hint {n}/{len(self.hints)}? {cost}", "SEL=Yes ◄=No"):
            return False
        total = self.db.use_hint(self.challenge_id)
        self.emit(event="hint_used", stage=self.number, hints_used=total)
        return True

    def _page(self, title: str, text: str) -> None:
        lines = textwrap.wrap(text, 16) or [""]
        pages = [(title, lines[0])] + [(lines[i], lines[i + 1] if i + 1 < len(lines) else "")
                                       for i in range(1, len(lines), 2)]
        for line0, line1 in pages:
            self.ui.show(line0, line1)
            if self.ui.wait(Button.SELECT, Button.RIGHT, Button.BACK) == Button.BACK:
                return

    # -- common screens -----------------------------------------------------

    def show_already_solved(self, hold: float = 2.0) -> None:
        self.ui.show(f"Stage {self.number} done!", "Already solved ✓", hold=hold)

    def finish(self, line0: Optional[str] = None, line1: Optional[str] = None) -> None:
        if line1 is None:
            line1 = f"+{self.awarded}pts ◄=Menu" if self.awarded is not None else "◄=Back to menu"
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
    #: Stage N is locked until stage N-1 is solved (config key "sequential" overrides).
    sequential: bool = False
    #: ``secrets(rng, config, out_dir) -> overrides`` regenerates per-session
    #: secrets (keys, UIDs, badge files...). See app/core/session.py.
    secrets: Optional[Callable[[random.Random, Dict[str, Any], Path], Dict[str, Any]]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def resolve_config(self, config: Optional[Dict[str, Any]] = None,
                       session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """``defaults`` <- ``config.json[section]`` (+ local overlay) <- session secrets."""
        merged = deep_merge(self.defaults, _config_section(self.section, config))
        overrides = session_overrides(self.section, session)
        return deep_merge(merged, overrides) if overrides else merged

    def is_sequential(self, config: Dict[str, Any]) -> bool:
        return bool(config.get("sequential", self.sequential))

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
