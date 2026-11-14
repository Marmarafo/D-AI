"""Cross-platform data/config directory resolution (Linux, Windows, Termux)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "dai"


def data_dir() -> Path:
    env = os.environ.get("DAI_HOME")
    if env:
        p = Path(env).expanduser()
    elif sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        p = Path(base) / APP
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        p = Path(base) / APP
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    env = os.environ.get("DAI_CONFIG")
    if env:
        return Path(env).expanduser()
    return data_dir() / "config.toml"


def default_db_path() -> Path:
    return data_dir() / "dai.sqlite3"


def is_shared_storage(path) -> bool:
    """Android shared storage is unreliable for SQLite locking."""
    s = str(path).replace("\\", "/")
    return s.startswith(("/sdcard", "/storage/emulated", "/storage/self"))
