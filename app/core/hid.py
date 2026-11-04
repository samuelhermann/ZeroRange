"""iButton USB HID reader shared by every scenario.

Replaces the two copy-pasted ``_HIDReaderAdapter`` / ``_find_hid_device``
implementations of the Coffee and Garage handlers.  The reader only collects
UIDs in the background; waiting / countdown / BACK handling is UI logic and
lives in the stages (see ``app.scenarios.stages.IButtonMatchStage``).
"""

import glob
import logging
import queue
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_NAME_HINTS = ("ibutton", "hid", "keyboard", "usb")


def find_hid_device(preferred: Optional[str] = None) -> Optional[str]:
    """Return the input device to use.

    ``preferred`` (``settings.hid_device`` in config.json) wins when set.
    Otherwise the first ``/dev/input/event*`` whose name looks like a HID
    keyboard-emulating reader is returned.
    """
    if preferred:
        return preferred
    try:
        from evdev import InputDevice  # type: ignore
    except ImportError:
        return None
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            dev = InputDevice(path)
            name = dev.name.lower()
            dev.close()
        except Exception:
            continue
        if any(hint in name for hint in _NAME_HINTS):
            return path
    return None


class HIDReader:
    """Background UID collector with a non-blocking :meth:`take_uid`.

    ``available`` is False when evdev or the device is missing; stages show a
    "reader not detected" screen in that case instead of crashing.
    """

    def __init__(self, device_path: Optional[str],
                 reader_factory: Optional[Callable[[str], object]] = None):
        self.device_path = device_path
        self._uids: "queue.SimpleQueue[str]" = queue.SimpleQueue()
        self._reader = None

        if not device_path:
            logger.warning("No iButton HID device found")
            return
        try:
            if reader_factory is None:
                from ibutton_usb_reader import IButtonUSBReader as reader_factory  # type: ignore
            self._reader = reader_factory(device_path)
            self._reader.start(callback=self._uids.put)
            logger.info("HID reader opened on %s", device_path)
        except Exception as exc:
            logger.warning("HID reader not available on %s: %s", device_path, exc)
            self._reader = None

    @classmethod
    def autodetect(cls, preferred: Optional[str] = None) -> "HIDReader":
        return cls(find_hid_device(preferred))

    @property
    def available(self) -> bool:
        return self._reader is not None

    def take_uid(self) -> Optional[str]:
        try:
            return self._uids.get_nowait()
        except queue.Empty:
            return None

    def clear(self) -> None:
        """Drop UIDs read before the current prompt (stale touches)."""
        while self.take_uid() is not None:
            pass

    def close(self) -> None:
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception as exc:
                logger.debug("HID close error: %s", exc)
            self._reader = None
