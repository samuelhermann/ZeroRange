"""Stage 2 — Crack & Dump the Employee Badge (PM3 emulation, 10 pts).

The Proxmark3 emulates ``credit_low.nfc`` while the learner reads it with a
Flipper Zero. Passes when sectors 8-14 have been authenticated with Key B
(auto-detected from the ``hf mf sim`` log) or on SELECT after the PM3 itself
verifies every sector is readable with Key B.
"""

from app.scenarios.stages import MifareEmulationStage
from challenges.coffee import BADGE_LOW, DEFAULT_KEY_B


class Stage2(MifareEmulationStage):
    challenge_id = 17
    number = 2
    title = "Stage2:Crack"
    name = "Crack & Dump"
    description = "Dump badge via PM3 emulation"

    badge_key = "badge_paths.low"
    default_badge = BADGE_LOW
    key_key = "master_key_b_hex"
    default_key = DEFAULT_KEY_B
    key_type = "B"
    sectors = frozenset(range(8, 15))
    log_requires_key = True

    intro = ("Coffee Stage 2", "Dump the badge")
    instructions = (
        ("PM3 emulates", "badge. Read it!"),
        ("Use Flipper Zero", "Add KeyB to dict"),
    )
    waiting_lines = ("Sectors", "SEL=Done ◄=Back")
    success_lines = ("ALL SECTORS READ", "+10pts Stage 2!")
    not_yet_lines = ("Not all sectors", "readable w/ KeyB")
