"""Coffee scenario declaration — picked up automatically by the registry."""

from app.scenarios.base import ScenarioDef
from challenges.coffee.prep_badges import PrepBadges
from challenges.coffee.stage1_technician import Stage1
from challenges.coffee.stage2_dump import Stage2
from challenges.coffee.stage3_refill import Stage3

SCENARIO = ScenarioDef(
    key="coffee",
    title="Coffee",
    brand="Sam BrewMaster",
    description="Fictional badge-operated coffee station: iButton maintenance "
                "token, MIFARE Classic dump, value-block forgery.",
    disclaimer=("Pro is FICTIONAL", "Training only.", "No real systems."),
    stages=(Stage1, Stage2, Stage3),
    tools=(PrepBadges,),
    complete_lines=("COFFEE MODULE", "COMPLETE!"),
    order=10,
)
