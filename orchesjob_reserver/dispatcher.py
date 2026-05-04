from __future__ import annotations

import signal
import sqlite3
import time
from typing import Any

from .config import Config
from .db import connect, init_db, transaction
from .log import log_json_line, log_json_line_error
from .orchesjob_client import build_start_command, start as orchesjob_start
from .reservations import (
    claim_for_dispatch,
    decode_command,
    decode_orchesjob_start_options,
    expire_due_reservations,
    expire_due_reservations_for_log,
    mark_dispatch_failed,
    mark_dispatched,
    recover_dispatching,
    select_ready_reservation,
)
from .utils import epoch_now


def log_unseen_reservations(
    conn: sqlite3.Connection,
    seen_reservation_ids: set[str],
    *,
    created_at_from: int,
) -> int:
    """Log reservations created after this run process started.

    This avoids emitting old DISPATCHED history every time supervisor restarts run.
    """
    rows = conn.execute(
        """
        SELECT reservation_id,
               run_key,
               reservation_status,
               command_json,
               orchesjob_start_options_json,
               not_before,
               expires_at,
               created_at
          FROM reservations
         WHERE created_at >= ?
         ORDER BY created_at, reservation_id
        """,
        (created_at_from,),
    ).fetchall()

    count = 0
    for row in rows:
        reservation_id = row["reservation_id"]
        if reservation_id in seen_reservation_ids:
            continue

        seen_reservation_ids.add(reservation_id)
        count += 1

        try:
            command = decode_command(row)
        except Exception:
            command = None

        try:
            start_options = list(decode_orchesjob_start_options(row))
        except Exception:
            start_options = None

        log_json_line(
            "reservation_accepted",
            reservation_id=reservation_id,
            run_key=row["run_key"],
            reservation_status=row["reservation_status"],
            command=command,
            orchesjob_start_options=start_options,
            not_before=row["not_before"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )

    return count


def log_expired_reservations(conn: sqlite3.Connection) -> int:
    expired = expire_due_reservations_for_log(conn, epoch_now())
    for row in expired:
        log_json_line(
            "reservation_expired",
            reservation_id=row["reservation_id"],
            run_key=row["run_key"],
            reservation_status=row["reservation_status"],
            command=row.get("command"),
            not_before=row.get("not_before"),
            expires_at=row.get("expires_at"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_error=row.get("last_error"),
        )
    return len(expired)


def dispatch_one(conn: sqlite3.Connection, cfg: Config) -> bool:
    now = epoch_now()

    with transaction(conn):
        expire_due_reservations(conn, now)
        row = select_ready_reservation(conn, now)
        if row is None:
            return False

        claimed = claim_for_dispatch(conn, row, now)
        if claimed is None:
            return False

    try:
        command = decode_command(claimed)
        reservation_start_options = decode_orchesjob_start_options(claimed)
        start_options = cfg.orchesjob_start_options + reservation_start_options
        start_command = build_start_command(
            orchesjob_bin=cfg.orchesjob_bin,
            run_key=claimed["run_key"],
            command=command,
            start_options=start_options,
        )
        log_json_line(
            "orchesjob_start_call",
            reservation_id=claimed["reservation_id"],
            run_key=claimed["run_key"],
            command=start_command,
        )
        job_id = orchesjob_start(
            orchesjob_bin=cfg.orchesjob_bin,
            run_key=claimed["run_key"],
            command=command,
            start_options=start_options,
        )
    except Exception as exc:
        error = str(exc)
        mark_dispatch_failed(conn, reservation_id=claimed["reservation_id"], error=error)
        log_json_line(
            "dispatch_failed",
            reservation_id=claimed["reservation_id"],
            run_key=claimed["run_key"],
            error=error,
        )
        return True

    mark_dispatched(conn, reservation_id=claimed["reservation_id"], job_id=job_id)
    log_json_line(
        "dispatch_succeeded",
        reservation_id=claimed["reservation_id"],
        run_key=claimed["run_key"],
        job_id=job_id,
    )
    return True


def run_dispatcher(
    *,
    db: str,
    orchesjob_bin: str,
    orchesjob_start_options: tuple[str, ...],
    poll_interval: float,
    error_sleep: float,
) -> None:
    cfg = Config(db=db, orchesjob_bin=orchesjob_bin, orchesjob_start_options=orchesjob_start_options)
    stop = False

    def handle_signal(signum: int, frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    with connect(cfg.db) as conn:
        init_db(conn)
        recovered = recover_dispatching(conn)
        if recovered:
            log_json_line("recovered_dispatching", count=recovered)

        run_started_at = epoch_now()

        log_json_line(
            "reserver_started",
            db=cfg.db,
            orchesjob_bin=cfg.orchesjob_bin,
            orchesjob_start_options=list(cfg.orchesjob_start_options),
            poll_interval=poll_interval,
            run_started_at=run_started_at,
        )

        seen_reservation_ids: set[str] = set()

        while not stop:
            try:
                logged_count = log_unseen_reservations(
                    conn,
                    seen_reservation_ids,
                    created_at_from=run_started_at,
                )
                expired_count = log_expired_reservations(conn)
                did_work = dispatch_one(conn, cfg)
                if not did_work and logged_count == 0 and expired_count == 0:
                    time.sleep(poll_interval)
            except Exception as exc:
                log_json_line_error("dispatcher_error", error=str(exc))
                time.sleep(error_sleep)

    log_json_line("reserver_stopped")
