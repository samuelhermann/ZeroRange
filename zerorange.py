#!/usr/bin/env python3
"""
ZeroRange - Flipper Zero Training System
Main application: screen-based state machine on a 16x2 LCD + 5 buttons.

Menus are data-driven:
  * classic modules (iButton, NFC, RFID, SubGHZ, IR) come from app/catalog.py
  * scenarios (Coffee, Garage, ...) are auto-discovered in challenges/*/scenario.py
"""

import importlib
import logging
import signal
import socket
import sys
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from app.catalog import CLASSIC_MODULES, ClassicModule, build_catalog
from app.core.config import config_section, load_config
from app.core.events import EventBus
from app.core.paths import DB_PATH, LOG_DIR
from app.core.ui import UI, Button
from app.scenarios.registry import Registry, discover
from app.scenarios.runner import ScenarioRunner
from database import Database

logger = logging.getLogger("zerorange")

VERSION = "1.1"

#: A screen is a blocking function returning the next screen (None = main menu).
Screen = Callable[[], Optional[Callable]]


def get_ip_address() -> str:
    """Best-effort LAN IP (no packet is actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "No IP"


def score_line(title: str, score: int, max_score: int, width: int = 16) -> str:
    """``">Coffee   10/210"`` — title shrinks so the score always fits."""
    score_text = f"{score}/{max_score}"
    room = max(1, width - 1 - len(score_text))
    return f">{title[:room]:<{room}}{score_text}"


@dataclass
class MenuEntry:
    title: str
    open: Screen


class ZeroRange:
    """Main application class."""

    def __init__(self, lcd=None, db=None, registry: Optional[Registry] = None, clock=None):
        self.lcd = lcd
        self.db = db
        self.registry = registry
        self.clock = clock
        self.ui: Optional[UI] = UI(lcd, clock) if lcd is not None else None
        self.config = load_config()

        # Hardware handlers (None when the device / library is missing)
        self.ibutton = None
        self.proxmark = None
        self.nfc = None
        self.rfid = None
        self.hackrf = None
        self.subghz = None
        self.flirc = None
        self.ir = None

        self.scenarios: List[ScenarioRunner] = []
        self._main_sel = 0
        self._cleaned_up = False

    # ------------------------------------------------------------------ init

    def _optional(self, label: str, factory: Callable[[], object]):
        """Build an optional component; a failure only disables that module."""
        try:
            obj = factory()
            logger.info(f"{label} ready")
            return obj
        except Exception as e:
            logger.warning(f"{label} unavailable: {e}")
            return None

    @staticmethod
    def _cls(module: str, name: str):
        """Lazy import: a missing library (evdev, board...) disables one module, not the app."""
        return getattr(importlib.import_module(module), name)

    def init_system(self):
        logger.info("Initializing ZeroRange...")
        settings = config_section("settings", self.config)

        if self.lcd is None:
            lcd_cls = self._cls("lcd_manager", "LCDManager")
            self.lcd = lcd_cls(address=int(str(settings.get("lcd_address", "0x20")), 16))
            self.ui = UI(self.lcd, self.clock)

        self.ui.show(f"ZeroRange v{VERSION}", "Initializing...")

        if self.registry is None:
            self.registry = discover()
        if self.db is None:
            self.db = Database(str(DB_PATH), catalog=build_catalog(self.registry.scenarios))

        hid_device = settings.get("hid_device")
        self.ibutton = self._optional("iButton", lambda: self._cls(
            "ibutton_handler", "iButtonHandler")(self.lcd, **({"usb_device": hid_device} if hid_device else {})))

        self.proxmark = self._optional("Proxmark3", lambda: self._cls("proxmark_handler", "ProxmarkHandler")())
        if self.proxmark is not None:
            self.nfc = self._optional("NFC", lambda: self._cls("nfc_handler", "NFCHandler")(self.lcd, self.proxmark))
            self.rfid = self._optional("RFID", lambda: self._cls("rfid_handler", "RFIDHandler")(self.lcd, self.proxmark))

        self.hackrf = self._optional("HackRF", lambda: self._cls("hackrf_handler", "HackRFHandler")())
        if self.hackrf is not None:
            self.subghz = self._optional("SubGHZ", lambda: self._cls("subghz_handler", "SubGHZHandler")(self.lcd, self.hackrf))

        self.flirc = self._optional("FLIRC", lambda: self._cls("flirc_handler", "FlircHandler")())
        if self.flirc is not None:
            self.ir = self._optional("IR", lambda: self._cls("ir_handler", "IRHandler")(self.lcd, self.flirc))

        self.scenarios = [
            ScenarioRunner(sc, self.lcd, self.db, proxmark=self.proxmark, hackrf=self.hackrf,
                           sse_emit=EventBus(sc.key), clock=self.clock)
            for sc in self.registry
        ]
        for key, error in self.registry.errors.items():
            logger.error(f"Scenario '{key}' disabled: {error}")

        self.ui.show(f"ZeroRange v{VERSION}", "Ready!", hold=1)
        logger.info(f"Initialization complete. Score: {self.db.get_total_score()}/{self.db.get_max_score()}")

    # ------------------------------------------------------------------ menus

    def menu_entries(self) -> List[MenuEntry]:
        entries = [MenuEntry(m.title, self._module_screen(m)) for m in CLASSIC_MODULES]
        entries += [MenuEntry(r.title, self._scenario_screen(r)) for r in self.scenarios]
        entries.append(MenuEntry("Settings", self.settings_screen))
        return entries

    def home_screen(self) -> Optional[Screen]:
        self.ui.show(f"ZeroRange V{VERSION.split('.')[0]}", get_ip_address())
        self.ui.wait(*Button)
        return self.main_menu

    def main_menu(self) -> Optional[Screen]:
        entries = self.menu_entries()
        max_score = self.db.get_max_score()

        def render(i):
            return score_line(entries[i].title, self.db.get_total_score(), max_score), "U/D SEL=Go L=Bk"

        choice = self.ui.menu(len(entries), render, start=self._main_sel)
        if choice is None:
            return self.home_screen
        self._main_sel = choice
        return entries[choice].open

    def _module_screen(self, module: ClassicModule) -> Screen:
        def screen() -> Optional[Screen]:
            handler = getattr(self, module.handler)
            if handler is None:
                self.ui.notice(*module.unavailable)
                return self.main_menu

            selected = 0
            while True:
                def render(i):
                    ch = module.challenges[i]
                    status = self.db.get_challenge_status(ch.id) or {}
                    mark = " ✓" if status.get("completed") else ""
                    return f">{ch.label}{mark}", "U/D SEL=Go L=Bk"

                choice = self.ui.menu(len(module.challenges), render, start=selected)
                if choice is None:
                    return self.main_menu
                selected = choice
                self.run_classic_challenge(handler, module.challenges[choice])
        return screen

    def run_classic_challenge(self, handler, challenge) -> int:
        """Run one handler method, record the attempt, return points earned."""
        logger.info(f"Starting challenge {challenge.id} ({challenge.label})")
        start = time.time()
        try:
            points = int(getattr(handler, challenge.method)() or 0)
        except Exception as e:
            logger.error(f"Error running challenge {challenge.id}: {e}", exc_info=True)
            return 0
        elapsed = int(time.time() - start)
        self.db.add_history(challenge.id, points > 0, elapsed)
        if points > 0:
            self.db.mark_completed(challenge.id, elapsed)
            logger.info(f"Challenge {challenge.id} completed! "
                        f"Score: {self.db.get_total_score()}/{self.db.get_max_score()}")
        return points

    def _scenario_screen(self, runner: ScenarioRunner) -> Screen:
        def screen() -> Optional[Screen]:
            try:
                runner.run()
            except Exception as e:
                logger.error(f"Error in scenario {runner.key}: {e}", exc_info=True)
            return self.main_menu
        return screen

    # ------------------------------------------------------------------ settings

    def settings_screen(self) -> Optional[Screen]:
        items = [("Statistics", self.stats_screen),
                 ("Reset scores", self.reset_screen),
                 ("About", self.about_screen)]
        choice = self.ui.choose([label for label, _ in items], footer="U/D SEL=Go L=Bk")
        if choice is None:
            return self.main_menu
        return items[choice][1]

    def stats_screen(self) -> Optional[Screen]:
        s = self.db.get_stats()
        self.ui.show(f"Score:{s['total_score']}/{s['max_score']}",
                     f"{s['completed_count']}/{s['total_challenges']} Tries:{s['total_attempts']}")
        self.ui.wait(Button.BACK, timeout=10)
        return self.settings_screen

    def about_screen(self) -> Optional[Screen]:
        self.ui.notice(f"ZeroRange v{VERSION}", "Flipper Train ◄")
        return self.settings_screen

    def reset_screen(self) -> Optional[Screen]:
        if not self.ui.confirm("Reset scores?", "SEL=Yes ◄=No"):
            logger.info("Reset cancelled")
            return self.settings_screen
        logger.info("Resetting all scores...")
        self.db.reset_scores()
        self.ui.show("Scores Reset!", "Progress cleared", hold=2)
        return self.main_menu

    # ------------------------------------------------------------------ loop

    def main_loop(self):
        logger.info("Entering main loop")
        screen: Screen = self.home_screen
        while True:
            try:
                screen = screen() or self.main_menu
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(1)
                screen = self.main_menu

    def cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        logger.info("Cleaning up...")
        for component in [*self.scenarios, self.ibutton, self.subghz, self.ir]:
            if component is not None and hasattr(component, "close"):
                try:
                    component.close()
                except Exception as e:
                    logger.error(f"Error closing {type(component).__name__}: {e}")
        if self.lcd is not None:
            try:
                self.ui.show("  Shutting down", "   Bye bye...", hold=2)
                self.lcd.clear()
                self.lcd.close()
            except Exception as e:
                logger.error(f"Error closing LCD: {e}")
        if self.db is not None:
            self.db.close()

    def run(self):
        try:
            self.init_system()
            self.main_loop()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Stopping on user/system request")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            if self.ui is not None:
                self.ui.show("INIT FAILED!", "Check logs", hold=5)
        finally:
            self.cleanup()


def setup_logging(level: str = "INFO") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        handlers=[logging.FileHandler(LOG_DIR / 'zerorange.log'),
                  logging.StreamHandler(sys.stdout)],
    )


def _raise_exit(signum, _frame):
    logger.info(f"Received signal {signum}, shutting down...")
    raise SystemExit(0)


def main():
    setup_logging(config_section("settings").get("log_level", "INFO"))
    signal.signal(signal.SIGINT, _raise_exit)
    signal.signal(signal.SIGTERM, _raise_exit)
    logger.info("=" * 50)
    logger.info("ZeroRange starting...")
    ZeroRange().run()
    logger.info("ZeroRange stopped")


if __name__ == "__main__":
    main()
