"""Map Unicode text to what an HD44780 (ROM A00) 16x2 LCD can actually show.

Menus use "✓", "◄", "→"... which the controller cannot render: ``ord("✓")``
is far above 255 and comes out as garbage.  We register a few custom glyphs in
CGRAM slots 1-3 and substitute the rest with ROM equivalents or ASCII.
The web mirror keeps the original Unicode text.
"""

import unicodedata
from typing import Dict, List, Tuple

#: char -> (CGRAM slot, 5x8 bitmap). Slot 0 is avoided ("\x00" is fragile).
CUSTOM_GLYPHS: Dict[str, Tuple[int, List[int]]] = {
    "✓": (1, [0x00, 0x01, 0x03, 0x16, 0x1C, 0x08, 0x00, 0x00]),
    "◄": (2, [0x02, 0x06, 0x0E, 0x1E, 0x0E, 0x06, 0x02, 0x00]),
    "►": (3, [0x08, 0x0C, 0x0E, 0x0F, 0x0E, 0x0C, 0x08, 0x00]),
}

ROM_SUBSTITUTES: Dict[str, str] = {
    "→": "\x7e", "←": "\x7f",
    "✔": "\x01", "◀": "\x02", "▶": "\x03",
    "—": "-", "–": "-", "…": "...", "’": "'", "°": "\xdf",
    "\x07": "\x01",  # legacy checkmark code used by older scenario menus
}


def to_lcd(text: str) -> str:
    out = []
    for ch in text:
        if ch in CUSTOM_GLYPHS:
            out.append(chr(CUSTOM_GLYPHS[ch][0]))
        elif ch in ROM_SUBSTITUTES:
            out.append(ROM_SUBSTITUTES[ch])
        elif " " <= ch <= "~" or ch in "\x01\x02\x03":
            out.append(ch)
        else:
            base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append(base or "?")
    return "".join(out)
