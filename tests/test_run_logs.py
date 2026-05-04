from __future__ import annotations

import json

from orchesjob_reserver.config import Config
from orchesjob_reserver.db import connect, init_db
from orchesjob_reserver.dispatcher import dispatch_one, log_unseen_reservations
from orchesjob_reserver.orchesjob_client import build_start_command
from orchesjob_reserver.reservations import create_reservation


def captured_lines(value: str) -> list[str]:
    return [line for line in value.splitlines() if line.strip()]


def test_build_start_command_includes_options_before_double_dash() -> None:
    cmd = build_start_command(
        orchesjob_bin="orchesjob",
        run_key="rk",
        command=["/bin/echo", "hello"],
        start_options=("--strict", "--bypass"),
    )
    assert cmd == [
        "orchesjob",
        "start",
        "--run-key",
        "rk",
        "--strict",
        "--bypass",
        "--",
        "/bin/echo",
        "hello",
    ]


def test_log_unseen_reservations_outputs_json_line(db_path: str, capsys) -> None:
    seen: set[str] = set()

    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(
            conn,
            run_key="dag/task/log",
            command=["/bin/echo", "hello"],
            orchesjob_start_options=("--strict",),
            not_before=None,
            expires_at=None,
            metadata_json=None,
        )

        count = log_unseen_reservations(conn, seen, created_at_from=0)

    captured = capsys.readouterr()
    line = json.loads(captured.out.strip())

    assert count == 1
    assert line["event"] == "reservation_accepted"
    assert line["run_key"] == "dag/task/log"
    assert line["command"] == ["/bin/echo", "hello"]
    assert line["orchesjob_start_options"] == ["--strict"]


def test_dispatch_one_logs_orchesjob_start_call_and_success(db_path: str, fake_orchesjob: str, capsys) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(
            conn,
            run_key="dag/task/log-dispatch",
            command=["/bin/echo", "hello"],
            orchesjob_start_options=("--bypass",),
            not_before=None,
            expires_at=None,
            metadata_json=None,
        )

        did_work = dispatch_one(
            conn,
            Config(db=db_path, orchesjob_bin=fake_orchesjob, orchesjob_start_options=("--strict",)),
        )

    assert did_work is True
    events = [json.loads(line) for line in captured_lines(capsys.readouterr().out)]
    assert [event["event"] for event in events] == ["orchesjob_start_call", "dispatch_succeeded"]
    assert events[0]["command"][1:] == [
        "start",
        "--run-key",
        "dag/task/log-dispatch",
        "--strict",
        "--bypass",
        "--",
        "/bin/echo",
        "hello",
    ]
