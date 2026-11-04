"""NFC module — picked up automatically by the registry."""

from app.scenarios.base import ScenarioDef
from challenges.nfc.stages import Clone, Detect, MifareAttack

SCENARIO = ScenarioDef(
    key="nfc",
    title="NFC",
    description="ISO14443A cards: detect, clone a UID, recover MIFARE Classic keys.",
    stages=(Detect, Clone, MifareAttack),
    complete_lines=("NFC MODULE", "COMPLETE!"),
    order=2,
)
