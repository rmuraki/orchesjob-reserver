from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Optional

from .db import transaction
from .errors import CliError
from .utils import epoch_now, json_dumps, row_to_dict


STATUS_RESERVED = "RESERVED"
STATUS_DISPATCHING = "DISPATCHING"
STATUS_DISPATCHED = "DISPATCHED"
STATUS_CANCELLED = "CANCELLED"
STATUS_EXPIRED = "EXPIRED"
STATUS_DISPATCH_FAILED = "DISPATCH_FAILED"

RESERVATION_STATUSES = [
    STATUS_RESERVED,
    STATUS_DISPATCHING,
    STATUS_DISPATCHED,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_DISPATCH_FAILED,
]

TERMINAL_RESERVATION_STATUSES = {
    STATUS_DISPATCHED,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_DISPATCH_FAILED,
}


def fetch_by_run_key(conn: sqlite3.Connection, run_key: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM reservations WHERE run_key = ?", (run_key,)).fetchone()


def fetch_by_reservation_id(conn: sqlite3.Connection, reservation_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)).fetchone()


def resolve_reservation(
    conn: sqlite3.Connection,
    *,
    run_key: Optional[str],
    reservation_id: Optional[str],
) -> sqlite3.Row:
    if bool(run_key) == bool(reservation_id):
        raise CliError("Specify exactly one of --run-key or --reservation-id.")

    row = fetch_by_run_key(conn, run_key) if run_key else fetch_by_reservation_id(conn, reservation_id)  # type: ignore[arg-type]
    if row is None:
        raise CliError("Reservation not found.", exit_code=4)

    return row


def create_reservation(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    command: list[str],
    not_before: Optional[int],
    expires_at: Optional[int],
    metadata_json: Optional[str],
    orchesjob_start_options: tuple[str, ...] = (),
) -> tuple[bool, dict[str, Any]]:
    command_json = json_dumps(command)
    orchesjob_start_options_json = json_dumps(list(orchesjob_start_options))
    now = epoch_now()
    reservation_id = str(uuid.uuid4())

    with transaction(conn):
        existing = fetch_by_run_key(conn, run_key)
        if existing is not None:
            return False, row_to_dict(existing)

        conn.execute(
            """
            INSERT INTO reservations (
              reservation_id,
              run_key,
              command_json,
              reservation_status,
              job_id,
              not_before,
              expires_at,
              metadata_json,
              orchesjob_start_options_json,
              created_at,
              updated_at,
              dispatched_at,
              last_error
            ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                reservation_id,
                run_key,
                command_json,
                STATUS_RESERVED,
                not_before,
                expires_at,
                metadata_json,
                orchesjob_start_options_json,
                now,
                now,
            ),
        )

        row = fetch_by_run_key(conn, run_key)
        assert row is not None
        return True, row_to_dict(row)


def list_reservations(conn: sqlite3.Connection, *, status: Optional[str], limit: int) -> list[dict[str, Any]]:
    params: list[Any] = []
    where: list[str] = []

    if status:
        where.append("reservation_status = ?")
        params.append(status)

    sql = "SELECT * FROM reservations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]


def cancel_before_dispatch(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    now = epoch_now()

    with transaction(conn):
        conn.execute(
            """
            UPDATE reservations
               SET reservation_status = ?, updated_at = ?, last_error = NULL
             WHERE reservation_id = ?
            """,
            (STATUS_CANCELLED, now, row["reservation_id"]),
        )
        updated = fetch_by_reservation_id(conn, row["reservation_id"])
        assert updated is not None
        return row_to_dict(updated)


def build_clean_where(
    *,
    before: int | None,
    after: int | None,
    all_: bool,
    job_id: str | None,
    run_key: str | None,
    reservation_id: str | None = None,
) -> tuple[str, list[Any]]:
    """Build WHERE clause for terminal reservation deletion."""
    if job_id and reservation_id:
        raise CliError("--job-id and --reservation-id cannot be combined.")

    if job_id and (before is not None or after is not None or all_ or run_key):
        raise CliError("--job-id cannot be combined with --all, --before, --after, or --run-key.")

    if reservation_id and (before is not None or after is not None or all_ or run_key):
        raise CliError("--reservation-id cannot be combined with --all, --before, --after, or --run-key.")

    if not job_id and not reservation_id and not all_ and before is None and after is None:
        raise CliError("Specify --all, --job-id, --reservation-id, --before, or --after.")

    where = ["reservation_status IN (?, ?, ?, ?)"]
    params: list[Any] = [
        STATUS_DISPATCHED,
        STATUS_CANCELLED,
        STATUS_EXPIRED,
        STATUS_DISPATCH_FAILED,
    ]

    if job_id:
        where.append("job_id = ?")
        params.append(job_id)
    elif reservation_id:
        where.append("reservation_id = ?")
        params.append(reservation_id)
    else:
        if run_key:
            where.append("run_key = ?")
            params.append(run_key)
        if before is not None:
            where.append("updated_at < ?")
            params.append(before)
        if after is not None:
            where.append("updated_at >= ?")
            params.append(after)

    return " AND ".join(where), params


def select_clean_candidates(
    conn: sqlite3.Connection,
    *,
    before: int | None,
    after: int | None,
    all_: bool,
    job_id: str | None,
    run_key: str | None,
    reservation_id: str | None = None,
) -> list[dict[str, Any]]:
    where, params = build_clean_where(
        before=before,
        after=after,
        all_=all_,
        job_id=job_id,
        reservation_id=reservation_id,
        run_key=run_key,
    )
    rows = conn.execute(
        f"""
        SELECT *
          FROM reservations
         WHERE {where}
         ORDER BY updated_at, reservation_id
        """,
        params,
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def clean_reservations(
    conn: sqlite3.Connection,
    *,
    before: int | None,
    after: int | None,
    all_: bool,
    job_id: str | None,
    run_key: str | None,
    dry_run: bool,
    reservation_id: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    candidates = select_clean_candidates(
        conn,
        before=before,
        after=after,
        all_=all_,
        job_id=job_id,
        reservation_id=reservation_id,
        run_key=run_key,
    )

    if dry_run or not candidates:
        return 0, candidates

    ids = [row["reservation_id"] for row in candidates]
    placeholders = ",".join("?" for _ in ids)

    with transaction(conn):
        cur = conn.execute(
            f"DELETE FROM reservations WHERE reservation_id IN ({placeholders})",
            ids,
        )
        return cur.rowcount, candidates


def expire_due_reservations_for_log(conn: sqlite3.Connection, now: int) -> list[dict[str, Any]]:
    """Expire due RESERVED reservations and return rows for JSON Lines logging."""
    rows = conn.execute(
        """
        SELECT *
          FROM reservations
         WHERE reservation_status = ?
           AND expires_at IS NOT NULL
           AND expires_at <= ?
         ORDER BY expires_at, reservation_id
        """,
        (STATUS_RESERVED, now),
    ).fetchall()

    if not rows:
        return []

    ids = [row["reservation_id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)

    with transaction(conn):
        cur = conn.execute(
            f"""
            UPDATE reservations
               SET reservation_status = ?, updated_at = ?, last_error = 'expired before dispatch'
             WHERE reservation_id IN ({placeholders})
               AND reservation_status = ?
            """,
            [STATUS_EXPIRED, now, *ids, STATUS_RESERVED],
        )
        if cur.rowcount == 0:
            return []

        updated = conn.execute(
            f"""
            SELECT *
              FROM reservations
             WHERE reservation_id IN ({placeholders})
             ORDER BY expires_at, reservation_id
            """,
            ids,
        ).fetchall()

    return [row_to_dict(row) for row in updated]



def expire_due_reservations(conn: sqlite3.Connection, now: int) -> int:
    cur = conn.execute(
        """
        UPDATE reservations
           SET reservation_status = ?, updated_at = ?, last_error = 'expired before dispatch'
         WHERE reservation_status = ?
           AND expires_at IS NOT NULL
           AND expires_at <= ?
        """,
        (STATUS_EXPIRED, now, STATUS_RESERVED, now),
    )
    return cur.rowcount


def recover_dispatching(conn: sqlite3.Connection) -> int:
    now = epoch_now()
    cur = conn.execute(
        """
        UPDATE reservations
           SET reservation_status = ?, updated_at = ?, last_error = 'recovered from DISPATCHING'
         WHERE reservation_status = ?
        """,
        (STATUS_RESERVED, now, STATUS_DISPATCHING),
    )
    return cur.rowcount


def select_ready_reservation(conn: sqlite3.Connection, now: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM reservations
         WHERE reservation_status = ?
           AND (not_before IS NULL OR not_before <= ?)
         ORDER BY COALESCE(not_before, created_at), created_at
         LIMIT 1
        """,
        (STATUS_RESERVED, now),
    ).fetchone()


def claim_for_dispatch(conn: sqlite3.Connection, row: sqlite3.Row, now: int) -> Optional[sqlite3.Row]:
    cur = conn.execute(
        """
        UPDATE reservations
           SET reservation_status = ?, updated_at = ?, last_error = NULL
         WHERE reservation_id = ?
           AND reservation_status = ?
        """,
        (STATUS_DISPATCHING, now, row["reservation_id"], STATUS_RESERVED),
    )
    if cur.rowcount != 1:
        return None

    return fetch_by_reservation_id(conn, row["reservation_id"])


def mark_dispatched(conn: sqlite3.Connection, *, reservation_id: str, job_id: str) -> None:
    now = epoch_now()
    with transaction(conn):
        conn.execute(
            """
            UPDATE reservations
               SET reservation_status = ?,
                   job_id = ?,
                   updated_at = ?,
                   dispatched_at = ?,
                   last_error = NULL
             WHERE reservation_id = ?
            """,
            (STATUS_DISPATCHED, job_id, now, now, reservation_id),
        )


def mark_dispatch_failed(conn: sqlite3.Connection, *, reservation_id: str, error: str) -> None:
    now = epoch_now()
    with transaction(conn):
        conn.execute(
            """
            UPDATE reservations
               SET reservation_status = ?, updated_at = ?, last_error = ?
             WHERE reservation_id = ?
            """,
            (STATUS_DISPATCH_FAILED, now, error[:4000], reservation_id),
        )


def decode_command(row: sqlite3.Row) -> list[str]:
    command = json.loads(row["command_json"])
    if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
        raise ValueError("command_json is invalid")
    return command


def decode_orchesjob_start_options(row: sqlite3.Row) -> tuple[str, ...]:
    options = json.loads(row["orchesjob_start_options_json"])
    if not isinstance(options, list) or not all(isinstance(x, str) for x in options):
        raise ValueError("orchesjob_start_options_json is invalid")
    return tuple(options)
