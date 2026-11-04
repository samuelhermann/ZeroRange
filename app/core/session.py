"""Training sessions: per-session random secrets.

A trainer starts a *new session* (LCD Settings or web dashboard) before a
group arrives. Every scenario that declares ``ScenarioDef.secrets`` then gets
fresh values (keys, target UIDs...) and freshly generated files (badges,
signals) — so answers from a previous group are useless.

Secrets are stored as config overrides in ``run/session.json`` and generated
files under ``run/session/<scenario>/``. Both processes (LCD and web) read
them through ``ScenarioDef.resolve_config``. Deleting the session falls back
to the defaults of config.json.
"""

import json
import logging
import os
import random
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.paths import RUN_DIR

logger = logging.getLogger(__name__)

SESSION_FILE = RUN_DIR / "session.json"
SESSION_DIR = RUN_DIR / "session"


def load_session(path: Optional[Path] = None) -> Dict[str, Any]:
    """Current session (``{}`` if none)."""
    try:
        with open(path or SESSION_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable session file: %s", exc)
        return {}


def session_overrides(section: str, session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = load_session() if session is None else session
    value = data.get("overrides", {}).get(section, {})
    return value if isinstance(value, dict) else {}


def new_session(scenarios, *, rng: Optional[random.Random] = None,
                path: Optional[Path] = None, directory: Optional[Path] = None,
                config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate fresh secrets for every scenario that supports it."""
    rng = rng or random.SystemRandom()
    path = Path(path or SESSION_FILE)
    directory = Path(directory or SESSION_DIR)
    if directory.exists():
        shutil.rmtree(directory)

    overrides: Dict[str, Dict[str, Any]] = {}
    for scenario in scenarios:
        if scenario.secrets is None:
            continue
        out_dir = directory / scenario.key
        out_dir.mkdir(parents=True, exist_ok=True)
        base = scenario.resolve_config(config, session={})
        try:
            values = scenario.secrets(rng, base, out_dir) or {}
        except Exception as exc:  # one broken generator must not block the others
            logger.error("Secrets for %s failed: %s", scenario.key, exc, exc_info=True)
            continue
        overrides[scenario.section] = values

    session = {
        "id": time.strftime("%Y%m%d-%H%M%S") + f"-{rng.randrange(16**4):04x}",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overrides": overrides,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    logger.info("New training session %s (%d scenario(s) randomized)", session["id"], len(overrides))
    return session


def clear_session(path: Optional[Path] = None, directory: Optional[Path] = None) -> None:
    """Back to the static secrets of config.json."""
    Path(path or SESSION_FILE).unlink(missing_ok=True)
    shutil.rmtree(directory or SESSION_DIR, ignore_errors=True)
    logger.info("Training session cleared")


# ---------------------------------------------------------------------------
# Helpers for secret generators
# ---------------------------------------------------------------------------

def repo_relative(path: Path) -> str:
    """Store generated paths relative to the repo so the session survives a move."""
    from app.core.paths import REPO_ROOT
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def random_hex(rng: random.Random, n_bytes: int) -> str:
    return "".join(f"{rng.randrange(256):02X}" for _ in range(n_bytes))


def dallas_crc8(data: bytes) -> int:
    """Maxim/Dallas 1-Wire CRC8 (poly x^8+x^5+x^4+1, reflected 0x8C)."""
    crc = 0
    for byte in data:
        for _ in range(8):
            mix = (crc ^ byte) & 1
            crc >>= 1
            if mix:
                crc ^= 0x8C
            byte >>= 1
    return crc


def random_ds1990_uid(rng: random.Random) -> str:
    """Valid DS1990A ROM id: family 0x01 + 6-byte serial + CRC8 (16 hex chars)."""
    body = bytes([0x01] + [rng.randrange(256) for _ in range(6)])
    return (body + bytes([dallas_crc8(body)])).hex().upper()
