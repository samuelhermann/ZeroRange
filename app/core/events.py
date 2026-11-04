"""Cross-process event bus between the LCD app and the web companion.

Why: ``zerorange.py`` and ``app/web/wsgi.py`` run as two separate systemd
services.  The previous implementation kept SSE subscribers in an in-memory
list *inside the web process* while stages called ``emit_event`` *inside the
LCD process* — so no event ever reached a browser.

How: each channel (one per scenario) is an append-only JSON-lines file under
``run/events/<channel>.jsonl``.  The LCD process appends, the web process
follows the file like ``tail -F``.  Same pattern as the existing
``run/lcd_state.json`` mirror: no broker, no extra dependency, and the LCD
keeps working if the web companion is down.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

from app.core.paths import EVENTS_DIR

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 256 * 1024


def channel_path(channel: str, directory: Optional[Path] = None) -> Path:
    return Path(directory or EVENTS_DIR) / f"{channel}.jsonl"


class EventBus:
    """Callable publisher: ``bus({"event": "x"})`` appends one JSON line.

    Instances are drop-in replacements for the old ``sse_emit`` callbacks.
    Publishing never raises: a full disk must not crash a training session.
    """

    def __init__(self, channel: str, directory: Optional[Path] = None,
                 max_bytes: int = DEFAULT_MAX_BYTES):
        self.channel = channel
        self.path = channel_path(channel, directory)
        self.max_bytes = max_bytes

    def emit(self, data: Dict[str, Any]) -> None:
        record = dict(data)
        record.setdefault("ts", round(time.time(), 3))
        line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            # O_APPEND + a single small write => atomic w.r.t. the reader.
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            logger.debug("Event bus %s: could not write event: %s", self.channel, exc)

    __call__ = emit

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.stat().st_size > self.max_bytes:
                os.replace(self.path, self.path.with_suffix(".jsonl.1"))
        except FileNotFoundError:
            pass


def follow(path: Path, *, from_start: bool = False, poll: float = 0.25,
           keepalive: float = 25.0,
           clock: Callable[[], float] = time.monotonic,
           sleep: Callable[[float], None] = time.sleep) -> Iterator[Optional[str]]:
    """Yield lines appended to *path*, forever (``tail -F`` semantics).

    * Yields ``None`` after *keepalive* seconds without data (SSE heartbeat).
    * Copes with the file not existing yet, being rotated or truncated.
    * Starts at the end of an existing file unless *from_start*.
    """
    path = Path(path)
    handle = None
    inode = None
    buf = b""
    first_open = True
    last_activity = clock()

    def _drain(fh):
        nonlocal buf
        chunk = fh.read()
        if not chunk:
            return []
        buf += chunk
        *complete, buf = buf.split(b"\n")
        return [c.decode("utf-8", "replace") for c in complete if c.strip()]

    try:
        while True:
            lines = []
            try:
                st = path.stat()
            except FileNotFoundError:
                st = None
                first_open = False  # a file created later is read from its start

            if st is not None:
                rotated = handle is not None and st.st_ino != inode
                truncated = handle is not None and not rotated and st.st_size < handle.tell()
                if rotated:
                    lines.extend(_drain(handle))  # finish the old file first
                    handle.close()
                    handle = None
                if truncated:
                    handle.seek(0)
                    buf = b""
                if handle is None:
                    handle = open(path, "rb")
                    inode = st.st_ino
                    buf = b""
                    if first_open and not from_start:
                        handle.seek(0, os.SEEK_END)
                    first_open = False

            if handle is not None:
                lines.extend(_drain(handle))

            if lines:
                last_activity = clock()
                for line in lines:
                    yield line
            elif clock() - last_activity >= keepalive:
                last_activity = clock()
                yield None
            else:
                sleep(poll)
    finally:
        if handle is not None:
            handle.close()


def sse_stream(path: Path, **follow_kwargs) -> Iterator[str]:
    """Format :func:`follow` output as Server-Sent Events."""
    yield 'data: {"event":"connected"}\n\n'
    for line in follow(path, **follow_kwargs):
        if line is None:
            yield ": keepalive\n\n"
            continue
        try:
            json.loads(line)
        except ValueError:
            continue  # never forward a torn/garbage line to the browser
        yield f"data: {line}\n\n"
