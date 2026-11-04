"""A 16x2 LCD drawn in the terminal, driven by the keyboard (and the web LCD).

Keys: arrows or W/A/S/D move, Enter/Space = SELECT, A/Left/Backspace/Esc =
BACK (◄), D/Right = RIGHT (► hints). Ctrl-C quits.

It also writes ``run/lcd_state.json`` and reads ``run/web_button.json`` like
the real LCDManager, so the docs/ web LCD and web_lcd_server.py work too.
"""

import os
import select
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Optional, Tuple

from app.core import lcd_mirror

SELECT, UP, DOWN, RIGHT, BACK = 1, 2, 3, 4, 5
KEY_TTL = 1.0   # a key not consumed within 1 s is dropped (screens poll subsets)

_KEYMAP = {
    "\r": SELECT, "\n": SELECT, " ": SELECT,
    "w": UP, "s": DOWN, "d": RIGHT, "a": BACK,
    "\x7f": BACK, "\x08": BACK, "b": BACK,
    "\x1b[A": UP, "\x1b[B": DOWN, "\x1b[C": RIGHT, "\x1b[D": BACK, "\x1b": BACK,
}

HELP = ("arrows/WASD move · Enter=SELECT · ←/A/Esc=BACK · →/D=hint · Ctrl-C quit\n"
        "inject hardware: python3 tools/sim_inject.py --help  (or the web dashboard)")


class TerminalLCD:
    width, height = 16, 2

    def __init__(self, stream=None, stdin=None, interactive: Optional[bool] = None,
                 mirror_dir: Optional[Path] = None):
        self.out = stream or sys.stdout
        self._state_file = Path(mirror_dir) / "lcd_state.json" if mirror_dir else lcd_mirror.LCD_STATE_FILE
        self._button_file = Path(mirror_dir) / "web_button.json" if mirror_dir else lcd_mirror.WEB_BUTTON_FILE
        self.stdin = stdin or sys.stdin
        self.lines = ["", ""]
        self._keys: Deque[Tuple[int, float]] = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._saved_tty = None
        lcd_mirror.clear_web_button(self._button_file)
        is_tty = hasattr(self.stdin, "isatty") and self.stdin.isatty()
        self.interactive = is_tty if interactive is None else interactive
        if self.interactive:
            self._enter_cbreak()
            threading.Thread(target=self._read_keys, daemon=True).start()
        self._render()

    # -- terminal ----------------------------------------------------------

    def _enter_cbreak(self) -> None:
        try:
            import termios
            import tty
            fd = self.stdin.fileno()
            self._saved_tty = termios.tcgetattr(fd)
            tty.setcbreak(fd)            # keeps Ctrl-C -> SIGINT
        except Exception:
            self._saved_tty = None

    def _restore(self) -> None:
        if self._saved_tty is not None:
            import termios
            termios.tcsetattr(self.stdin.fileno(), termios.TCSADRAIN, self._saved_tty)
            self._saved_tty = None

    def _read_keys(self) -> None:
        fd = self.stdin.fileno()
        while not self._stop.is_set():
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            ch = os.read(fd, 1).decode(errors="ignore")
            if ch == "\x1b":             # arrow keys arrive as ESC [ X
                more, _, _ = select.select([fd], [], [], 0.05)
                if more:
                    ch += os.read(fd, 2).decode(errors="ignore")
            self.press(_KEYMAP.get(ch.lower() if len(ch) == 1 else ch))

    def _render(self) -> None:
        if not self.interactive:
            return
        bar = "─" * (self.width + 2)
        self.out.write("\x1b[H\x1b[2J"
                       f"  ZeroRange --sim\n  ┌{bar}┐\n"
                       f"  │ {self.lines[0]:<16} │\n  │ {self.lines[1]:<16} │\n"
                       f"  └{bar}┘\n\n{HELP}\n")
        self.out.flush()

    # -- input -------------------------------------------------------------

    def press(self, button: Optional[int]) -> None:
        if button:
            with self._lock:
                self._keys.append((button, time.monotonic()))

    def _expire(self) -> None:
        now = time.monotonic()
        while self._keys and now - self._keys[0][1] > KEY_TTL:
            self._keys.popleft()

    # -- LCDManager API ------------------------------------------------------

    def write_line(self, line: int, text: str) -> None:
        if 0 <= line < self.height:
            self.lines[line] = str(text).ljust(self.width)[:self.width]
            lcd_mirror.write_state(self.lines, self._state_file)
            self._render()

    def clear(self) -> None:
        self.lines = ["", ""]
        lcd_mirror.write_state(self.lines, self._state_file)
        self._render()

    def button_pressed(self, button_num: int) -> bool:
        web = lcd_mirror.take_web_button(self._button_file)
        if web:
            self.press(web)
        with self._lock:
            self._expire()
            if self._keys and self._keys[0][0] == button_num:
                self._keys.popleft()
                return True
        return False

    def wait_button_release(self, button_num: int) -> None:
        pass   # key presses are events, not levels

    def close(self) -> None:
        self._stop.set()
        self._restore()
        if self.interactive:
            self.out.write("\n")
            self.out.flush()
