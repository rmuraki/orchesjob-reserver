from __future__ import annotations

from pathlib import Path

from orchesjob_reserver.config import get_default_db, get_reserver_home


def test_home_priority_default_orchesjob_home_reserver_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ORCHESJOB_HOME", raising=False)
    monkeypatch.delenv("ORCHESJOB_RESERVER_HOME", raising=False)
    assert get_reserver_home() == "/var/lib/orchesjob"
    assert get_default_db() == "/var/lib/orchesjob/reserver.sqlite3"

    orch_home = tmp_path / "orch"
    monkeypatch.setenv("ORCHESJOB_HOME", str(orch_home))
    assert get_reserver_home() == str(orch_home)
    assert get_default_db() == str(orch_home / "reserver.sqlite3")

    reserver_home = tmp_path / "reserver"
    monkeypatch.setenv("ORCHESJOB_RESERVER_HOME", str(reserver_home))
    assert get_reserver_home() == str(reserver_home)
    assert get_default_db() == str(reserver_home / "reserver.sqlite3")
