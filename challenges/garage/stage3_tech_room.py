"""Stage 3 — Tech Room (Proxmark3 MIFARE Classic, 10 pts).

The PM3 emulates ``tech_room.nfc`` (sector 0 Key A = leaked in Stage 2).
The learner reads sector 0 with that key. Auto-detected from the PM3
emulation log, or confirmed with SELECT (PM3 reads block 0 with Key A).
"""

from app.scenarios.stages import MifareEmulationStage
from challenges.garage import DEFAULT_TECH_KEY_A, TECH_ROOM_BADGE


class Stage3(MifareEmulationStage):
    challenge_id = 21
    number = 3
    title = "Stage3:TechRm"
    name = "Tech Room"
    description = "Read MIFARE with leaked key"

    badge_key = "badge_path"
    default_badge = TECH_ROOM_BADGE
    key_key = "tech_room_key_a_hex"
    default_key = DEFAULT_TECH_KEY_A
    key_type = "A"
    sectors = frozenset({0})
    log_requires_key = False   # sim logs "auth ... block N" without the key

    intro = ("Garage Stage 3", "Tech room. Open!")
    waiting_lines = ("PM3 emulating...", "SEL=Done ◄=Back")
    success_lines = ("Access granted!", "+10pts")
    not_yet_lines = ("Not yet!", "Use Key A first")
