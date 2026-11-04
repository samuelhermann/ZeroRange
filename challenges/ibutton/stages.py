"""iButton stages, read through the USB HID reader (``self.hw`` = HIDReader)."""

import logging

from app.core.ui import hex_fit, normalize_hex
from app.scenarios.base import Stage

logger = logging.getLogger(__name__)


def reader_order(uid: str) -> str:
    """The USB reader reports the 6 serial bytes reversed:
    ``01 CA FE 11 11 11 11 D4`` (as programmed) -> ``01 11 11 11 11 FE CA D4``."""
    v = normalize_hex(uid)
    if len(v) != 16:
        return v
    serial = [v[i:i + 2] for i in range(2, 14, 2)]
    return v[:2] + "".join(reversed(serial)) + v[14:]


class _IButtonStage(Stage):
    requires = "hid"

    def ready(self) -> bool:
        return self.require_hardware("iBtn reader N/A", "Connect reader ◄")

    def read(self, timeout: int):
        self.hw.clear()
        return self.wait_for(self.hw.take_uid, timeout=timeout)

    def solved(self) -> int:
        points = self.award()
        self.ui.show("SOLVED!", f"+{points}pts", hold=2)
        self.finish()
        return points


class TouchRead(_IButtonStage):
    challenge_id = 1
    number = 1
    title = "Ch1:Touch"
    name = "Touch & Read"
    description = "Detect any iButton"
    hints = (
        "Flipper: iButton > Read, then touch the reader with the Flipper's iButton pins.",
        "Make good contact with the probe and hold it steady for 1-2 seconds.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("Ch1:Touch iBtn", "")
            uid, outcome = self.read(60)
            if uid:
                self.ui.show("iButton read:", hex_fit(uid), hold=2)
                return self.solved()
            if outcome == "back" or not self.retry("TIMEOUT"):
                return 0


class Clone(_IButtonStage):
    challenge_id = 2
    number = 2
    title = "Ch2:Clone"
    name = "Clone iButton"
    description = "Read then emulate"
    hints = (
        "Step 1: read the original key with the Flipper (iButton > Read) and save it.",
        "Step 2: iButton > Saved > your key > Emulate, then touch the reader.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("Ch2: original", "")
            original, outcome = self.read(45)
            if not original:
                if outcome == "back" or not self.retry("FAILED"):
                    return 0
                continue
            self.ui.show("ID saved!", hex_fit(original), hold=2)
            self.ui.show("Now emulate it", "with the Flipper", hold=2)

            self.ui.show("Ch2: clone", "")
            clone, outcome = self.read(45)
            if clone and normalize_hex(clone) == normalize_hex(original):
                return self.solved()
            if clone:
                logger.info("Clone mismatch: %s vs %s", clone, original)
            if outcome == "back" or not self.retry("WRONG ID" if clone else "TIMEOUT"):
                return 0


class EmulateTarget(_IButtonStage):
    challenge_id = 3
    number = 3
    title = "Ch3:Emulate"
    name = "Emulate Specific"
    description = "Create custom ID"
    config_keys = ("ch3_target_uid",)
    hints = (
        "Flipper: iButton > Add Manually > Dallas DS1990, type the 8 bytes shown.",
        "Check the byte order: type the ID exactly as displayed, left to right.",
    )

    @classmethod
    def defaults(cls):
        return {"ch3_target_uid": "01CAFE11111111D4"}

    def target(self) -> str:
        return self.cfg_hex("ch3_target_uid", "01CAFE11111111D4")

    def accepts(self, uid: str) -> bool:
        v = normalize_hex(uid)
        return v in (self.target(), reader_order(self.target()))

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        target = self.target()
        while True:
            self.ui.show(target, "")       # exactly 16 hex chars on row 0
            uid, outcome = self.read(120)
            if uid and self.accepts(uid):
                return self.solved()
            if uid:
                logger.info("Ch3 wrong ID %s (target %s)", uid, target)
                self.ui.line(1, "Wrong, retry...")
                self.ui.sleep(1)
                continue
            if outcome == "back" or not self.retry("TIMEOUT"):
                return 0
