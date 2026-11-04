"""Web mirror of the LCD, shared by the real LCDManager and the simulator.

* ``run/lcd_state.json``  — the two lines currently shown (read by web_lcd_server.py)
* ``run/web_button.json`` — a button pressed on the web page (written by web_lcd_server.py)
"""

import json
import os
from pathlib import Path
from typing import Optional, Sequence

from app.core.paths import RUN_DIR

LCD_STATE_FILE = RUN_DIR / "lcd_state.json"
WEB_BUTTON_FILE = RUN_DIR / "web_button.json"


def write_state(lines: Sequence[str], path: Path = LCD_STATE_FILE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"line1": lines[0], "line2": lines[1]}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def clear_web_button(path: Path = WEB_BUTTON_FILE) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def take_web_button(path: Path = WEB_BUTTON_FILE) -> Optional[int]:
    """Pop the pending web button press (1-5), if any."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
    except (OSError, ValueError):
        return None
    btn = data.get("button") if isinstance(data, dict) else None
    return btn if isinstance(btn, int) and 1 <= btn <= 5 else None
