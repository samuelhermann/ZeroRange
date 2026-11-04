"""RFID 125 kHz module — picked up automatically by the registry."""

from app.scenarios.base import ScenarioDef
from challenges.rfid.stages import CloneT5577, Detect, SimulateEM

SCENARIO = ScenarioDef(
    key="rfid",
    title="RFID",
    description="125 kHz tags: detect, clone to a T5577, simulate an EM410x.",
    stages=(Detect, CloneT5577, SimulateEM),
    complete_lines=("RFID MODULE", "COMPLETE!"),
    order=3,
)
