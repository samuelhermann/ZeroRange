"""config.json loading with an optional, git-ignored ``config.local.json`` overlay.

The overlay lets a trainer keep real UIDs / keys for their own kit out of the
repository: any key present in ``config.local.json`` replaces (or, for nested
objects, is merged into) the value from ``config.json``.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.paths import REPO_ROOT

logger = logging.getLogger(__name__)

CONFIG_PATH = REPO_ROOT / "config.json"
LOCAL_CONFIG_PATH = REPO_ROOT / "config.local.json"


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable config %s: %s", path, exc)
        return {}


def load_config(path: Optional[Path] = None, local_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load config.json merged with config.local.json (if present)."""
    base = _read_json(path or CONFIG_PATH)
    overlay = _read_json(local_path or LOCAL_CONFIG_PATH)
    return deep_merge(base, overlay) if overlay else base


def config_section(name: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a copy of one top-level section (``{}`` if missing)."""
    cfg = config if config is not None else load_config()
    section = cfg.get(name, {})
    return dict(section) if isinstance(section, dict) else {}


def lookup(config: Dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """Fetch ``a.b.c`` style keys from nested dicts."""
    node: Any = config
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
