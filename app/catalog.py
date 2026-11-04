"""Single source of truth for every scored challenge.

* Classic modules (iButton, NFC, RFID, SubGHZ, IR) are described by the
  :data:`CLASSIC_MODULES` table below — the main app builds their menus from it.
* Scenario stages describe themselves (``Stage.challenge_id`` etc.).

``build_catalog`` merges both into the rows the database is synced with, so
adding a challenge no longer means editing three hard-coded lists in
``database.py`` and ``zerorange.py``.
"""

from dataclasses import dataclass
from typing import Iterable, List, Tuple

CatalogRow = Tuple[int, str, str, str, int]  # id, module, name, description, points


@dataclass(frozen=True)
class ClassicChallenge:
    id: int
    label: str        # LCD label, e.g. "Ch1:Touch"
    method: str       # handler method returning points earned
    name: str
    description: str
    points: int = 10


@dataclass(frozen=True)
class ClassicModule:
    key: str                      # DB module name
    title: str                    # main-menu label
    handler: str                  # attribute of ZeroRange holding the handler
    unavailable: Tuple[str, str]  # screen shown when the hardware is missing
    challenges: Tuple[ClassicChallenge, ...]

    @property
    def max_points(self) -> int:
        return sum(c.points for c in self.challenges)


CLASSIC_MODULES: Tuple[ClassicModule, ...] = (
    ClassicModule("ibutton", "iButton", "ibutton", ("iBtn Not Ready", "Connect USB L=Bk"), (
        ClassicChallenge(1, "Ch1:Touch", "challenge_1_touch", "Touch & Read", "Detect any iButton"),
        ClassicChallenge(2, "Ch2:Clone", "challenge_2_clone", "Clone iButton", "Read then emulate"),
        ClassicChallenge(3, "Ch3:Emulate", "challenge_3_emulate", "Emulate Specific", "Create custom ID"),
    )),
    ClassicModule("nfc", "NFC", "nfc", ("NFC - No PM3!", "L=Back"), (
        ClassicChallenge(4, "Ch4:Detect", "challenge_1_detect", "Detect & Read", "Detect any NFC card"),
        ClassicChallenge(5, "Ch5:Clone", "challenge_2_clone", "Clone Card", "Read and dump NFC"),
        ClassicChallenge(6, "Ch6:MIFARE", "challenge_3_mifare_attack", "MIFARE Attack", "Break MIFARE Classic"),
    )),
    ClassicModule("rfid", "RFID", "rfid", ("RFID - No PM3!", "L=Back"), (
        ClassicChallenge(7, "Ch7:Detect", "challenge_1_detect", "Detect Tag", "Detect RFID 125kHz"),
        ClassicChallenge(8, "Ch8:Clone", "challenge_2_clone", "Clone to T5577", "Clone tag to T5577"),
        ClassicChallenge(9, "Ch9:Simulate", "challenge_3_simulate", "Simulate EM410x", "Simulate EM410x tag"),
    )),
    ClassicModule("subghz", "SubGHZ", "subghz", ("SubGHz-No HackRF", "L=Back"), (
        ClassicChallenge(10, "Ch10:Detect", "challenge_1_detect", "Detect Signal", "Capture RF signal"),
        ClassicChallenge(11, "Ch11:Replay", "challenge_2_replay", "Record & Replay", "Capture and replay"),
        ClassicChallenge(12, "Ch12:Analyze", "challenge_3_analyze", "Signal Analysis", "Analyze RF protocol"),
    )),
    ClassicModule("ir", "IR", "ir", ("IR - No FLIRC!", "L=Back"), (
        ClassicChallenge(13, "Ch13:Detect", "challenge_1_detect", "Detect IR", "Detect any IR signal"),
        ClassicChallenge(14, "Ch14:Replay", "challenge_2_replay", "Capture & Replay", "Record and replay IR"),
        ClassicChallenge(15, "Ch15:Protocol", "challenge_3_protocol", "Protocol Analysis", "Identify IR protocol"),
    )),
)


def classic_rows() -> List[CatalogRow]:
    return [(c.id, m.key, c.name, c.description, c.points)
            for m in CLASSIC_MODULES for c in m.challenges]


def build_catalog(scenarios: Iterable = ()) -> List[CatalogRow]:
    rows = classic_rows()
    for scenario in scenarios:
        rows.extend(scenario.catalog_rows())
    return sorted(rows)


def next_free_ids(rows: Iterable[CatalogRow], count: int) -> List[int]:
    """Allocate *count* consecutive ids after the highest one in use."""
    start = max((r[0] for r in rows), default=0) + 1
    return list(range(start, start + count))
