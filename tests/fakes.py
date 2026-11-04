"""Test doubles for LCD, clock and hardware.

``FakeLCD`` is driven by a *script* of button presses: each press is consumed
the first time the code polls that button. Unlike counting
``button_pressed`` calls, scripts do not break when a screen polls buttons in
a different order — and a stuck script fails loudly instead of hanging.
"""

import os
from collections import deque
from typing import Iterable, List, Optional, Sequence, Tuple

from app.catalog import build_catalog
from app.core.ui import Button
from app.scenarios.runner import ScenarioRunner
from database import Database


class ScriptStalled(AssertionError):
    pass


class Idle:
    """Script entry: press nothing for *seconds* of (fake) clock time."""

    def __init__(self, seconds: float):
        self.seconds = seconds

    def __repr__(self):
        return f"Idle({self.seconds})"


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start
        self.slept = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.t += seconds
            self.slept += seconds


class FakeLCD:
    """Records screens, replays a button script.

    ``lenient=True``: once the script is exhausted BACK reads as pressed, so
    any screen eventually unwinds (useful for smoke tests).
    """

    def __init__(self, script: Iterable = (), *, stall_limit: int = 20_000, lenient: bool = False,
                 clock: Optional[FakeClock] = None):
        self.script = deque(b if isinstance(b, Idle) else Button(b) for b in script)
        self.stall_limit = stall_limit
        self.lenient = lenient
        self.clock = clock
        self._idle_since: Optional[float] = None
        self.lines = ["", ""]
        self.screens: List[Tuple[str, str]] = []
        self._idle_polls = 0

    # LCDManager API -------------------------------------------------------

    def write_line(self, row: int, text: str) -> None:
        self.lines[row] = text.ljust(16)[:16]
        if row == 1:
            self.screens.append((self.lines[0].rstrip(), self.lines[1].rstrip()))

    def clear(self) -> None:
        self.lines = ["", ""]

    def close(self) -> None:
        pass

    def wait_button_release(self, _btn) -> None:
        pass

    def _skip_idle(self) -> bool:
        """Consume an elapsed Idle entry; True while still idling."""
        head = self.script[0] if self.script else None
        if not isinstance(head, Idle):
            return False
        if self.clock is None:
            raise ValueError("Idle() script entries need FakeLCD(clock=...)")
        if self._idle_since is None:
            self._idle_since = self.clock.now()
        if self.clock.now() - self._idle_since >= head.seconds:
            self.script.popleft()
            self._idle_since = None
            self._idle_polls = 0
            return self._skip_idle()
        return True

    def button_pressed(self, btn) -> bool:
        if self._skip_idle():
            return False
        if self.script and self.script[0] == btn:
            self.script.popleft()
            self._idle_polls = 0
            return True
        if not self.script and self.lenient and btn == Button.BACK:
            return True
        self._idle_polls += 1
        if self._idle_polls > self.stall_limit:
            head = repr(self.script[0]) if self.script else "<empty script>"
            raise ScriptStalled(f"LCD polled {self.stall_limit}x without match; next scripted "
                                f"button: {head}; last screen: {self.screens[-1:]}")
        return False

    # helpers ----------------------------------------------------------------

    def text(self) -> str:
        return "\n".join(f"{a} | {b}" for a, b in self.screens)

    def saw(self, fragment: str) -> bool:
        return any(fragment in a or fragment in b for a, b in self.screens)


class FakeHID:
    """HIDReader double: ``take_uid`` pops the next scripted UID (None = nothing)."""

    def __init__(self, uids: Sequence[Optional[str]] = (), available: bool = True):
        self.uids = deque(uids)
        self.available = available
        self.closed = False

    def take_uid(self) -> Optional[str]:
        return self.uids.popleft() if self.uids else None

    def clear(self) -> None:  # scripted UIDs are never "stale"
        pass

    def close(self) -> None:
        self.closed = True


class FakeEmulation:
    def __init__(self, log_lines: Sequence[str] = ()):
        self.log_lines = list(log_lines)
        self.stopped = False

    def read_log_lines(self) -> List[str]:
        return list(self.log_lines)

    def stop(self) -> None:
        self.stopped = True


class AuthError(RuntimeError):
    """Mimics proxmark_handler.ProxmarkAuthError (matched by name)."""


class FakePM3:
    """ProxmarkHandler double. ``cards`` / ``tags`` are scripted scan results
    (``None`` entries = nothing on the antenna for that probe)."""

    def __init__(self, blocks=None, *, simulation_mode: bool = False, log_lines=(),
                 fail_auth: bool = False, cards=(), tags=(), dump=None,
                 clone_ok: bool = True, sim_ok: bool = True):
        self.simulation_mode = simulation_mode
        self.blocks = dict(blocks or {})
        self.fail_auth = fail_auth
        self.reads: List[Tuple[int, bytes, str]] = []
        self.emulation = FakeEmulation(log_lines)
        self.emulated = []
        self.cards = deque(cards)
        self.tags = deque(tags)
        self.dump = dump
        self.clone_ok, self.sim_ok = clone_ok, sim_ok
        self.cloned: List[Tuple[str, str]] = []
        self.simulated: List[str] = []

    def nfc_scan(self):
        return self.cards.popleft() if self.cards else None

    def nfc_dump_mifare(self):
        return self.dump

    def rfid_scan(self):
        return self.tags.popleft() if self.tags else None

    def rfid_clone_to_t5577(self, tag_id, tag_type="em410x"):
        self.cloned.append((tag_id, tag_type))
        return self.clone_ok

    def rfid_simulate_em410x(self, tag_id):
        self.simulated.append(tag_id)
        return self.sim_ok

    def read_block(self, block: int, key: bytes, key_type: str = "B") -> bytes:
        self.reads.append((block, key, key_type))
        if self.fail_auth:
            raise AuthError(f"auth failed block {block}")
        return self.blocks.get(block, bytes(16))

    def emulate_mfc_from_file(self, path):
        self.emulated.append(path)
        return self.emulation


class FakeHackRF:
    """HackRFHandler double. ``captures`` scripts the signal strength (dBm) of
    successive 1-second captures; each capture writes a real temp file."""

    def __init__(self, simulation_mode: bool = True, captures=(), analysis=None):
        self.simulation_mode = simulation_mode
        self.device_connected = True
        self.replayed = []
        self.captures = deque(captures)
        self.files: List[str] = []
        self.analysis = analysis or {"protocol": "Princeton", "modulation": "OOK", "confidence": 0.9}

    def replay_signal(self, path, frequency=None, repeat=1) -> bool:
        self.replayed.append((path, frequency))
        return True

    def capture_signal(self, duration_seconds=1.0, frequency=None, filename=None):
        if not self.captures:
            return False, None, {}
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".raw")
        os.close(fd)
        self.files.append(path)
        strength = self.captures.popleft()
        return True, path, {"detected": True, "signal_strength": strength,
                            "frequency": frequency or 433_920_000}

    def analyze_signal(self, path):
        return dict(self.analysis)


class FakeFlirc:
    """FlircHandler double: ``receive_ir`` pops the next scripted event."""

    def __init__(self, events=(), simulation_mode: bool = False, device_connected: bool = True):
        self.events = deque(events)
        self.simulation_mode = simulation_mode
        self.device_connected = device_connected

    def receive_ir(self, timeout=1):
        if self.events:
            return True, dict(self.events.popleft())
        return False, None


class EventLog(list):
    """Callable event sink that records events."""

    def __call__(self, event):
        self.append(dict(event))

    def of(self, name: str):
        return [e for e in self if e.get("event") == name]


def make_db(scenarios=None) -> Database:
    """In-memory DB; by default with the catalog of every bundled scenario."""
    if scenarios is None:
        from app.scenarios.registry import get_registry
        scenarios = get_registry().scenarios
    return Database(":memory:", catalog=build_catalog(scenarios))


def make_stage(cls, *, script=(), config=None, hw=None, db=None, scenarios=None, lenient=False):
    """Instantiate a stage with fakes. Returns (stage, lcd, db, events)."""
    clock = FakeClock()
    lcd = FakeLCD(script, lenient=lenient, clock=clock)
    db = db or make_db(scenarios)
    events = EventLog()
    stage = cls(lcd, db, config or {}, hw, events, clock=clock)
    return stage, lcd, db, events


def make_runner(scenario, *, script=(), config=None, hid=None, pm3=None, hackrf=None,
                db=None, lenient=False):
    """ScenarioRunner wired to fakes. Returns (runner, lcd, db)."""
    clock = FakeClock()
    lcd = FakeLCD(script, lenient=lenient, clock=clock)
    db = db or make_db([scenario])
    hid = hid if hid is not None else FakeHID()
    runner = ScenarioRunner(
        scenario, lcd, db,
        proxmark=pm3 if pm3 is not None else FakePM3(),
        hackrf=hackrf if hackrf is not None else FakeHackRF(),
        sse_emit=EventLog(),
        config=config if config is not None else scenario.resolve_config(),
        hid_factory=lambda: hid,
        clock=clock,
        show_disclaimer=False,
    )
    return runner, lcd, db
