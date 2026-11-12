"""Optional add-ons for BotLi that do not touch its own config parser.

Everything here is read from `extras.yml` next to the bot. If the file is missing every
feature is off, so the bot behaves exactly as before.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "mistakes": {
        "enabled": True,
        "file": "mistakes.json",
    },
    "clock": {
        "enabled": True,
        "bullet_only": True,
        "low_time_threshold": 8.0,
        "horizon": 30,
        "min_time": 0.04,
        "max_time": 0.25,
    },
}

_config: dict[str, Any] | None = None


def config(path: str = "extras.yml") -> dict[str, Any]:
    """Return the add-on settings, loading them once per process."""
    global _config
    if _config is not None:
        return _config

    merged = {section: dict(values) for section, values in DEFAULTS.items()}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            for section, values in loaded.items():
                if isinstance(values, dict) and section in merged:
                    merged[section].update(values)
                else:
                    merged[section] = values
            logger.info(f"Loaded add-on settings from {path}")
        except (OSError, yaml.YAMLError) as error:
            logger.warning(f"Could not read {path}: {error}")
    _config = merged
    return _config


def section(name: str) -> dict[str, Any]:
    """Return one add-on section."""
    return config().get(name) or {}