"""Prep Badges — unscored tool: emulate either reference badge via the PM3 so
a Flipper Zero (or any ISO14443A reader) can read and save it.

SELECT toggles Key B on the LCD, BACK stops the emulation.
"""

from app.scenarios.stages import BadgeEmulatorTool
from challenges.coffee import BADGE_HIGH, BADGE_LOW, DEFAULT_KEY_B


class PrepBadges(BadgeEmulatorTool):
    title = "Prep Badges"
    badges = (
        ("Low  1,50 EUR", "badge_paths.low", BADGE_LOW),
        ("High 50,00 EUR", "badge_paths.high", BADGE_HIGH),
    )
    key_key = "master_key_b_hex"
    default_key = DEFAULT_KEY_B
