"""Sub-GHz module — picked up automatically by the registry."""

from app.scenarios.base import ScenarioDef
from challenges.subghz.stages import Analyze, Detect, Replay

SCENARIO = ScenarioDef(
    key="subghz",
    title="SubGHZ",
    description="433 MHz radio: detect a transmission, record & replay, analyse it.",
    stages=(Detect, Replay, Analyze),
    complete_lines=("SUBGHZ MODULE", "COMPLETE!"),
    order=4,
)
