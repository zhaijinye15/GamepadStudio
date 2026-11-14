"""用户设置持久化（%APPDATA%\\GamepadStudio\\settings.json）."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .paths import settings_file

DEFAULTS: Dict[str, Any] = {
    "deadzone": 0.18,
    "invert_ly": True,
    "invert_ry": True,
    "rumble_low": 0.6,
    "rumble_high": 0.9,
    "rumble_duration": 2.5,
    "rumble_pattern": "constant",
    "output_enabled": False,
    "show_raw": True,
    "last_profile": "",
    "window_size": [1220, 800],
}


def load_settings() -> Dict[str, Any]:
    path = settings_file()
    data = dict(DEFAULTS)
    try:
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except Exception:
        pass
    return data


def save_settings(data: Dict[str, Any]) -> None:
    path: Path = settings_file()
    try:
        path.write_text(json.dumps({k: data.get(k, DEFAULTS[k]) for k in DEFAULTS},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
