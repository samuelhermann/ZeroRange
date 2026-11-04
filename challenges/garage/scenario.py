"""Garage scenario declaration — picked up automatically by the registry."""

from app.core.nfc_file import parse_nfc, write_nfc
from app.core.paths import resolve
from app.core.session import random_hex, repo_relative
from app.scenarios.base import ScenarioDef
from challenges.garage import TECH_ROOM_BADGE
from challenges.garage.rolling_scheme import write_sub_file
from challenges.garage.stage1_rolling import Stage1
from challenges.garage.stage2_pedestrian import Stage2
from challenges.garage.stage3_tech_room import Stage3


def secrets(rng, config, out_dir):
    """New session: new tech-room Key A (badge regenerated) and a new rolling
    remote (device id + seed), with matching reference .sub captures.

    The pedestrian fob is a physical DS1990, so its UID stays as configured.
    """
    key_a = random_hex(rng, 6)
    blocks = parse_nfc(resolve(config.get("badge_path") or TECH_ROOM_BADGE))
    blocks[3] = bytes.fromhex(key_a) + blocks[3][6:]
    badge = out_dir / "tech_room.nfc"
    write_nfc(badge, blocks)

    rolling = config.get("rolling", {})
    device_id, seed = random_hex(rng, 4), random_hex(rng, 4)
    counter = int(rolling.get("initial_counter", 100))
    freq = int(rolling.get("freq_hz", 433_920_000))
    signals = {}
    for name, ctr in (("press_N", counter), ("press_N_plus_1", counter + 1)):
        path = out_dir / f"{name}.sub"
        write_sub_file(path, bytes.fromhex(device_id), ctr, bytes.fromhex(seed), freq)
        signals[name] = repo_relative(path)

    return {
        "tech_room_key_a_hex": key_a,
        "badge_path": repo_relative(badge),
        "rolling": {"device_id_hex": device_id, "seed_hex": seed},
        "signal_paths": signals,
    }


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
    sequential=True,
    secrets=secrets,
)
