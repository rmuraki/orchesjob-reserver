from __future__ import annotations

import json

from orchesjob_reserver.cli import main
from orchesjob_reserver.config import Config
from orchesjob_reserver.db import connect, init_db
from orchesjob_reserver.dispatcher import dispatch_one


def test_cli_version(capsys) -> None:
    exit_code = main(["--version"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "orchesjob-reserver" in captured.out


def test_cli_reserve_creates_reservation(db_path: str, capsys) -> None:
    exit_code = main([
        "reserve",
        "--db", db_path,
        "--run-key", "dag/task/cli",
        "--metadata-json", '{"dag_id":"dag","task_id":"task"}',
        "--",
        "/bin/echo",
        "hello",
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["created"] is True
    assert payload["reservation"]["run_key"] == "dag/task/cli"
    assert payload["reservation"]["command"] == ["/bin/echo", "hello"]
    assert payload["reservation"]["metadata"] == {"dag_id": "dag", "task_id": "task"}
    assert isinstance(payload["reservation"]["created_at"], int)


def test_cli_reserve_is_idempotent(db_path: str, capsys) -> None:
    args = ["reserve", "--db", db_path, "--run-key", "dag/task/idem", "--", "/bin/echo", "hello"]

    assert main(args) == 0
    capsys.readouterr()

    assert main(args) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["created"] is False


def test_cli_status_include_job_proxies_orchesjob(db_path: str, fake_orchesjob: str, capsys) -> None:
    assert main(["reserve", "--db", db_path, "--run-key", "dag/task/done", "--", "/bin/echo"]) == 0
    capsys.readouterr()

    with connect(db_path) as conn:
        init_db(conn)
        assert dispatch_one(conn, Config(db=db_path, orchesjob_bin=fake_orchesjob)) is True
    capsys.readouterr()

    assert main([
        "status",
        "--db", db_path,
        "--orchesjob-bin", fake_orchesjob,
        "--run-key", "dag/task/done",
        "--include-job",
    ]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["reservation"]["reservation_status"] == "DISPATCHED"
    assert payload["job"]["status"] == "SUCCEEDED"


def test_cli_result_proxies_orchesjob_result(db_path: str, fake_orchesjob: str, capsys) -> None:
    assert main(["reserve", "--db", db_path, "--run-key", "dag/task/result", "--", "/bin/echo"]) == 0
    capsys.readouterr()

    with connect(db_path) as conn:
        init_db(conn)
        assert dispatch_one(conn, Config(db=db_path, orchesjob_bin=fake_orchesjob)) is True
    capsys.readouterr()

    assert main(["result", "--db", db_path, "--orchesjob-bin", fake_orchesjob, "--run-key", "dag/task/result"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["result"] == "ok"


def test_cli_invalid_metadata_returns_error(db_path: str, capsys) -> None:
    exit_code = main([
        "reserve",
        "--db", db_path,
        "--run-key", "bad-meta",
        "--metadata-json", '["not", "object"]',
        "--",
        "/bin/echo",
    ])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "must be a JSON object" in captured.err


def test_cli_reserve_stores_orchesjob_start_options(db_path: str, capsys) -> None:
    exit_code = main([
        "reserve",
        "--db", db_path,
        "--orchesjob-start-option=--strict",
        "--orchesjob-start-option=--bypass",
        "--run-key", "dag/task/options-cli",
        "--",
        "/bin/echo",
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["reservation"]["orchesjob_start_options"] == ["--strict", "--bypass"]
