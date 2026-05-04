from __future__ import annotations

import json

from orchesjob_reserver.db import connect, init_db
from orchesjob_reserver.dispatcher import log_expired_reservations
from orchesjob_reserver.reservations import (
    STATUS_EXPIRED,
    clean_reservations,
    create_reservation,
    fetch_by_run_key,
    mark_dispatched,
)
from orchesjob_reserver.utils import epoch_now


def test_clean_by_reservation_id_deletes_terminal_reservation(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="rid", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "rid")
        assert row is not None
        rid = row["reservation_id"]
        mark_dispatched(conn, reservation_id=rid, job_id="job-rid")
        deleted, candidates = clean_reservations(
            conn,
            before=None,
            after=None,
            all_=False,
            job_id=None,
            reservation_id=rid,
            run_key=None,
            dry_run=False,
        )
        assert deleted == 1
        assert len(candidates) == 1
        assert fetch_by_run_key(conn, "rid") is None


def test_clean_by_reservation_id_does_not_delete_reserved(db_path: str) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="reserved-rid", command=["/bin/echo"], not_before=None, expires_at=None, metadata_json=None)
        row = fetch_by_run_key(conn, "reserved-rid")
        assert row is not None
        deleted, candidates = clean_reservations(
            conn,
            before=None,
            after=None,
            all_=False,
            job_id=None,
            reservation_id=row["reservation_id"],
            run_key=None,
            dry_run=False,
        )
        assert deleted == 0
        assert candidates == []
        assert fetch_by_run_key(conn, "reserved-rid") is not None


def test_log_expired_reservations_outputs_json_line(db_path: str, capsys) -> None:
    now = epoch_now()
    with connect(db_path) as conn:
        init_db(conn)
        create_reservation(conn, run_key="expire-me", command=["/bin/echo", "expired"], not_before=None, expires_at=now - 1, metadata_json=None)
        count = log_expired_reservations(conn)
        row = fetch_by_run_key(conn, "expire-me")
    payload = json.loads(capsys.readouterr().out.strip())
    assert count == 1
    assert row is not None
    assert row["reservation_status"] == STATUS_EXPIRED
    assert payload["event"] == "reservation_expired"
    assert payload["run_key"] == "expire-me"
    assert payload["reservation_status"] == STATUS_EXPIRED
    assert payload["command"] == ["/bin/echo", "expired"]
