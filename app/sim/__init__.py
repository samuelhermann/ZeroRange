"""Simulation mode: run ZeroRange on any computer, without hardware.

    python3 zerorange.py --sim

The LCD is drawn in the terminal (keyboard = the 5 buttons) and every device
is simulated. Make the "learner" act with ``tools/sim_inject.py`` or the
Simulator panel of the trainer dashboard (http://localhost:8080/dashboard/).
Scores go to ``run/sim_scores.db``, never to the real ``scores.db``.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from app.core.paths import SIM_FLAG
from app.sim.devices import SimFlirc, SimHackRF, SimHID, SimProxmark
from app.sim.inbox import SimHub
from app.sim.lcd import TerminalLCD



@dataclass
class SimEnvironment:
    lcd: object
    hub: SimHub
    devices: Dict[str, object] = field(default_factory=dict)
    flag: Path = SIM_FLAG

    def close(self) -> None:
        self.flag.unlink(missing_ok=True)
        if hasattr(self.lcd, "close"):
            self.lcd.close()


def build_sim_environment(lcd=None, inbox: Optional[Path] = None,
                          flag: Path = SIM_FLAG) -> SimEnvironment:
    hub = SimHub(inbox)
    hid = SimHID(hub)
    devices = {
        "proxmark": SimProxmark(hub),
        "hackrf": SimHackRF(hub),
        "flirc": SimFlirc(hub),
        "hid_factory": lambda: hid,
    }
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("1\n", encoding="utf-8")
    return SimEnvironment(lcd=lcd or TerminalLCD(), hub=hub, devices=devices, flag=flag)
