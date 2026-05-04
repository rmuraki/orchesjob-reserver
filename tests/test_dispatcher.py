from __future__ import annotations

from orchesjob_reserver.config import Config
from orchesjob_reserver.db import connect, init_db
from orchesjob_reserver.dispatcher import dispatch_one
from orchesjob_reserver.reservations import (
    STATUS_DISPATCHED,
    STATUS_DISPATCH_FAILED,
    create_reservation,
    fetch_by_run_key,
)


def test_dispatch_one_starts_orchesjob_and_stores_job_id(db_path: str, fake_orchesjob: str) -> None:
    cfg = Config(db=db_path, orchesjob_bin=fake_orchesjob)

    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="dag/task/success", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        did_work = dispatch_one(conn, cfg)
        row = fetch_by_run_key(conn, "dag/task/success")

    assert did_work is True
    assert row is not None
    assert row["reservation_status"] == STATUS_DISPATCHED
    assert row["job_id"] == "job-dag_task_success"


def test_dispatch_one_marks_dispatch_failed_when_orchesjob_start_fails(db_path: str, fake_orchesjob: str) -> None:
    cfg = Config(db=db_path, orchesjob_bin=fake_orchesjob)

    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="dag/task/fail-start", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        did_work = dispatch_one(conn, cfg)
        row = fetch_by_run_key(conn, "dag/task/fail-start")

    assert did_work is True
    assert row is not None
    assert row["reservation_status"] == STATUS_DISPATCH_FAILED
    assert "simulated start failure" in row["last_error"]


def test_dispatch_one_returns_false_when_no_ready_reservation(db_path: str, fake_orchesjob: str) -> None:
    cfg = Config(db=db_path, orchesjob_bin=fake_orchesjob)

    with connect(db_path) as conn:
        init_db(conn)
        did_work = dispatch_one(conn, cfg)

    assert did_work is False


def test_dispatch_passes_orchesjob_start_options(db_path: str, fake_orchesjob: str) -> None:
    cfg = Config(db=db_path, orchesjob_bin=fake_orchesjob, orchesjob_start_options=("--strict", "--bypass"))

    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="dag/task/options", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        did_work = dispatch_one(conn, cfg)
        row = fetch_by_run_key(conn, "dag/task/options")

    assert did_work is True
    assert row is not None
    assert row["job_id"] == "job-dag_task_options"
