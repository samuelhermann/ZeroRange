"""Generic scenario engine: one class runs every ScenarioDef.

Replaces the near-identical ``CoffeeHandler`` / ``GarageHandler`` classes.
"""

import logging
from typing import Any, Callable, Dict, Optional, Type

from app.core.config import config_section, load_config
from app.core.events import EventBus
from app.core.hid import HIDReader
from app.core.ui import UI, Button, Clock
from app.scenarios.base import ScenarioDef, Stage, Step

logger = logging.getLogger(__name__)


class ScenarioRunner:
    """Drives a scenario on the LCD: disclaimer -> stage menu -> stages.

    Args:
        scenario:    the declarative definition.
        lcd, db:     LCDManager / Database (or test doubles).
        proxmark:    ProxmarkHandler or None.
        hackrf:      HackRFHandler or None.
        sse_emit:    event sink; defaults to ``EventBus(scenario.key)``.
        config:      scenario config; defaults to ``scenario.resolve_config()``.
        hid_factory: zero-arg callable returning a HIDReader-like object; only
                     called if a step requires ``"hid"``.
        clock:       injectable clock (tests).
        show_disclaimer: set False to skip the disclaimer slides (tests).
    """

    def __init__(self, scenario: ScenarioDef, lcd, db, *, proxmark=None, hackrf=None,
                 sse_emit: Optional[Callable[[Dict[str, Any]], None]] = None,
                 config: Optional[Dict[str, Any]] = None,
                 hid_factory: Optional[Callable[[], Any]] = None,
                 clock: Optional[Clock] = None, show_disclaimer: bool = True):
        self.scenario = scenario
        self.show_disclaimer = show_disclaimer
        self.lcd = lcd
        self.db = db
        self.devices: Dict[str, Any] = {"proxmark": proxmark, "hackrf": hackrf}
        self.sse = EventBus(scenario.key) if sse_emit is None else sse_emit
        self.cfg = config if config is not None else scenario.resolve_config()
        self._hid_factory = self._default_hid_factory if hid_factory is None else hid_factory
        self._hid = None
        self.clock = clock
        self.ui = UI(lcd, clock)
        self._items = list(scenario.steps)

    # ------------------------------------------------------------------ info

    @property
    def key(self) -> str:
        return self.scenario.key

    @property
    def title(self) -> str:
        return self.scenario.title

    @property
    def max_points(self) -> int:
        return self.scenario.max_points

    def _completed(self, stage: Type[Stage]) -> bool:
        status = self.db.get_challenge_status(stage.challenge_id)
        return bool(status and status.get("completed"))

    def get_module_score(self) -> int:
        total = 0
        for stage in self.scenario.stages:
            status = self.db.get_challenge_status(stage.challenge_id)
            if status and status.get("completed"):
                total += status.get("points", stage.points)
        return total

    def is_complete(self) -> bool:
        return all(self._completed(s) for s in self.scenario.stages)

    # ------------------------------------------------------------------ hardware

    @staticmethod
    def _default_hid_factory() -> HIDReader:
        preferred = config_section("settings", load_config()).get("hid_device")
        return HIDReader.autodetect(preferred)

    def _device(self, name: Optional[str]):
        if name is None:
            return None
        if name == "hid":
            return self._hid
        return self.devices.get(name)

    # ------------------------------------------------------------------ screens

    def _show_disclaimer(self) -> None:
        sc = self.scenario
        if sc.disclaimer and self.show_disclaimer:
            self.ui.slides(sc.brand or sc.title, sc.disclaimer, hold=1.5, skippable=True)

    def _render_item(self, index: int):
        item = self._items[index]
        marker = " "
        if issubclass(item, Stage) and self._completed(item):
            marker = "✓"
        score = f"{self.get_module_score()}/{self.max_points}"
        footer = f"U/D SEL=Go {score}"
        if len(footer) > 16:
            footer = f"U/D {score}"
        return f">{item.title[:14]}{marker}", footer

    def _celebrate(self) -> None:
        line0, line1 = self.scenario.complete_lines
        self.emit({"event": "scenario_complete", "score": self.get_module_score(),
                   "max": self.max_points})
        self.ui.show(line0, f"{line1} {self.get_module_score()}/{self.max_points}"[:16], hold=4)

    def emit(self, data: Dict[str, Any]) -> None:
        try:
            self.sse(data)
        except Exception as exc:
            logger.debug("Event emit failed: %s", exc)

    # ------------------------------------------------------------------ public

    def run(self) -> int:
        """Entry point called by zerorange.py. Returns points earned this session."""
        sc = self.scenario
        logger.info("Scenario %s started", sc.key)
        self.emit({"event": "session_start", "scenario": sc.key})
        self._show_disclaimer()

        if "hid" in sc.devices():
            self._hid = self._hid_factory()

        earned = 0
        selected = 0
        try:
            while True:
                choice = self.ui.menu(len(self._items), self._render_item, start=selected)
                if choice is None:
                    break
                selected = choice
                earned += self._launch(self._items[choice])
        finally:
            self.close()

        logger.info("Scenario %s exited, earned %s pts this session", sc.key, earned)
        return earned

    def _launch(self, item: Type[Step]) -> int:
        was_complete = self.is_complete()
        step = item(self.lcd, self.db, self.cfg, self._device(item.requires), self.sse,
                    clock=self.clock)
        try:
            points = int(step.run() or 0)
        except Exception as exc:
            logger.error("%s/%s crashed: %s", self.key, item.__name__, exc, exc_info=True)
            self.emit({"event": "stage_error", "step": item.__name__})
            self.ui.show(f"{item.title[:10]} error!", "Check logs ◄")
            self.ui.wait(Button.BACK, timeout=5)
            return 0
        if not issubclass(item, Stage):
            return 0
        if points and not was_complete and self.is_complete():
            self._celebrate()
        return points

    def close(self) -> None:
        if self._hid is not None:
            try:
                self._hid.close()
            finally:
                self._hid = None
