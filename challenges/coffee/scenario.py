"""Coffee scenario declaration — picked up automatically by the registry."""

from app.core.config import lookup
from app.core.nfc_file import parse_nfc, write_nfc
from app.core.paths import resolve
from app.core.session import random_hex, repo_relative
from app.scenarios.base import ScenarioDef
from challenges.coffee import BADGE_HIGH, BADGE_LOW
from challenges.coffee.prep_badges import PrepBadges
from challenges.coffee.stage1_technician import Stage1
from challenges.coffee.stage2_dump import Stage2
from challenges.coffee.stage3_refill import Stage3

KEY_B_SECTORS = range(8, 15)


def secrets(rng, config, out_dir):
    """New session: a new Key B, written into both reference badges.

    The technician iButton is a physical token, so its UID stays as configured.
    """
    key_b = random_hex(rng, 6)
    paths = {}
    for name, default in (("low", BADGE_LOW), ("high", BADGE_HIGH)):
        blocks = parse_nfc(resolve(lookup(config, f"badge_paths.{name}", default)))
        for sector in KEY_B_SECTORS:
            trailer = 4 * sector + 3
            blocks[trailer] = blocks[trailer][:10] + bytes.fromhex(key_b)
        dst = out_dir / f"credit_{name}.nfc"
        write_nfc(dst, blocks)
        paths[name] = repo_relative(dst)
    return {"master_key_b_hex": key_b, "badge_paths": paths}


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
    sequential=True,
    secrets=secrets,
)
