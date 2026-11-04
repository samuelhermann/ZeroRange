"""Stage 2 — Pedestrian Gate (iButton, 10 pts).

The learner touches the configured DS1990 iButton to the USB HID reader.
On success the tech-room Key A is "leaked" as a post-it on the LCD and web
companion (needed in Stage 3).
"""

from app.core.ui import hex_fit
from app.scenarios.stages import IButtonMatchStage
from challenges.garage import DEFAULT_TECH_KEY_A


class Stage2(IButtonMatchStage):
    challenge_id = 20
    number = 2
    title = "Stage2:Gate"
    name = "Pedestrian Gate"
    description = "Clone iButton fob"

    uid_key = "pedestrian_uid"      # no default: each kit uses its own fob
    max_wrong_key = "max_wrong_reads_stage2"

    intro = ("Garage Stage 2", "Side gate. Fob?")
    prompt = "Touch iBtn fob"
    noun = "fob"
    streak_hint = "Try another fob"
    success_lines = ("Gate unlocked!", "+{points}pts")
    hints = (
        "The side gate trusts one DS1990 fob: borrow a staff fob and read it.",
        "Flipper: iButton > Read the fob, then Saved > Emulate on the reader.",
    )

    def reveal(self) -> None:
        raw = self.cfg_hex("tech_room_key_a_hex", DEFAULT_TECH_KEY_A)
        key = hex_fit(raw)
        self.ui.show("Post-it on door:", key, hold=4)
        self.ui.show("Tech room Key A:", key, hold=3)
        self.emit(event="key_leaked", stage=self.number, key_a_hex=raw)
