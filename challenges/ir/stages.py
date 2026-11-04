"""Infrared stages (``self.hw`` = FlircHandler)."""

import logging
from typing import Any, Dict, Optional

from app.scenarios.base import Stage

logger = logging.getLogger(__name__)


class _IrStage(Stage):
    requires = "flirc"

    def ready(self) -> bool:
        return self.require_hardware("IR - No FLIRC!", "Connect FLIRC ◄", allow_simulation=True)

    def _probe(self) -> Optional[Dict[str, Any]]:
        received, info = self.hw.receive_ir(timeout=1)
        return info if received and info else None

    def receive(self, timeout: int):
        """``receive_ir`` itself blocks ~1 s, which paces the polling."""
        return self.wait_for(self._probe, timeout=timeout, interval=0.05)

    def solved(self) -> int:
        points = self.award()
        self.ui.show("SOLVED!", f"+{points}pts", hold=2)
        self.finish()
        return points


class Detect(_IrStage):
    challenge_id = 13
    number = 1
    title = "Ch13:Detect"
    name = "Detect IR"
    description = "Detect any IR signal"
    hints = (
        "Point a remote straight at the FLIRC receiver and press any button.",
        "Flipper: Infrared > Universal Remotes > TV > Power works too.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("IR Ch13:Detect", "")
            info, outcome = self.receive(60)
            if info:
                self.ui.show(f"Key:{info.get('keycode', '?')}", f"Proto:{info.get('protocol', '?')}",
                             hold=3)
                return self.solved()
            if outcome == "back" or not self.retry("NO IR SIGNAL"):
                return 0


def same_signal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if a.get("scancode") and a.get("scancode") == b.get("scancode"):
        return True
    return bool(a.get("keycode")) and a.get("keycode") == b.get("keycode")


class Replay(_IrStage):
    challenge_id = 14
    number = 2
    title = "Ch14:Replay"
    name = "Capture & Replay"
    description = "Record and replay IR"
    hints = (
        "Flipper: Infrared > Learn New Remote, press the remote button, save it.",
        "Then send the saved button towards the FLIRC: same remote, same button.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        while True:
            self.ui.show("Ch14 [1/2]", "Press any IR btn", hold=2)
            original, outcome = self.receive(45)
            if not original:
                if outcome == "back" or not self.retry("NO IR SIGNAL"):
                    return 0
                continue
            self.ui.show("Captured!", f"Key:{original.get('keycode', '?')}", hold=2)
            self.ui.show("Ch14 [2/2]", "Send SAME signal", hold=2)
            replay, outcome = self.receive(45)
            if replay and same_signal(original, replay):
                self.ui.show("Signal matched!", "", hold=2)
                return self.solved()
            if replay:
                logger.info("IR mismatch: %s vs %s", original, replay)
            if outcome == "back" or not self.retry("MISMATCH!" if replay else "NO SIGNAL"):
                return 0


class Protocols(_IrStage):
    challenge_id = 15
    number = 3
    title = "Ch15:Protocol"
    name = "Protocol Analysis"
    description = "Identify IR protocol"
    signals_needed = 3
    hints = (
        "Send 3 signals; try different remotes to see different protocols.",
        "Most TVs use NEC; Philips/European remotes often use RC5 or RC6.",
    )

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        self.ui.show("Ch15:Protocol", f"Send {self.signals_needed} signals", hold=2)
        protocols = set()
        received = 0
        while received < self.signals_needed:
            self.ui.show(f"Signal {received + 1}/{self.signals_needed}", "")
            info, outcome = self.receive(40)
            if not info:
                if outcome == "back" or not self.retry("NO SIGNAL"):
                    return 0
                continue
            received += 1
            protocols.add(info.get("protocol") or "Unknown")
            self.ui.show(f"Proto:{info.get('protocol', '?')}", f"Got {len(protocols)} type(s)", hold=2)
        self.ui.show(f"{len(protocols)} protocol(s)", ",".join(sorted(protocols)), hold=2)
        return self.solved()
