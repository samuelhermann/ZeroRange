"""Stage 1 — Rolling-Code Teardown (10 pts, awarded once both parts are done).

Part 1a — replay fails:
  ZeroRange TXes press N, the receiver accepts it and moves on. A replay of
  press N is then rejected (stale counter). The learner confirms with SELECT.

Part 1b — RollJam:
  The receiver is "jammed". ZeroRange TXes press N+1 and N+2 (the learner can
  capture both with a Flipper). Jamming is lifted, press N+1 is replayed and
  accepted -> "Gate OPEN" -> stage solved.

1a is worth 3 partial points (stored); the stage is solved after 1b (10 pts
in total). A learner who already did 1a can jump straight to 1b.
"""

import logging
import os
import tempfile

from app.scenarios.base import Stage
from challenges.garage.receiver_state import ReceiverState
from challenges.garage.rolling_scheme import encode_frame, frame_to_ook_timings

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 2_000_000


def _parse_hex(value: str, default: str) -> bytes:
    return bytes.fromhex((value or default).replace(" ", ""))


class Stage1(Stage):
    challenge_id = 19
    number = 1
    title = "Stage1:RollJam"
    name = "Rolling Code"
    description = "RollJam garage remote"
    requires = "hackrf"
    config_keys = ("rolling.device_id_hex", "rolling.seed_hex")
    part_1a_points = 3
    hints = (
        "A rolling code changes on every press: a replay of an old press is refused.",
        "RollJam: jam the receiver, keep press 1, capture press 2, then replay press 1.",
    )

    @classmethod
    def defaults(cls):
        return {"rolling.device_id_hex": "DEADBEEF", "rolling.seed_hex": "C0FFEE11"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        rolling = self.cfg.get("rolling", {})
        self._device_id = _parse_hex(rolling.get("device_id_hex"), "DEADBEEF")
        self._seed = _parse_hex(rolling.get("seed_hex"), "C0FFEE11")
        self._freq = int(rolling.get("freq_hz", 433_920_000))
        self._gap = int(rolling.get("press_gap_ms", 1500)) / 1000
        self._window = int(rolling.get("counter_window", 16))
        self._initial_counter = int(rolling.get("initial_counter", 100))

    # ------------------------------------------------------------------ radio

    def _frame(self, counter: int) -> bytes:
        return encode_frame(self._device_id, counter, self._seed)

    def _tx_frame(self, counter: int, label: str) -> bool:
        """TX one OOK frame via the HackRF (or simulate it). Returns success."""
        self.ui.show(f"Emitting {label}", f"ctr={counter}")
        self.emit(event="press_emitted", counter=counter)

        if getattr(self.hw, "simulation_mode", False):
            logger.info("[SIM] TX press counter=%s", counter)
            self.ui.sleep(0.5)
            return True

        # Crude OOK -> 8-bit IQ: ON = 127+127j, OFF = 0
        iq = bytearray()
        for t in frame_to_ook_timings(self._frame(counter)):
            n = max(1, abs(t) * _SAMPLE_RATE // 1_000_000)
            iq += (b"\x7f\x7f" if t > 0 else b"\x00\x00") * n

        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tf:
            tf.write(iq)
            path = tf.name
        try:
            return bool(self.hw.replay_signal(path, frequency=self._freq))
        finally:
            os.unlink(path)

    # ------------------------------------------------------------------ parts

    def _run_1a(self, receiver: ReceiverState) -> bool:
        press_n = self._initial_counter
        self.ui.show("Stage 1a: Replay", "Watching...", hold=1)

        if not self._tx_frame(press_n, "press N"):
            if not self.ui.confirm("HackRF TX fail!", "SEL=Skip ◄=Back"):
                return False
        self.ui.sleep(self._gap)

        accepted, reason = receiver.submit_frame(self._frame(press_n))
        if not accepted:
            logger.error("Fresh receiver rejected press N (%s) - check rolling config", reason)
            self.ui.notice("Receiver error", f"{reason} ◄")
            return False

        self.ui.show("Replay press N", "Will it work?...", hold=1)
        self._tx_frame(press_n, "REPLAY N")
        self.ui.sleep(0.5)
        replay_ok, _ = receiver.submit_frame(self._frame(press_n))
        if replay_ok:
            self.ui.show("Accepted! (bug?)", "", hold=2)
        else:
            self.ui.show("Replay rejected", "Counter moved on", hold=2)

        if not self.ui.confirm("Got REJECTED?", "SEL=Yes ◄=Back"):
            return False

        self.award_partial(self.part_1a_points, "1a")
        self.ui.show("Rolling code!", f"+{self.part_1a_points}pts, next: 1b", hold=2)
        return True

    def _skip_1a(self, receiver: ReceiverState) -> None:
        """1a already credited: bring the receiver to the state 1a leaves it in."""
        receiver.submit_frame(self._frame(self._initial_counter))

    def _run_1b(self, receiver: ReceiverState) -> bool:
        press_n1 = self._initial_counter + 1
        press_n2 = self._initial_counter + 2

        self.ui.slides("1b: RollJam", ["RollJam principle", "Jam+capture x2,", "replay 1st press"])

        receiver.set_jammed(True)
        self.ui.show("JAMMING active", "Capturing...", hold=1)

        self._tx_frame(press_n1, "press N+1")
        self.emit(event="frame_held", counter=press_n1, tray_size=1)
        self.ui.sleep(self._gap)

        self._tx_frame(press_n2, "press N+2")
        self.emit(event="frame_held", counter=press_n2, tray_size=2)
        self.ui.sleep(self._gap)

        receiver.set_jammed(False)
        self.ui.show("Jam lifted!", "Replaying N+1...", hold=1)

        self._tx_frame(press_n1, "REPLAY N+1")
        self.ui.sleep(0.5)
        accepted, reason = receiver.submit_frame(self._frame(press_n1))
        if not accepted:
            self.ui.show("Replay failed!", f"Reason: {reason}", hold=3)
            return False
        self.ui.show("Gate OPEN!", "RollJam success!", hold=3)
        return True

    # ------------------------------------------------------------------ flow

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0

        self.ui.slides("Garage Stage 1", ["RollJam demo", "Garage door", "433 MHz OOK"], hold=1.2)

        if not self.require_hardware("HackRF not found", "Connect HackRF ◄", allow_simulation=True):
            return 0

        self.start_timer()
        receiver = ReceiverState(
            device_id=self._device_id,
            seed=self._seed,
            initial_counter=self._initial_counter - 1,
            window=self._window,
            on_event=self.emit,
        )

        if self.earned() >= self.part_1a_points and \
                self.ui.confirm("1a already done", "SEL=Go 1b ◄=Redo"):
            self._skip_1a(receiver)
        else:
            if not self._run_1a(receiver):
                return 0
            if not self.ui.confirm("Ready for 1b?", "SEL=Go ◄=Later"):
                self.ui.show("1b later...", f"{self.part_1a_points}/{self.points} kept", hold=2)
                return 0

        if not self._run_1b(receiver):
            self.finish("Stage 1: retry 1b")
            return 0

        points = self.award()
        self.finish(f"Stage 1: +{points}pts")
        return points
