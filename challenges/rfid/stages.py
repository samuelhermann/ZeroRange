"""RFID 125 kHz stages (``self.hw`` = ProxmarkHandler)."""

import logging

from app.core.ui import Button, normalize_hex
from app.scenarios.base import Stage

logger = logging.getLogger(__name__)


class _RfidStage(Stage):
    requires = "proxmark"

    def ready(self) -> bool:
        return self.require_hardware("RFID - No PM3!", "Connect PM3 ◄")

    def scan(self, timeout: int):
        """``lf search`` takes a few seconds per probe."""
        return self.wait_for(self.hw.rfid_scan, timeout=timeout, interval=0.5)

    def solved(self) -> int:
        points = self.award()
        self.ui.show("SOLVED!", f"+{points}pts", hold=2)
        self.finish()
        return points


class Detect(_RfidStage):
    challenge_id = 7
    number = 1
    title = "Ch7:Detect"
    name = "Detect Tag"
    description = "Detect RFID 125kHz"
    hints = (
        "125 kHz tags must be very close to the Proxmark3 LF antenna.",
        "Not detected? Rotate the tag, or emulate one: Flipper 125 kHz RFID > Saved.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("RFID Ch7:Detect", "")
            tag, outcome = self.scan(60)
            if tag:
                self.ui.show(f"Type:{tag.get('type', '?')}", f"ID:{tag.get('id', '?')}", hold=3)
                return self.solved()
            if outcome == "back" or not self.retry("TIMEOUT"):
                return 0


class CloneT5577(_RfidStage):
    challenge_id = 8
    number = 2
    title = "Ch8:Clone"
    name = "Clone to T5577"
    description = "Clone tag to T5577"
    hints = (
        "The T5577 is a writable 125 kHz card that can impersonate EM410x and HID tags.",
        "Flipper: 125 kHz RFID > Saved > tag > Write, with the T5577 on its back.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("Ch8: original", "")
            tag, outcome = self.scan(45)
            if not tag:
                if outcome == "back" or not self.retry("FAILED"):
                    return 0
                continue
            target = normalize_hex(tag.get("id", ""))
            self.ui.show("ID saved!", target, hold=2)

            if not self.ui.confirm("Place a T5577", "SEL=Write ◄=Back"):
                return 0
            self.ui.show("Cloning...", "Please wait...")
            kind = (tag.get("type") or "em410x").split()[0]   # "HID Prox" -> "HID"
            if not self.hw.rfid_clone_to_t5577(tag.get("id", ""), kind):
                if not self.retry("Clone failed"):
                    return 0
                continue

            self.ui.show("Ch8: read clone", "")
            clone, outcome = self.scan(45)
            if clone and normalize_hex(clone.get("id", "")) == target:
                return self.solved()
            if outcome == "back" or not self.retry("WRONG ID" if clone else "TIMEOUT"):
                return 0


class SimulateEM(_RfidStage):
    challenge_id = 9
    number = 3
    title = "Ch9:Simulate"
    name = "Simulate EM410x"
    description = "Simulate EM410x tag"
    hints = (
        "Read an EM410x tag; the PM3 then simulates it — read it back with the Flipper.",
        "Flipper emulation range is short: keep the devices close and steady.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("Ch9: EM410x tag", "")
            tag, outcome = self.scan(60)
            if not tag:
                if outcome == "back" or not self.retry("TIMEOUT"):
                    return 0
                continue
            if tag.get("type", "").lower() != "em410x":
                self.ui.show("Not EM410x!", "Need EM410x", hold=3)
                continue
            tag_id = tag.get("id", "")
            self.ui.show("Simulating...", "Remove the tag", hold=2)
            if not self.hw.rfid_simulate_em410x(tag_id):
                if not self.retry("Sim failed"):
                    return 0
                continue
            btn = self.ui.prompt("Read it w/Flipper", "SEL=Done ◄=Back", Button.SELECT, Button.BACK)
            if btn == Button.SELECT:
                return self.solved()
            return 0
