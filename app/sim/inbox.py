"""Simulator inbox: what the learner "does" with the hardware, in --sim mode.

Producers (``tools/sim_inject.py``, the dashboard's Simulator panel) append
JSON lines to ``run/sim_inbox.jsonl``; the simulated devices consume them.

    {"kind": "ibutton", "uid": "0100C0FFEE7E11AB"}
    {"kind": "nfc", "uid": "04A3F5B2", "type": "MIFARE Classic"}
    {"kind": "pm3_card", "path": "challenges/coffee/badges/credit_high.nfc"}
"""

import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional

from app.core.paths import RUN_DIR

INBOX_FILE = RUN_DIR / "sim_inbox.jsonl"

#: kind -> required fields
KINDS: Dict[str, tuple] = {
    "ibutton": ("uid",),            # touch the iButton HID reader
    "nfc": ("uid",),                # ISO14443A card on the PM3 (type optional)
    "rfid": ("id",),                # 125 kHz tag on the PM3 (type optional)
    "pm3_card": ("path",),          # .nfc card on the PM3 antenna (read_block)
    "pm3_block": ("block", "data"),  # overwrite one block of that card (32 hex)
    "pm3_log": ("line",),           # line appended to the running hf mf sim log
    "rf": (),                       # Sub-GHz transmission (strength dBm optional)
    "ir": ("keycode",),             # IR remote (protocol / scancode optional)
}


class Inbox:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or INBOX_FILE)

    def push(self, kind: str, **fields: Any) -> Dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"Unknown kind {kind!r}; choose from {', '.join(KINDS)}")
        missing = [f for f in KINDS[kind] if not fields.get(f)]
        if missing:
            raise ValueError(f"{kind} needs: {', '.join(missing)}")
        event = {"kind": kind, "ts": round(time.time(), 3), **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
        return event

    def reset(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")


class SimHub:
    """Reads new inbox lines and routes them into one queue per kind."""

    def __init__(self, path: Optional[Path] = None):
        self.inbox = Inbox(path)
        self.inbox.reset()
        self._pos = 0
        self.queues: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)

    def pump(self) -> None:
        try:
            size = os.path.getsize(self.inbox.path)
        except OSError:
            return
        if size < self._pos:           # file was reset
            self._pos = 0
        if size == self._pos:
            return
        with open(self.inbox.path, "rb") as fh:
            fh.seek(self._pos)
            chunk = fh.read()
        complete, _, _partial = chunk.rpartition(b"\n")
        if not _:
            return
        self._pos += len(complete) + 1
        for raw in complete.split(b"\n"):
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("kind") in KINDS:
                self.queues[event["kind"]].append(event)

    def take(self, kind: str) -> Optional[Dict[str, Any]]:
        self.pump()
        queue = self.queues[kind]
        return queue.popleft() if queue else None
