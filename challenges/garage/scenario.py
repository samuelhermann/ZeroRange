"""Garage scenario declaration — picked up automatically by the registry."""

from app.scenarios.base import ScenarioDef
from challenges.garage.stage1_rolling import Stage1
from challenges.garage.stage2_pedestrian import Stage2
from challenges.garage.stage3_tech_room import Stage3

SCENARIO = ScenarioDef(
    key="garage",
    title="Garage",
    brand="Sam Garage",
    description="Fictional car park: rolling-code RollJam, iButton side gate, "
                "MIFARE tech room opened with a leaked key.",
    disclaimer=("Sam Garage", "is FICTIONAL.", "Training only.", "No real targets."),
    stages=(Stage1, Stage2, Stage3),
    complete_lines=("GARAGE MODULE", "COMPLETE!"),
    order=20,
)
