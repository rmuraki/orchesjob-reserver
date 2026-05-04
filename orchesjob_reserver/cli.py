from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .config import DEFAULT_ORCHESJOB_BIN, Config, get_default_db
from .db import connect, init_db
from .dispatcher import run_dispatcher
from .errors import CliError, ReserverError
from .orchesjob_client import proxy_cancel, proxy_result, status as orchesjob_status
from .reservations import (
    RESERVATION_STATUSES,
    STATUS_DISPATCH_FAILED,
    STATUS_EXPIRED,
    STATUS_RESERVED,
    cancel_before_dispatch,
    clean_reservations,
    create_reservation,
    list_reservations,
    resolve_reservation,
)
from .utils import parse_epoch_seconds, parse_json_object, print_json, row_to_dict
from .version import get_version


def add_common_args(parser: argparse.ArgumentParser) -> None:
    default_db = get_default_db()
    parser.add_argument("--db", default=default_db, help=f"SQLite DB path. Default: {default_db}")
    parser.add_argument(
        "--orchesjob-bin",
        default=DEFAULT_ORCHESJOB_BIN,
        help=f"orchesjob executable. Default: {DEFAULT_ORCHESJOB_BIN}",
    )
    parser.add_argument(
        "--orchesjob-start-option",
        action="append",
        default=[],
        metavar="OPTION",
        help=(
            "Option passed through to `orchesjob start` before `--`. "
            "For reserve, options are stored with the reservation. For run, options are global defaults. "
            "Repeatable. Example: --orchesjob-start-option=--strict"
        ),
    )


def identity_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-key")
    group.add_argument("--reservation-id")


def normalize_remainder_command(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        return command[1:]
    return command


def cfg_from_args(args: argparse.Namespace) -> Config:
    return Config(
        db=args.db,
        orchesjob_bin=args.orchesjob_bin,
        orchesjob_start_options=tuple(args.orchesjob_start_option),
    )


def cmd_reserve(args: argparse.Namespace) -> None:
    if not args.command:
        raise CliError("reserve requires command after --")

    not_before = parse_epoch_seconds(args.not_before, field_name="not_before")
    expires_at = parse_epoch_seconds(args.expires_at, field_name="expires_at")
    metadata_json = parse_json_object(args.metadata_json, field_name="metadata_json")

    with connect(args.db) as conn:
        init_db(conn)
        created, reservation = create_reservation(
            conn,
            run_key=args.run_key,
            command=args.command,
            not_before=not_before,
            expires_at=expires_at,
            metadata_json=metadata_json,
            orchesjob_start_options=tuple(args.orchesjob_start_option),
        )

    print_json({"created": created, "reservation": reservation})


def cmd_status(args: argparse.Namespace) -> None:
    cfg = cfg_from_args(args)

    with connect(cfg.db) as conn:
        init_db(conn)
        row = resolve_reservation(conn, run_key=args.run_key, reservation_id=args.reservation_id)
        reservation = row_to_dict(row)

    output = {"reservation": reservation}

    if args.include_job and reservation.get("job_id"):
        output["job"] = orchesjob_status(orchesjob_bin=cfg.orchesjob_bin, job_id=reservation["job_id"])

    print_json(output)


def cmd_result(args: argparse.Namespace) -> None:
    cfg = cfg_from_args(args)

    with connect(cfg.db) as conn:
        init_db(conn)
        row = resolve_reservation(conn, run_key=args.run_key, reservation_id=args.reservation_id)
        reservation = row_to_dict(row)

    job_id = reservation.get("job_id")
    if not job_id:
        raise CliError("Reservation has not been dispatched yet; job_id is not available.", exit_code=5)

    raise SystemExit(proxy_result(orchesjob_bin=cfg.orchesjob_bin, job_id=job_id))


def cmd_cancel(args: argparse.Namespace) -> None:
    cfg = cfg_from_args(args)

    with connect(cfg.db) as conn:
        init_db(conn)
        row = resolve_reservation(conn, run_key=args.run_key, reservation_id=args.reservation_id)
        status_value = row["reservation_status"]
        job_id = row["job_id"]

        if status_value in (STATUS_RESERVED, STATUS_DISPATCH_FAILED, STATUS_EXPIRED):
            updated = cancel_before_dispatch(conn, row)
            print_json({"cancelled": True, "reservation": updated})
            return

    if job_id:
        raise SystemExit(proxy_cancel(orchesjob_bin=cfg.orchesjob_bin, job_id=job_id))

    raise CliError(f"Cannot cancel reservation in status {status_value} without job_id.", exit_code=6)


def cmd_list(args: argparse.Namespace) -> None:
    with connect(args.db) as conn:
        init_db(conn)
        reservations = list_reservations(conn, status=args.status, limit=args.limit)

    print_json({"reservations": reservations})


def cmd_clean(args: argparse.Namespace) -> None:
    before = parse_epoch_seconds(args.before, field_name="before")
    after = parse_epoch_seconds(args.after, field_name="after")

    with connect(args.db) as conn:
        init_db(conn)
        deleted, candidates = clean_reservations(
            conn,
            before=before,
            after=after,
            all_=args.all,
            job_id=args.job_id,
            reservation_id=args.reservation_id,
            run_key=args.run_key,
            dry_run=args.dry_run,
        )

    print_json(
        {
            "deleted": deleted,
            "dry_run": args.dry_run,
            "matched": len(candidates),
            "reservations": candidates,
        }
    )


def cmd_run(args: argparse.Namespace) -> None:
    run_dispatcher(
        db=args.db,
        orchesjob_bin=args.orchesjob_bin,
        orchesjob_start_options=tuple(args.orchesjob_start_option),
        poll_interval=args.poll_interval,
        error_sleep=args.error_sleep,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchesjob-reserver")
    parser.add_argument("--version", action="version", version=f"%(prog)s {get_version()}")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p = sub.add_parser("reserve", help="Create an idempotent reservation")
    add_common_args(p)
    p.add_argument("--run-key", required=True)
    p.add_argument("--not-before", help="Epoch seconds or ISO 8601 datetime. Omit to dispatch as soon as possible.")
    p.add_argument("--expires-at", help="Epoch seconds or ISO 8601 datetime. If reached before dispatch, reservation expires.")
    p.add_argument("--metadata-json", help="JSON object metadata, e.g. Airflow dag_id/task_id/logical_date")
    p.add_argument("command", nargs=argparse.REMAINDER, help="Command after --")
    p.set_defaults(func=cmd_reserve)

    p = sub.add_parser("status", help="Show reservation status")
    add_common_args(p)
    identity_args(p)
    p.add_argument("--include-job", action="store_true", help="Proxy orchesjob status if job_id is available")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("result", help="Proxy orchesjob result by reservation")
    add_common_args(p)
    identity_args(p)
    p.set_defaults(func=cmd_result)

    p = sub.add_parser("cancel", help="Cancel reservation or proxy orchesjob cancel")
    add_common_args(p)
    identity_args(p)
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("list", help="List reservations")
    add_common_args(p)
    p.add_argument("--status", choices=RESERVATION_STATUSES)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser(
        "clean",
        help="Delete terminal reservation data",
        description=(
            "Delete terminal reservation data. RESERVED/DISPATCHING reservations are never deleted.\n\n"
            "Selection rules:\n"
            "  * Specify --all to delete all terminal reservation data.\n"
            "  * Specify --job-id to delete one terminal reservation.\n"
            "  * Specify --reservation-id to delete one terminal reservation.\n"
            "  * Otherwise, specify at least one of --before or --after.\n"
            "  * --before and --after may be combined as a range.\n"
            "  * --run-key may be combined with --all, --before, or --after.\n"
            "  * --job-id and --reservation-id cannot be combined with other selection options."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    add_common_args(p)
    p.add_argument("--before", metavar="DATETIME", help="Delete terminal reservations updated before this datetime")
    p.add_argument("--after", metavar="DATETIME", help="Delete terminal reservations updated at or after this datetime")
    p.add_argument("--all", action="store_true", help="Delete all matching terminal reservation data")
    p.add_argument("--job-id", metavar="JOB_ID", help="Delete a specific terminal reservation by job_id")
    p.add_argument("--reservation-id", metavar="RESERVATION_ID", help="Delete a specific terminal reservation by reservation_id")
    p.add_argument("--run-key", metavar="RUN_KEY", help="Restrict deletion to a run_key")
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="Preview without deleting")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("run", help="Run foreground dispatcher for supervisor")
    add_common_args(p)
    p.add_argument("--poll-interval", type=float, default=2.0)
    p.add_argument("--error-sleep", type=float, default=5.0)
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()

    try:
        args = parser.parse_args(argv)

        if hasattr(args, "command"):
            args.command = normalize_remainder_command(args.command)

        args.func(args)
        return 0
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code, file=sys.stderr)
        return 1
    except CliError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return exc.exit_code
    except ReserverError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
