from __future__ import annotations

import datetime as dt

from orchesjob_reserver.db import connect, init_db
from orchesjob_reserver.reservations import (
    STATUS_CANCELLED,
    STATUS_DISPATCHED,
    STATUS_DISPATCHING,
    STATUS_EXPIRED,
    STATUS_RESERVED,
    cancel_before_dispatch,
    claim_for_dispatch,
    clean_reservations,
    create_reservation,
    expire_due_reservations,
    fetch_by_run_key,
    list_reservations,
    mark_dispatched,
    recover_dispatching,
    select_ready_reservation,
)
from orchesjob_reserver.utils import epoch_now


def test_create_reservation_is_idempotent_by_run_key(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        created1, r1 = create_reservation(
            conn,
            run_key="dag/task/1",
            command=["/bin/echo", "hello"],
            not_before=None,
            expires_at=None,
            metadata_json=None,
        )
        created2, r2 = create_reservation(
            conn,
            run_key="dag/task/1",
            command=["/bin/echo", "changed"],
            not_before=None,
            expires_at=None,
            metadata_json=None,
        )

    assert created1 is True
    assert created2 is False
    assert r1["reservation_id"] == r2["reservation_id"]
    assert r2["command"] == ["/bin/echo", "hello"]


def test_select_ready_reservation_respects_not_before(db_path: str) -> None:
    future = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).timestamp())

    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="future", command=["/bin/echo"], not_before=future, expires_at=None, metadata_json=None)
        create_reservation(conn, run_key="ready", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)

        row = select_ready_reservation(conn, epoch_now())

    assert row is not None
    assert row["run_key"] == "ready"


def test_claim_for_dispatch_moves_reserved_to_dispatching(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="claim", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "claim")
        assert row is not None

        claimed = claim_for_dispatch(conn, row, epoch_now())
        assert claimed is not None
        assert claimed["reservation_status"] == STATUS_DISPATCHING

        again = claim_for_dispatch(conn, row, epoch_now())
        assert again is None


def test_mark_dispatched_stores_job_id(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="dispatched", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "dispatched")
        assert row is not None
        claimed = claim_for_dispatch(conn, row, epoch_now())
        assert claimed is not None
        mark_dispatched(conn, reservation_id=claimed["reservation_id"], job_id="job-123")
        updated = fetch_by_run_key(conn, "dispatched")

    assert updated is not None
    assert updated["reservation_status"] == STATUS_DISPATCHED
    assert updated["job_id"] == "job-123"
    assert isinstance(updated["dispatched_at"], int)


def test_recover_dispatching_returns_records_to_reserved(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="recover", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "recover")
        assert row is not None
        claimed = claim_for_dispatch(conn, row, epoch_now())
        assert claimed is not None
        recovered = recover_dispatching(conn)
        updated = fetch_by_run_key(conn, "recover")

    assert recovered == 1
    assert updated is not None
    assert updated["reservation_status"] == STATUS_RESERVED


def test_expire_due_reservations_only_before_dispatch(db_path: str) -> None:
    past = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).timestamp())

    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="expired", command=["/bin/echo"], not_before=None, expires_at=past, metadata_json=None)
        expired = expire_due_reservations(conn, epoch_now())
        row = fetch_by_run_key(conn, "expired")

    assert expired == 1
    assert row is not None
    assert row["reservation_status"] == STATUS_EXPIRED


def test_cancel_before_dispatch(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="cancel", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "cancel")
        assert row is not None
        cancelled = cancel_before_dispatch(conn, row)

    assert cancelled["reservation_status"] == STATUS_CANCELLED


def test_clean_reservations_deletes_dispatched_only(db_path: str) -> None:
    before = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).timestamp())

    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="keep", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        create_reservation(conn, run_key="delete", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "delete")
        assert row is not None
        claimed = claim_for_dispatch(conn, row, epoch_now())
        assert claimed is not None
        mark_dispatched(conn, reservation_id=claimed["reservation_id"], job_id="job-1")

        deleted, candidates = clean_reservations(conn, before=before, after=None, all_=False, job_id=None, run_key=None, dry_run=False)
        rows = list_reservations(conn, status=None, limit=10)

    assert deleted == 1
    assert len(candidates) == 1
    assert [r["run_key"] for r in rows] == ["keep"]
