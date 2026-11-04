"""Ready-made stage types for the most common training patterns.

Most scenario stages are one of a handful of shapes.  Subclass one of these
and set class attributes — no event loop to write:

* :class:`IButtonMatchStage`      touch a specific iButton UID on the HID reader
* :class:`MifareEmulationStage`   PM3 emulates a badge, learner must authenticate
                                  to given sectors with a given key
* :class:`BadgeEmulatorTool`      unscored "prep" tool: emulate reference badges
"""

import logging
import re
from typing import ClassVar, Iterable, Optional, Sequence, Set, Tuple

from app.core.ui import Button, hex_fit, is_hex, normalize_hex
from app.scenarios.base import Stage, Tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# iButton UID match
# ---------------------------------------------------------------------------

class IButtonMatchStage(Stage):
    """Learner presents the iButton whose UID is ``config[uid_key]``.

    Override :meth:`reveal` to show a "leak" (key, code...) after success —
    it is also replayed when a solved stage is re-opened.
    """

    requires = "hid"

    uid_key: ClassVar[str] = "target_uid"
    default_uid: ClassVar[str] = ""
    max_wrong_key: ClassVar[str] = "max_wrong_reads"
    default_max_wrong: ClassVar[int] = 3
    read_timeout: ClassVar[int] = 60

    intro: ClassVar[Tuple[str, str]] = ()           # splash (row0, row1), 2 s
    prompt: ClassVar[str] = "Touch iButton"
    noun: ClassVar[str] = "key"                     # "No key seen", "Wrong key!"
    streak_hint: ClassVar[str] = "Check your key"   # after max_wrong misses
    #: ``{points}`` is replaced by the points earned (after hint penalty).
    success_lines: ClassVar[Tuple[str, str]] = ("Access granted!", "+{points}pts")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "config_keys" not in cls.__dict__:
            cls.config_keys = (cls.uid_key,)

    @classmethod
    def defaults(cls):
        return {cls.uid_key: cls.default_uid}

    # hooks ------------------------------------------------------------------

    def reveal(self) -> None:
        """Called after success and when re-running a solved stage."""

    # helpers ----------------------------------------------------------------

    def target_uid(self) -> str:
        return self.cfg_hex(self.uid_key, self.default_uid)

    def matches(self, uid: str, target: str) -> bool:
        return normalize_hex(uid) == target

    def _wait_uid(self) -> Tuple[Optional[str], bool]:
        """Return ``(uid, aborted)``; ``(None, False)`` means timeout."""
        self.hw.clear()
        uid, outcome = self.wait_for(self.hw.take_uid, timeout=self.read_timeout)
        return uid, outcome == "back"

    # flow -------------------------------------------------------------------

    def run(self) -> int:
        if self.already_complete():
            self.reveal()
            return 0

        if self.intro:
            self.ui.show(*self.intro, hold=2)

        if not self.require_hardware("iBtn reader N/A", "Connect reader ◄"):
            return 0

        target = self.target_uid()
        if not is_hex(target):
            logger.error("%s: config %r is not a valid UID: %r",
                         type(self).__name__, self.uid_key, target)
            self.ui.notice("Stage not set up", "Check config ◄")
            return 0

        max_wrong = max(1, int(self.cfg_get(self.max_wrong_key, self.default_max_wrong)))
        wrong = 0
        self.start_timer()

        while True:
            self.ui.show(self.prompt, "◄=Back")
            uid, aborted = self._wait_uid()
            if aborted:
                logger.info("%s aborted by user", type(self).__name__)
                return 0
            if uid is None:
                if not self.retry(f"No {self.noun} seen"):
                    return 0
                continue

            if self.matches(uid, target):
                points = self.award()
                self.ui.show(*(line.format(points=points) for line in self.success_lines), hold=2)
                self.reveal()
                self.finish()
                return points

            wrong += 1
            logger.warning("%s wrong UID %s (streak %d)", type(self).__name__,
                           normalize_hex(uid), wrong)
            self.emit(event="uid_rejected", stage=self.number, streak=wrong)
            if wrong >= max_wrong:
                wrong = 0
                self.ui.show(f"Wrong {self.noun}!", self.streak_hint, hold=3)
                if not self.ui.confirm(f"Wrong {self.noun}", "SEL=Retry ◄=Back"):
                    return 0
            else:
                left = max_wrong - wrong
                self.ui.show(f"Wrong {self.noun}!", f"{left} tr{'y' if left == 1 else 'ies'} left",
                             hold=2)


# ---------------------------------------------------------------------------
# MIFARE Classic emulation + authentication
# ---------------------------------------------------------------------------

_SECTOR_RE = re.compile(r"\bSECT(?:OR)?\s*[:#=]?\s*(\d+)")
_BLOCK_RE = re.compile(r"\b(?:BLOCK|BLK)\s*[:#=]?\s*(\d+)")


def block_to_sector(block: int) -> int:
    """MIFARE Classic 1K/4K block -> sector."""
    return block // 4 if block < 128 else 32 + (block - 128) // 16


def sector_first_block(sector: int) -> int:
    return sector * 4 if sector < 32 else 128 + (sector - 32) * 16


class MifareEmulationStage(Stage):
    """The Proxmark3 emulates ``config[badge_key]``; the learner must read the
    ``sectors`` using the key in ``config[key_key]``.

    Completion: auto-detected from the ``hf mf sim`` log, or SELECT ("I'm done")
    triggers :meth:`verify` (PM3 reads the first block of every sector).
    """

    requires = "proxmark"

    badge_key: ClassVar[str] = "badge_path"
    default_badge: ClassVar[str] = ""
    key_key: ClassVar[str] = "key_hex"
    default_key: ClassVar[str] = ""
    key_type: ClassVar[str] = "A"
    sectors: ClassVar[frozenset] = frozenset({0})
    #: When True a log line only counts if it contains the expected key.
    log_requires_key: ClassVar[bool] = True

    intro: ClassVar[Tuple[str, str]] = ()
    instructions: ClassVar[Sequence[Tuple[str, str]]] = ()   # screens shown after PM3 starts
    waiting_lines: ClassVar[Tuple[str, str]] = ("PM3 emulates card", "SEL=Done ◄=Back")
    success_lines: ClassVar[Tuple[str, str]] = ("ACCESS GRANTED", "+{points}pts")
    not_yet_lines: ClassVar[Tuple[str, str]] = ("Not yet!", "Auth all sectors")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "config_keys" not in cls.__dict__:
            cls.config_keys = (cls.badge_key, cls.key_key)
        if "file_keys" not in cls.__dict__:
            cls.file_keys = (cls.badge_key,)

    @classmethod
    def defaults(cls):
        return {cls.badge_key: cls.default_badge, cls.key_key: cls.default_key}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._found: Set[int] = set()
        self._seen_lines = 0

    # helpers ----------------------------------------------------------------

    def key_hex(self) -> str:
        return self.cfg_hex(self.key_key, self.default_key)

    def detect_sectors(self, lines: Iterable[str]) -> Set[int]:
        """Sectors authenticated with the expected key according to PM3 log lines."""
        key = self.key_hex()
        found: Set[int] = set()
        for raw in lines:
            line = raw.upper()
            if "FAIL" in line:
                continue
            compact = line.replace(" ", "")
            if self.log_requires_key:
                if key not in compact:
                    continue
            elif "AUTH" not in line and key not in compact:
                continue
            found.update(int(m) for m in _SECTOR_RE.findall(line))
            found.update(block_to_sector(int(m)) for m in _BLOCK_RE.findall(line))
        return found & set(self.sectors)

    def verify(self) -> bool:
        """Ask the PM3 to read every target sector with the expected key."""
        key = bytes.fromhex(self.key_hex())
        for sector in sorted(self.sectors):
            try:
                data = self.pm3_read(sector_first_block(sector), key)
            except Exception as exc:
                logger.info("Verify sector %d failed: %s", sector, exc)
                return False
            if not data or len(data) != 16:
                return False
            self._found.add(sector)
        return True

    def pm3_read(self, block: int, key: bytes) -> Optional[bytes]:
        return self.hw.read_block(block, key, self.key_type)

    def _poll_log(self, handle) -> None:
        try:
            lines = handle.read_log_lines()
        except Exception as exc:
            logger.debug("PM3 log read failed: %s", exc)
            return
        fresh = lines[self._seen_lines:]
        self._seen_lines = len(lines)
        new = self.detect_sectors(fresh) - self._found
        if new:
            self._found |= new
            self.emit(event="sector_unlocked", stage=self.number,
                      sectors=sorted(self._found), total=len(self.sectors))

    def on_success(self) -> Tuple[dict, ...]:
        """Extra events to emit with the award (override if needed)."""
        return ()

    # flow -------------------------------------------------------------------

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0

        if self.intro:
            self.ui.show(*self.intro, hold=2)

        if not self.require_hardware("Proxmark3 needed", "Not detected! ◄"):
            return 0

        badge = self.cfg_path(self.badge_key, self.default_badge)
        self.ui.show("Loading badge...", "Starting PM3...")
        try:
            handle = self.hw.emulate_mfc_from_file(badge)
        except Exception as exc:
            logger.error("%s: emulation failed for %s: %s", type(self).__name__, badge, exc)
            self.ui.show("PM3 load failed!", str(exc), hold=3)
            return 0

        try:
            return self._loop(handle)
        finally:
            try:
                handle.stop()
            except Exception as exc:
                logger.warning("Error stopping emulation: %s", exc)

    def _loop(self, handle) -> int:
        for screen in self.instructions:
            self.ui.show(*screen, hold=2.5)

        self.start_timer()
        total = len(self.sectors)
        shown = None
        while True:
            self._poll_log(handle)
            if self._found >= set(self.sectors):
                return self._success()

            if total > 1 and shown != len(self._found):
                shown = len(self._found)
                self.ui.show(f"Sectors: {shown}/{total}", self.waiting_lines[1])
            elif total == 1 and shown is None:
                shown = 0
                self.ui.show(*self.waiting_lines)

            btn = self.ui.poll(Button.SELECT, Button.BACK)
            if btn == Button.BACK:
                logger.info("%s aborted by user", type(self).__name__)
                return 0
            if btn == Button.SELECT:
                self.ui.show("Verifying...", "PM3 reading...")
                if self.verify():
                    return self._success()
                self.ui.show(*self.not_yet_lines, hold=2.5)
                shown = None
            self.ui.sleep(0.1)

    def _success(self) -> int:
        points = self.award(*self.on_success())
        self.ui.show(*(line.format(points=points) for line in self.success_lines), hold=3)
        self.finish()
        return points


# ---------------------------------------------------------------------------
# Badge emulator tool
# ---------------------------------------------------------------------------

class BadgeEmulatorTool(Tool):
    """Lets a trainer emulate reference badges so learners can save them.

    ``badges`` is a sequence of ``(label, config_key, default_path)``.
    SELECT toggles the display of ``config[key_key]``, BACK stops.
    """

    title = "Prep Badges"
    requires = "proxmark"
    badges: ClassVar[Sequence[Tuple[str, str, str]]] = ()
    key_key: ClassVar[str] = ""
    default_key: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "file_keys" not in cls.__dict__:
            cls.file_keys = tuple(k for _, k, _ in cls.badges)
        if "config_keys" not in cls.__dict__:
            cls.config_keys = cls.file_keys + ((cls.key_key,) if cls.key_key else ())

    @classmethod
    def defaults(cls):
        values = {k: d for _, k, d in cls.badges}
        if cls.key_key:
            values[cls.key_key] = cls.default_key
        return values

    def run(self) -> int:
        labels = [label for label, _, _ in self.badges]
        selected = 0
        while True:
            choice = self.ui.choose(labels, start=selected)
            if choice is None:
                return 0
            selected = choice
            label, key, default = self.badges[choice]
            self._emulate(label, self.cfg_path(key, default))

    def _emulate(self, label: str, path) -> None:
        if not self.require_hardware("PM3 not found!", "Connect PM3 ◄=Bk"):
            return
        self.ui.show(f"Loading {label[:8]}", "Starting PM3...")
        try:
            handle = self.hw.emulate_mfc_from_file(path)
        except Exception as exc:
            logger.error("Prep emulation failed: %s", exc)
            self.ui.show("PM3 load failed!", str(exc), hold=3)
            return

        logger.info("Prep: emulating %s", path)
        key = hex_fit(self.cfg_get(self.key_key, self.default_key)) if self.key_key else ""
        show_key = False
        try:
            while True:
                if show_key:
                    self.ui.show(key, "SEL=Hide  ◄=Stop")
                else:
                    hint = "SEL=Key   ◄=Stop" if key else "◄=Stop"
                    self.ui.show(f"Emul: {label[:10]}", hint)
                btn = self.ui.wait(Button.SELECT, Button.BACK)
                if btn == Button.BACK:
                    break
                show_key = bool(key) and not show_key
        finally:
            handle.stop()
            logger.info("Prep: emulation stopped")
        self.ui.show("Emulation stopped", "Badge saved? OK!", hold=2)
