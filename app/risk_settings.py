"""Runtime risk settings for LazyBot FS.

The UI/API exposes these settings as user-controlled switches. The default
keeps the existing protective behavior unless the user explicitly disables it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


SETTINGS_FILE = Path(os.getenv("SCALPER_SETTINGS_FILE", "scalper_settings.json"))
DEFAULTS: dict[str, Any] = {
    "stop_loss_enabled": _env_bool("STOP_LOSS_ENABLED", True),
}


def load_settings() -> dict[str, Any]:
    settings = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                settings.update(saved)
        except (OSError, ValueError, TypeError):
            pass
    settings["stop_loss_enabled"] = bool(settings.get("stop_loss_enabled", True))
    return settings


def set_stop_loss_enabled(enabled: bool) -> dict[str, Any]:
    settings = load_settings()
    settings["stop_loss_enabled"] = bool(enabled)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(SETTINGS_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
    return settings
