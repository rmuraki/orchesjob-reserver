from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_HOME = "/var/lib/orchesjob"
DEFAULT_ORCHESJOB_BIN = os.environ.get("ORCHESJOB_BIN", "orchesjob")


def get_reserver_home() -> str:
    """Return the reserver home directory.

    Priority, low to high:
      1. /var/lib/orchesjob
      2. ORCHESJOB_HOME
      3. ORCHESJOB_RESERVER_HOME
    """
    return os.environ.get(
        "ORCHESJOB_RESERVER_HOME",
        os.environ.get("ORCHESJOB_HOME", DEFAULT_HOME),
    )


def get_default_db() -> str:
    return str(Path(get_reserver_home()) / "reserver.sqlite3")


DEFAULT_DB = get_default_db()


@dataclass(frozen=True)
class Config:
    db: str
    orchesjob_bin: str
    orchesjob_start_options: tuple[str, ...] = ()
