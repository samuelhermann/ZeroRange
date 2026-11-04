"""Sub-GHz stages (``self.hw`` = HackRFHandler)."""

import logging
import os
from typing import Any, Dict, Optional

from app.scenarios.base import Stage

logger = logging.getLogger(__name__)

DEFAULT_FREQ = 433_920_000
DEFAULT_THRESHOLD_DBM = -55


class _SubGhzStage(Stage):
    requires = "hackrf"
    config_keys = ("frequency_hz", "threshold_dbm")

    @classmethod
    def defaults(cls):
        return {"frequency_hz": DEFAULT_FREQ, "threshold_dbm": DEFAULT_THRESHOLD_DBM}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.capture_path: Optional[str] = None

    def ready(self) -> bool:
        return self.require_hardware("SubGHz-No HackRF", "Connect HackRF ◄", allow_simulation=True)

    @property
    def frequency(self) -> int:
        return int(self.cfg_get("frequency_hz", DEFAULT_FREQ))

    def _probe(self) -> Optional[Dict[str, Any]]:
        ok, path, info = self.hw.capture_signal(duration_seconds=1.0, frequency=self.frequency)
        threshold = float(self.cfg_get("threshold_dbm", DEFAULT_THRESHOLD_DBM))
        if ok and info.get("detected") and info.get("signal_strength", -100) > threshold:
            self._discard()
            self.capture_path = path
            return info
        if path and os.path.exists(path):
            os.remove(path)
        return None

    def _discard(self) -> None:
        if self.capture_path and os.path.exists(self.capture_path):
            os.remove(self.capture_path)
        self.capture_path = None

    def listen(self, timeout: int):
        self.ui.show(f"Scan {self.frequency / 1e6:.2f}MHz", "")
        return self.wait_for(self._probe, timeout=timeout, interval=0.3)

    def solved(self) -> int:
        points = self.award()
        self.ui.show("SOLVED!", f"+{points}pts", hold=2)
        self.finish()
        return points

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.ready():
            return 0
        self.start_timer()
        try:
            return self.play()
        finally:
            self._discard()

    def play(self) -> int:  # pragma: no cover - abstract
        raise NotImplementedError


class Detect(_SubGhzStage):
    challenge_id = 10
    number = 1
    title = "Ch10:Detect"
    name = "Detect Signal"
    description = "Capture RF signal"
    hints = (
        "Transmit at 433.92 MHz: Flipper Sub-GHz > Saved > a remote > Send.",
        "Get close to the HackRF antenna; a simple OOK remote works best.",
    )

    def play(self) -> int:
        while True:
            info, outcome = self.listen(60)
            if info:
                self.ui.show(f"Signal:{info.get('signal_strength')}dBm",
                             f"Freq:{info.get('frequency', self.frequency) / 1e6:.2f}MHz", hold=3)
                return self.solved()
            if outcome == "back" or not self.retry("NO SIGNAL"):
                return 0


class Replay(_SubGhzStage):
    challenge_id = 11
    number = 2
    title = "Ch11:Replay"
    name = "Record & Replay"
    description = "Capture and replay"
    hints = (
        "Press your remote once: ZeroRange records it, then replays it 3 times.",
        "Capture it on the Flipper too (Read RAW) and compare the two recordings.",
    )

    def play(self) -> int:
        while True:
            self.ui.show("Ch11 [1/2]", "Press TX button", hold=2)
            info, outcome = self.listen(45)
            if not info:
                if outcome == "back" or not self.retry("NO SIGNAL"):
                    return 0
                continue
            self.ui.show("Signal captured!", f"{info.get('signal_strength')}dBm", hold=2)
            self.ui.show("Ch11 [2/2]", "Replaying x3...")
            if self.hw.replay_signal(self.capture_path, repeat=3):
                self.ui.show("Signal replayed!", "", hold=2)
                return self.solved()
            if not self.retry("REPLAY FAILED"):
                return 0


class Analyze(_SubGhzStage):
    challenge_id = 12
    number = 3
    title = "Ch12:Analyze"
    name = "Signal Analysis"
    description = "Analyze RF protocol"
    hints = (
        "Look at the signal in the Flipper: Sub-GHz > Read RAW, or Frequency Analyzer.",
        "Common 433 MHz protocols: Princeton, CAME, Nice FLO (all OOK).",
    )

    def play(self) -> int:
        while True:
            self.ui.show("Ch12:Analyze", "Send RF signal", hold=2)
            info, outcome = self.listen(60)
            if not info:
                if outcome == "back" or not self.retry("NO SIGNAL"):
                    return 0
                continue
            self.ui.show("Analyzing...", "Please wait...")
            analysis = self.hw.analyze_signal(self.capture_path)
            if analysis.get("error"):
                if not self.retry("ANALYSIS FAILED"):
                    return 0
                continue
            self.ui.show(f"Proto:{analysis.get('protocol', 'Unknown')}",
                         f"Mod:{analysis.get('modulation', 'Unknown')}", hold=3)
            return self.solved()
