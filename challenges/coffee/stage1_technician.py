"""Stage 1 — Technician Token (iButton, 10 pts).

The learner touches the maintenance iButton to the USB HID reader.
On success the LCD "leaks" Key B for sectors 8-14 (needed in Stages 2 and 3).
"""

from app.core.ui import hex_fit
from app.scenarios.stages import IButtonMatchStage
from challenges.coffee import DEFAULT_KEY_B, DEFAULT_TECHNICIAN_UID


class Stage1(IButtonMatchStage):
    challenge_id = 16
    number = 1
    title = "Stage1:iButton"
    name = "Technician Token"
    description = "Read maintenance iButton"

    uid_key = "technician_uid"
    default_uid = DEFAULT_TECHNICIAN_UID
    max_wrong_key = "max_wrong_reads_stage1"

    intro = ("Coffee Stage 1", "Pull maint token")
    prompt = "Touch iBtn token"
    noun = "token"
    streak_hint = "Check the token"
    success_lines = ("Token OK! +{points}pts", "Stage 1 SOLVED")
    hints = (
        "Technicians open the machine with an iButton token. Find it and touch the reader.",
        "No token? A Flipper can emulate one it has read: iButton > Saved > Emulate.",
    )

    def reveal(self) -> None:
        raw = self.cfg_hex("master_key_b_hex", DEFAULT_KEY_B)
        key = hex_fit(raw)
        self.ui.show("Leaked log: KeyB", key, hold=4)
        self.ui.show("Sectors 8-14:", key, hold=3)
        self.emit(event="key_leaked", stage=self.number, key_b_hex=raw)
