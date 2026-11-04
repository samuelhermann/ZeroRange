"""High-level helpers for the 16x2 LCD + 5-button interface.

Every stage used to re-implement the same loops ("show two lines, sleep",
"wait for SELECT or BACK", "scroll a list with UP/DOWN"...).  They now live
here, once, with two properties the copies did not have:

* every blocking wait **waits for the button release**, so a BACK press can
  no longer leak into the next screen and exit two menus at once;
* time is read through an injectable :class:`Clock`, so tests run instantly.
"""

import logging
import time
from enum import IntEnum
from typing import Callable, Iterable, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

LCD_WIDTH = 16
POLL_INTERVAL = 0.1


class Button(IntEnum):
    """Button numbers as understood by ``LCDManager.button_pressed``."""

    SELECT = 1
    UP = 2
    DOWN = 3
    RIGHT = 4
    BACK = 5  # the LEFT key, labelled "◄" / "L=Bk" on screen


ALL_BUTTONS = tuple(Button)


class Clock:
    """Wall-clock abstraction (monotonic). Tests swap in a fake one."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def normalize_hex(value: str) -> str:
    """Upper-case hex with separators (space, dash, colon) removed."""
    return "".join(ch for ch in str(value) if ch not in " -:_").upper()


def is_hex(value: str) -> bool:
    v = normalize_hex(value)
    return bool(v) and all(c in "0123456789ABCDEF" for c in v)


def hex_spaced(value: str) -> str:
    """``"B4EEC0FFEE11"`` -> ``"B4 EE C0 FF EE 11"``."""
    v = normalize_hex(value)
    return " ".join(v[i:i + 2] for i in range(0, len(v), 2))


def hex_fit(value: str, width: int = LCD_WIDTH) -> str:
    """Hex grouped as readably as fits on one LCD row.

    A 6-byte key spaced per byte is 17 chars and used to lose its last digit:
    ``"B4 EE C0 FF EE 11"`` -> ``"B4EE C0FF EE11"``.
    """
    v = normalize_hex(value)
    for group in (2, 4, 8):
        text = " ".join(v[i:i + group] for i in range(0, len(v), group))
        if len(text) <= width:
            return text
    return v


def eur(cents: int) -> str:
    """Format cents the French way: ``5000`` -> ``"50,00"``."""
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100},{cents % 100:02d}"


def fit(text: str, width: int = LCD_WIDTH) -> str:
    return str(text)[:width]


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class UI:
    """Blocking LCD interaction primitives built on ``lcd.write_line`` /
    ``lcd.button_pressed`` / ``lcd.wait_button_release``."""

    def __init__(self, lcd, clock: Optional[Clock] = None):
        self.lcd = lcd
        self.clock = clock or Clock()

    # -- time -------------------------------------------------------------

    def now(self) -> float:
        return self.clock.now()

    def sleep(self, seconds: float) -> None:
        self.clock.sleep(seconds)

    # -- output -----------------------------------------------------------

    def show(self, line0: str = "", line1: str = "", hold: float = 0.0) -> None:
        """Write both lines (each padded/truncated to 16 chars by the LCD driver)."""
        self.lcd.write_line(0, fit(line0))
        self.lcd.write_line(1, fit(line1))
        if hold:
            self.sleep(hold)

    def line(self, row: int, text: str) -> None:
        self.lcd.write_line(row, fit(text))

    def slides(self, title: str, lines: Iterable[str], hold: float = 1.5,
               skippable: bool = False) -> bool:
        """Show *title* on row 0 and each of *lines* in turn on row 1.

        With ``skippable=True`` any of SELECT/BACK ends the sequence early.
        Returns False if the user skipped.
        """
        for text in lines:
            self.show(title, text)
            if skippable:
                if self.wait(Button.SELECT, Button.BACK, timeout=hold) is not None:
                    return False
            else:
                self.sleep(hold)
        return True

    # -- input ------------------------------------------------------------

    def poll(self, *buttons: Button) -> Optional[Button]:
        """Non-blocking: return the first of *buttons* currently pressed (and
        wait for its release), or None."""
        for btn in buttons or ALL_BUTTONS:
            if self.lcd.button_pressed(int(btn)):
                self.lcd.wait_button_release(int(btn))
                return Button(btn)
        return None

    def wait(self, *buttons: Button, timeout: Optional[float] = None,
             on_tick: Optional[Callable[[float], None]] = None) -> Optional[Button]:
        """Block until one of *buttons* is pressed or *timeout* elapses (-> None).

        ``on_tick(remaining_seconds)`` is called on every poll when a timeout is set.
        """
        start = self.now()
        while True:
            btn = self.poll(*buttons)
            if btn is not None:
                return btn
            if timeout is not None:
                remaining = timeout - (self.now() - start)
                if remaining <= 0:
                    return None
                if on_tick:
                    on_tick(remaining)
            self.sleep(POLL_INTERVAL)

    def wait_back(self) -> None:
        self.wait(Button.BACK)

    def prompt(self, line0: str, line1: str, *buttons: Button,
               timeout: Optional[float] = None) -> Optional[Button]:
        self.show(line0, line1)
        return self.wait(*buttons, timeout=timeout)

    def confirm(self, line0: str, line1: str = "SEL=Yes ◄=Back") -> bool:
        """SELECT -> True, BACK -> False."""
        return self.prompt(line0, line1, Button.SELECT, Button.BACK) == Button.SELECT

    def notice(self, line0: str, line1: str = "◄=Back") -> None:
        """Show a message and block until BACK."""
        self.show(line0, line1)
        self.wait_back()

    def menu(self, count: int, render: Callable[[int], Tuple[str, str]],
             start: int = 0) -> Optional[int]:
        """Scrollable list. ``render(index) -> (line0, line1)``.

        The screen is only redrawn when the selection changes (no I2C flicker,
        no DB query every 100 ms).  Returns the index on SELECT, None on BACK.
        """
        if count <= 0:
            self.wait_back()
            return None
        selected = start % count
        dirty = True
        while True:
            if dirty:
                self.show(*render(selected))
                dirty = False
            btn = self.poll(Button.UP, Button.DOWN, Button.SELECT, Button.BACK)
            if btn == Button.UP:
                selected = (selected - 1) % count
                dirty = True
            elif btn == Button.DOWN:
                selected = (selected + 1) % count
                dirty = True
            elif btn == Button.SELECT:
                return selected
            elif btn == Button.BACK:
                return None
            else:
                self.sleep(POLL_INTERVAL)

    def choose(self, labels: Sequence[str], footer: str = "U/D SEL=Go ◄=Bk",
               start: int = 0) -> Optional[int]:
        """Convenience wrapper around :meth:`menu` for a plain list of labels."""
        return self.menu(len(labels), lambda i: (f">{labels[i]}", footer), start)
