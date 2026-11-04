"""NFC stages (``self.hw`` = ProxmarkHandler)."""

import logging

from app.core.ui import normalize_hex
from app.scenarios.base import Stage

logger = logging.getLogger(__name__)


class _NfcStage(Stage):
    requires = "proxmark"

    def ready(self) -> bool:
        return self.require_hardware("NFC - No PM3!", "Connect PM3 ◄")

    def scan(self, timeout: int):
        """Wait for a card; ``hf 14a reader`` itself takes ~1 s per probe."""
        return self.wait_for(self.hw.nfc_scan, timeout=timeout, interval=0.5)

    def solved(self) -> int:
        points = self.award()
        self.ui.show("SOLVED!", f"+{points}pts", hold=2)
        self.finish()
        return points


class Detect(_NfcStage):
    challenge_id = 4
    number = 1
    title = "Ch4:Detect"
    name = "Detect & Read"
    description = "Detect any NFC card"
    hints = (
        "Place the card flat on the Proxmark3 HF antenna (the big coil).",
        "Not detected? Try another orientation, or use the Flipper: NFC > Emulate.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("NFC Ch4:Detect", "")
            card, outcome = self.scan(60)
            if card:
                self.ui.show(f"Type:{card.get('type', '?')}", f"UID:{card.get('uid', '?')}", hold=3)
                return self.solved()
            if outcome == "back" or not self.retry("TIMEOUT"):
                return 0


class Clone(_NfcStage):
    challenge_id = 5
    number = 2
    title = "Ch5:Clone"
    name = "Clone Card"
    description = "Read and dump NFC"
    hints = (
        "Read the original first; then present a clone with the SAME UID.",
        "Use a Gen1a 'magic' card, or the Flipper: NFC > Saved > card > Emulate.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("Ch5: original", "")
            original, outcome = self.scan(45)
            if not original:
                if outcome == "back" or not self.retry("FAILED"):
                    return 0
                continue
            uid = normalize_hex(original.get("uid", ""))
            self.ui.show("UID saved!", uid, hold=2)
            if "MIFARE Classic" in original.get("type", ""):
                self.ui.show("Dumping data...", "Please wait...")
                dump = self.hw.nfc_dump_mifare()
                self.ui.line(1, f"{len(dump)} blocks OK" if dump else "Dump failed")
                self.ui.sleep(2)

            self.ui.show("Ch5: your clone", "")
            clone, outcome = self.scan(45)
            if clone and normalize_hex(clone.get("uid", "")) == uid:
                return self.solved()
            if outcome == "back" or not self.retry("WRONG CARD" if clone else "TIMEOUT"):
                return 0


class MifareAttack(_NfcStage):
    challenge_id = 6
    number = 3
    title = "Ch6:MIFARE"
    name = "MIFARE Attack"
    description = "Break MIFARE Classic"
    hints = (
        "Start with the default keys: FFFFFFFFFFFF and A0A1A2A3A4A5.",
        "A nested attack needs one known key; the Flipper's dictionary attack finds it.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("Ch6: MIFARE", "")
            card, outcome = self.scan(60)
            if not card:
                if outcome == "back" or not self.retry("TIMEOUT"):
                    return 0
                continue
            if "MIFARE Classic" not in card.get("type", ""):
                self.ui.show("Not MIFARE!", "Need Classic 1K", hold=3)
                continue
            self.ui.show("Dumping keys...", "Please wait...")
            dump = self.hw.nfc_dump_mifare()
            if dump:
                return self.solved()
            if not self.retry("Attack failed"):
                return 0
