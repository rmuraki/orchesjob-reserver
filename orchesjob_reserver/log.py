from __future__ import annotations

import json
import sys
from typing import Any

from .utils import epoch_now


def log_json_line(event: str, **fields: Any) -> None:
    payload = {"ts": epoch_now(), "event": event, **fields}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def log_json_line_error(event: str, **fields: Any) -> None:
    payload = {"ts": epoch_now(), "event": event, **fields}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr, flush=True)
