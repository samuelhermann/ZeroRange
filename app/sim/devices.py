"""Simulated hardware with the same interface as the real handlers.

Each device takes its input from the :class:`~app.sim.inbox.SimHub`.
The PM3 simulation even checks MIFARE keys against the emulated badge, so
"SEL = verify" in a MIFARE stage behaves like the real thing.
"""

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.core.nfc_file import make_mfc1k, parse_nfc
from app.core.paths import resolve
from app.scenarios.stages import block_to_sector, sector_first_block

logger = logging.getLogger(__name__)

IDLE_SLEEP = 0.15   # what a real probe would spend talking to hardware


class SimAuthError(RuntimeError):
    """Same role as proxmark_handler.ProxmarkAuthError (matched by name: "Auth")."""


class SimHID:
    available = True

    def __init__(self, hub):
        self.hub = hub

    def take_uid(self) -> Optional[str]:
        event = self.hub.take("ibutton")
        return event["uid"] if event else None

    def clear(self) -> None:
        pass  # injected touches are intentional, never stale

    def close(self) -> None:
        pass


class SimEmulation:
    def __init__(self, hub, blocks: Dict[int, bytes]):
        self.hub = hub
        self.blocks = blocks
        self.log: List[str] = []
        self.stopped = False

    def read_log_lines(self) -> List[str]:
        while True:
            event = self.hub.take("pm3_log")
            if not event:
                return list(self.log)
            self.log.append(event["line"])

    def stop(self) -> None:
        self.stopped = True


class SimProxmark:
    simulation_mode = False   # behaves like real hardware for the stages

    def __init__(self, hub):
        self.hub = hub
        self.emulation: Optional[SimEmulation] = None
        self.card: Optional[Dict[int, bytes]] = None

    # NFC / RFID scans ----------------------------------------------------
    def nfc_scan(self):
        event = self.hub.take("nfc")
        if not event:
            time.sleep(IDLE_SLEEP)
            return None
        return {"uid": event["uid"], "type": event.get("type", "MIFARE Classic")}

    def nfc_dump_mifare(self):
        return {i: "00" * 16 for i in range(64)}

    def rfid_scan(self):
        event = self.hub.take("rfid")
        if not event:
            time.sleep(IDLE_SLEEP)
            return None
        return {"id": event["id"], "type": event.get("type", "EM410x")}

    def rfid_clone_to_t5577(self, tag_id, tag_type="em410x") -> bool:
        logger.info("[SIM] T5577 written with %s %s", tag_type, tag_id)
        return True

    def rfid_simulate_em410x(self, tag_id) -> bool:
        logger.info("[SIM] simulating EM410x %s", tag_id)
        return True

    # MIFARE Classic ------------------------------------------------------
    def emulate_mfc_from_file(self, nfc_path) -> SimEmulation:
        self.emulation = SimEmulation(self.hub, parse_nfc(resolve(nfc_path)))
        logger.info("[SIM] emulating %s", nfc_path)
        return self.emulation

    def _antenna_card(self) -> Optional[Dict[int, bytes]]:
        while True:
            event = self.hub.take("pm3_card")
            if not event:
                break
            self.card = parse_nfc(resolve(event["path"]))
        while True:
            event = self.hub.take("pm3_block")
            if not event:
                break
            if self.card is None:
                self.card = make_mfc1k(bytes.fromhex("DEADBEEF"))
            self.card[int(event["block"])] = bytes.fromhex(str(event["data"]).replace(" ", ""))
        return self.card

    def read_block(self, block: int, key: bytes, key_type: str = "B") -> bytes:
        active = self.emulation if self.emulation and not self.emulation.stopped else None
        card = active.blocks if active else self._antenna_card()
        if card is None:
            raise RuntimeError("[SIM] no card on the antenna (inject pm3_card)")
        trailer = card[sector_first_block(block_to_sector(block)) + 3]
        expected = trailer[0:6] if key_type.upper() == "A" else trailer[10:16]
        if bytes(key) != expected:
            raise SimAuthError(f"[SIM] auth failed on block {block} with key {bytes(key).hex()}")
        return card[block]


class SimHackRF:
    simulation_mode = False
    device_connected = True

    def __init__(self, hub):
        self.hub = hub
        self._dir = Path(tempfile.mkdtemp(prefix="zr_sim_rf_"))

    def capture_signal(self, duration_seconds=1.0, frequency=None, filename=None):
        event = self.hub.take("rf")
        if not event:
            time.sleep(IDLE_SLEEP)
            return False, None, {}
        path = self._dir / f"capture_{int(time.time() * 1000)}.raw"
        path.write_bytes(b"\x7f\x7f" * 2048)
        freq = int(event.get("frequency", frequency or 433_920_000))
        return True, str(path), {"detected": True, "frequency": freq,
                                 "signal_strength": float(event.get("strength", -40))}

    def replay_signal(self, filepath, frequency=None, repeat=1) -> bool:
        logger.info("[SIM] replay %s x%s", filepath, repeat)
        return True

    def analyze_signal(self, filepath) -> Dict:
        return {"protocol": "Princeton", "modulation": "OOK", "confidence": 0.9}

    def set_frequency(self, freq_hz) -> bool:
        return True

    def cleanup(self) -> None:
        for f in self._dir.glob("*"):
            f.unlink(missing_ok=True)
        try:
            os.rmdir(self._dir)
        except OSError:
            pass


class SimFlirc:
    simulation_mode = False
    device_connected = True

    def __init__(self, hub):
        self.hub = hub

    def receive_ir(self, timeout=1):
        event = self.hub.take("ir")
        if not event:
            time.sleep(min(timeout, IDLE_SLEEP))
            return False, None
        return True, {"keycode": event["keycode"], "protocol": event.get("protocol", "NEC"),
                      "scancode": event.get("scancode", event["keycode"]),
                      "timestamp": time.time()}

    def cleanup(self) -> None:
        pass
