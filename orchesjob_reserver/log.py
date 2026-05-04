from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Any


def current_time() -> dt.datetime:
    return dt.datetime.now().astimezone()


def build_log_payload(event: str, **fields: Any) -> dict[str, Any]:
    now = current_time()
    return {
        "ts": now.isoformat(timespec="seconds"),
        "ts_epoch": int(now.timestamp()),
        "event": event,
        **fields,
    }


def log_json_line(event: str, **fields: Any) -> None:
    print(
        json.dumps(build_log_payload(event, **fields), ensure_ascii=False, sort_keys=True),
        flush=True,
    )


def log_json_line_error(event: str, **fields: Any) -> None:
    print(
        json.dumps(build_log_payload(event, **fields), ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
        flush=True,
    )
