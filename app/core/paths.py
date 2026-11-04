"""Well-known filesystem locations, resolved from the repository root.

Using these instead of CWD-relative paths means ZeroRange works no matter which
directory systemd (or a developer) launches it from.
"""

from pathlib import Path
from typing import Union

REPO_ROOT = Path(__file__).resolve().parents[2]
CHALLENGES_DIR = REPO_ROOT / "challenges"
RUN_DIR = REPO_ROOT / "run"
EVENTS_DIR = RUN_DIR / "events"
LOG_DIR = REPO_ROOT / "logs"
DB_PATH = REPO_ROOT / "scores.db"


def resolve(path: Union[str, Path]) -> Path:
    """Return *path* as an absolute path; relative paths are anchored at the repo root."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p
