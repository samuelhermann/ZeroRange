"""Trainer credentials for the web dashboard.

Resolution order for the password:
1. ``config.local.json`` / ``config.json`` -> ``"web": {"trainer_password": "..."}``
2. environment variable ``ZERORANGE_TRAINER_PASSWORD``
3. an auto-generated password stored in ``run/trainer_password`` (mode 0600),
   shown on the LCD under Settings > Web login — physical access to the box
   is what proves you are the trainer.
"""

import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from app.core.config import config_section, load_config
from app.core.paths import RUN_DIR

logger = logging.getLogger(__name__)

TRAINER_USER = "trainer"
PASSWORD_FILE = RUN_DIR / "trainer_password"
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o/1/l/i: easy to read on an LCD


def _generate(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def get_trainer_password(config: Optional[dict] = None, path: Optional[Path] = None) -> str:
    configured = config_section("web", config if config is not None else load_config())
    if configured.get("trainer_password"):
        return str(configured["trainer_password"])
    if os.environ.get("ZERORANGE_TRAINER_PASSWORD"):
        return os.environ["ZERORANGE_TRAINER_PASSWORD"]

    path = Path(path or PASSWORD_FILE)
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except FileNotFoundError:
        pass
    value = _generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    logger.info("Generated trainer password in %s (see LCD Settings > Web login)", path)
    return value


def check_credentials(user: Optional[str], password: Optional[str], **kwargs) -> bool:
    expected = get_trainer_password(**kwargs)
    if not user or not password:
        return False
    # bytes: compare_digest refuses non-ASCII str; "&" avoids a timing short-circuit
    return hmac.compare_digest(user.encode(), TRAINER_USER.encode()) & \
        hmac.compare_digest(password.encode(), expected.encode())
