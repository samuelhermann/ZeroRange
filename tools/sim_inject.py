#!/usr/bin/env python3
"""Act as the learner while ZeroRange runs with --sim.

    python3 tools/sim_inject.py ibutton 0100C0FFEE7E11AB
    python3 tools/sim_inject.py nfc 04A3F5B2 --type "MIFARE Classic"
    python3 tools/sim_inject.py rfid 1122334455 --type EM410x
    python3 tools/sim_inject.py rf --strength -40
    python3 tools/sim_inject.py ir KEY_POWER --protocol NEC
    python3 tools/sim_inject.py pm3-log "Auth sector 8 key B B4EEC0FFEE11"
    python3 tools/sim_inject.py pm3-card challenges/coffee/badges/credit_high.nfc
    python3 tools/sim_inject.py pm3-block 40 C8000000...   # 32 hex chars
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sim.inbox import Inbox  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inject a simulated hardware event",
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ibutton", help="touch the iButton reader")
    p.add_argument("uid")
    p = sub.add_parser("nfc", help="put an NFC card on the PM3")
    p.add_argument("uid")
    p.add_argument("--type", default="MIFARE Classic")
    p = sub.add_parser("rfid", help="put a 125 kHz tag on the PM3")
    p.add_argument("id")
    p.add_argument("--type", default="EM410x")
    p = sub.add_parser("rf", help="transmit on Sub-GHz")
    p.add_argument("--strength", type=float, default=-40.0)
    p.add_argument("--frequency", type=int)
    p = sub.add_parser("ir", help="press an IR remote button")
    p.add_argument("keycode")
    p.add_argument("--protocol", default="NEC")
    p.add_argument("--scancode")
    p = sub.add_parser("pm3-log", help="append a line to the PM3 emulation log")
    p.add_argument("line")
    p = sub.add_parser("pm3-card", help="put a .nfc MIFARE card on the PM3 antenna")
    p.add_argument("path")
    p = sub.add_parser("pm3-block", help="overwrite one block of the card on the antenna")
    p.add_argument("block", type=int)
    p.add_argument("data", help="32 hex chars")

    args = vars(parser.parse_args(argv))
    kind = args.pop("cmd").replace("-", "_")
    fields = {k: v for k, v in args.items() if v is not None}
    event = Inbox().push(kind, **fields)
    print(f"injected {event}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
