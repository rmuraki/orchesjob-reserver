from __future__ import annotations

import json

import pytest

from orchesjob_reserver.db import connect, init_db
from orchesjob_reserver.dispatcher import log_unseen_reservations
from orchesjob_reserver.reservations import clean_reservations, create_reservation, fetch_by_run_key, mark_dispatched
from orchesjob_reserver.utils import epoch_now


def test_log_unseen_reservations_does_not_emit_old_dispatched_on_run_start(db_path: str, capsys) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="old", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "old")
        assert row is not None
        mark_dispatched(conn, reservation_id=row["reservation_id"], job_id="job-old")

        seen: set[str] = set()
        count = log_unseen_reservations(conn, seen, created_at_from=epoch_now() + 10)

    assert count == 0
    assert capsys.readouterr().out == ""


def test_log_unseen_reservations_emits_new_reservation(db_path: str, capsys) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        run_started_at = epoch_now()
        create_reservation(conn, run_key="new", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        seen: set[str] = set()
        count = log_unseen_reservations(conn, seen, created_at_from=run_started_at)

    assert count == 1
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "reservation_accepted"
    assert payload["run_key"] == "new"


def test_clean_dry_run_does_not_delete(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="rk", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "rk")
        assert row is not None
        mark_dispatched(conn, reservation_id=row["reservation_id"], job_id="job-rk")

        deleted, candidates = clean_reservations(conn, before=None, after=None, all_=True, job_id=None, run_key=None, dry_run=True)
        remaining = fetch_by_run_key(conn, "rk")

    assert deleted == 0
    assert len(candidates) == 1
    assert remaining is not None


def test_clean_by_job_id_deletes_terminal_only(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="rk", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "rk")
        assert row is not None
        mark_dispatched(conn, reservation_id=row["reservation_id"], job_id="job-rk")

        deleted, candidates = clean_reservations(conn, before=None, after=None, all_=False, job_id="job-rk", run_key=None, dry_run=False)
        remaining = fetch_by_run_key(conn, "rk")

    assert deleted == 1
    assert len(candidates) == 1
    assert remaining is None


def test_clean_does_not_delete_reserved_even_with_all(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="reserved", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)

        deleted, candidates = clean_reservations(conn, before=None, after=None, all_=True, job_id=None, run_key=None, dry_run=False)
        remaining = fetch_by_run_key(conn, "reserved")

    assert deleted == 0
    assert candidates == []
    assert remaining is not None


def test_clean_job_id_conflict_raises(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        with pytest.raises(Exception, match="--job-id cannot be combined"):
            clean_reservations(conn, before=None, after=None, all_=True, job_id="job-1", run_key=None, dry_run=True)
