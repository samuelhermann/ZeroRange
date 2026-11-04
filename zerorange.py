#!/usr/bin/env python3
"""
ZeroRange - Flipper Zero Training System
Main application: screen-based state machine on a 16x2 LCD + 5 buttons.

Every module (iButton, NFC, RFID, SubGHZ, IR, Coffee, Garage, ...) is a
scenario auto-discovered in challenges/*/scenario.py.

    python3 zerorange.py          # on the Raspberry Pi
    python3 zerorange.py --sim    # anywhere: terminal LCD + simulated hardware
"""

import argparse
import importlib
import logging
import signal
import socket
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from app.catalog import build_catalog
from app.core.auth import TRAINER_USER, get_trainer_password
from app.core.config import config_section, load_config
from app.core.events import EventBus
from app.core.paths import DB_PATH, LOG_DIR, SIM_DB_PATH
from app.core.session import load_session, new_session
from app.core.ui import UI, Button
from app.scenarios.registry import Registry, discover
from app.scenarios.runner import ScenarioRunner
from database import Database

logger = logging.getLogger("zerorange")

VERSION = "1.2"

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

    def __init__(self, lcd=None, db=None, registry: Optional[Registry] = None, clock=None,
                 devices: Optional[Dict[str, object]] = None, db_path=None, events_dir=None):
        self.lcd = lcd
        self.db = db
        self.db_path = db_path or DB_PATH
        self.events_dir = events_dir
        self.registry = registry
        self.clock = clock
        self.ui: Optional[UI] = UI(lcd, clock) if lcd is not None else None
        self.config = load_config()
        #: Shared hardware: "proxmark", "hackrf", "flirc" (None = not available).
        #: The iButton HID reader is opened by each scenario that needs it.
        self.devices: Dict[str, object] = dict(devices or {})
        self.scenarios: List[ScenarioRunner] = []
        self._main_sel = 0
        self._cleaned_up = False

    # ------------------------------------------------------------------ init

    @staticmethod
    def _optional(label: str, factory: Callable[[], object]):
        """Build an optional component; a failure only disables what needs it."""
        try:
            obj = factory()
            logger.info(f"{label} ready")
            return obj
        except Exception as e:
            logger.warning(f"{label} unavailable: {e}")
            return None

    @staticmethod
    def _cls(module: str, name: str):
        """Lazy import: a missing library (board, evdev...) only disables one device."""
        return getattr(importlib.import_module(module), name)

    def _init_devices(self) -> None:
        defaults = {
            "proxmark": lambda: self._cls("proxmark_handler", "ProxmarkHandler")(),
            "hackrf": lambda: self._cls("hackrf_handler", "HackRFHandler")(),
            "flirc": lambda: self._cls("flirc_handler", "FlircHandler")(),
        }
        for name, factory in defaults.items():
            if name not in self.devices:
                self.devices[name] = self._optional(name, factory)

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
            self.db = Database(str(self.db_path), catalog=build_catalog(self.registry.scenarios))
        self._init_devices()

        self.scenarios = [
            ScenarioRunner(sc, self.lcd, self.db,
                           proxmark=self.devices.get("proxmark"),
                           hackrf=self.devices.get("hackrf"),
                           flirc=self.devices.get("flirc"),
                           hid_factory=self.devices.get("hid_factory"),
                           sse_emit=EventBus(sc.key, self.events_dir), clock=self.clock)
            for sc in self.registry
        ]
        for key, error in self.registry.errors.items():
            logger.error(f"Scenario '{key}' disabled: {error}")

        self.ui.show(f"ZeroRange v{VERSION}", "Ready!", hold=1)
        logger.info(f"Initialization complete. Player: {self.db.get_active_player()['name']}, "
                    f"score {self.db.get_total_score()}/{self.db.get_max_score()}")

    # ------------------------------------------------------------------ menus

    def menu_entries(self) -> List[MenuEntry]:
        entries = [MenuEntry(r.title, self._scenario_screen(r)) for r in self.scenarios]
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

    def _scenario_screen(self, runner: ScenarioRunner) -> Screen:
        def screen() -> Optional[Screen]:
            try:
                runner.run()
            except Exception as e:
                logger.error(f"Error in scenario {runner.key}: {e}", exc_info=True)
            return self.main_menu
        return screen

    # ------------------------------------------------------------------ settings

    def settings_items(self):
        player = self.db.get_active_player()["name"]
        return [
            (f"Player:{player}", self.player_screen),
            ("Statistics", self.stats_screen),
            ("Leaderboard", self.leaderboard_screen),
            ("New session", self.session_screen),
            ("Reset scores", self.reset_screen),
            ("Web login", self.web_login_screen),
            ("About", self.about_screen),
        ]

    def settings_screen(self) -> Optional[Screen]:
        items = self.settings_items()
        choice = self.ui.choose([label[:15] for label, _ in items], footer="U/D SEL=Go L=Bk")
        if choice is None:
            return self.main_menu
        return items[choice][1]

    def player_screen(self) -> Optional[Screen]:
        players = self.db.list_players()
        active = self.db.active_player_id
        labels = [f"{'*' if p['id'] == active else ' '}{p['name'][:10]} {p['score']}" for p in players]
        labels.append("+ New player")
        start = next((i for i, p in enumerate(players) if p["id"] == active), 0)
        choice = self.ui.choose(labels, footer="SEL=Use ◄=Back", start=start)
        if choice is None:
            return self.settings_screen
        if choice == len(players):
            pid = self.db.add_player()
            self.db.set_active_player(pid)
            self.ui.show("New player:", self.db.get_active_player()["name"], hold=2)
            self.ui.show("Rename it on the", "web dashboard", hold=2)
        else:
            self.db.set_active_player(players[choice]["id"])
            self.ui.show("Now playing:", players[choice]["name"], hold=1.5)
        return self.main_menu

    def stats_screen(self) -> Optional[Screen]:
        s = self.db.get_stats()
        self.ui.show(f"Score:{s['total_score']}/{s['max_score']}",
                     f"{s['completed_count']}/{s['total_challenges']} Tries:{s['total_attempts']}")
        self.ui.wait(Button.BACK, timeout=10)
        return self.settings_screen

    def leaderboard_screen(self) -> Optional[Screen]:
        board = self.db.leaderboard()
        self.ui.choose([f"{r['rank']}.{r['name'][:9]} {r['score']}" for r in board],
                       footer="Leaderboard ◄=Bk")
        return self.settings_screen

    def session_screen(self) -> Optional[Screen]:
        current = load_session().get("id", "none")
        self.ui.show("Session:", current[-16:], hold=2)
        if not self.ui.confirm("New secrets?", "SEL=Yes ◄=No"):
            return self.settings_screen
        self.ui.show("Generating...", "keys & badges")
        session = new_session(self.registry.scenarios)
        self.ui.show("Session ready:", session["id"][-16:], hold=2)
        if self.ui.confirm("Reset ALL scores", "too? SEL=Y ◄=N"):
            for player in self.db.list_players():
                self.db.reset_scores(player["id"])
            self.ui.show("All scores reset", "", hold=1.5)
        return self.main_menu

    def web_login_screen(self) -> Optional[Screen]:
        self.ui.show(f"user: {TRAINER_USER}", f"pass: {get_trainer_password(self.config)}")
        self.ui.wait(Button.BACK, timeout=30)
        return self.settings_screen

    def about_screen(self) -> Optional[Screen]:
        self.ui.notice(f"ZeroRange v{VERSION}", "Flipper Train ◄")
        return self.settings_screen

    def reset_screen(self) -> Optional[Screen]:
        player = self.db.get_active_player()["name"]
        if not self.ui.confirm(f"Reset {player[:9]}?", "SEL=Yes ◄=No"):
            logger.info("Reset cancelled")
            return self.settings_screen
        self.db.reset_scores()
        self.ui.show("Scores Reset!", player[:16], hold=2)
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
        for runner in self.scenarios:
            runner.close()
        for name in ("hackrf", "flirc"):
            device = self.devices.get(name)
            if device is not None and hasattr(device, "cleanup"):
                try:
                    device.cleanup()
                except Exception as e:
                    logger.error(f"Error closing {name}: {e}")
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


def setup_logging(level: str = "INFO", to_stdout: bool = True) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers: List[logging.Handler] = [logging.FileHandler(LOG_DIR / 'zerorange.log')]
    if to_stdout:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        handlers=handlers,
    )


def _raise_exit(signum, _frame):
    logger.info(f"Received signal {signum}, shutting down...")
    raise SystemExit(0)


def main(argv=None):
    parser = argparse.ArgumentParser(description="ZeroRange - Flipper Zero training system")
    parser.add_argument("--sim", action="store_true",
                        help="run without hardware: terminal LCD + simulated devices "
                             "(drive them with tools/sim_inject.py or the web dashboard)")
    args = parser.parse_args(argv)

    # In --sim mode the terminal is the LCD: keep logs in logs/zerorange.log only.
    setup_logging(config_section("settings").get("log_level", "INFO"), to_stdout=not args.sim)
    signal.signal(signal.SIGINT, _raise_exit)
    signal.signal(signal.SIGTERM, _raise_exit)
    logger.info("=" * 50)
    logger.info("ZeroRange starting%s...", " in SIMULATION mode" if args.sim else "")

    if args.sim:
        from app.sim import build_sim_environment
        env = build_sim_environment()
        app = ZeroRange(lcd=env.lcd, devices=env.devices, db_path=SIM_DB_PATH)
        try:
            app.run()
        finally:
            env.close()
    else:
        ZeroRange().run()
    logger.info("ZeroRange stopped")


if __name__ == "__main__":
    main()
