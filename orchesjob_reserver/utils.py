from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any, Optional

from .errors import CliError


def epoch_now() -> int:
    return int(time.time())


def parse_epoch_seconds(value: Optional[str], *, field_name: str) -> Optional[int]:
    """Parse epoch seconds or an ISO 8601 datetime string into epoch seconds."""
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        raise CliError(f"Invalid {field_name}: empty value.")

    if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
        return int(stripped)

    try:
        parsed = dt.datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CliError(
            f"Invalid {field_name}: {value!r}. Expected epoch seconds or ISO 8601 datetime."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.astimezone()

    return int(parsed.timestamp())


def epoch_to_iso(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).isoformat(timespec="seconds")


def parse_json_object(value: Optional[str], *, field_name: str) -> Optional[str]:
    if value is None:
        return None

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid {field_name}: must be valid JSON object.") from exc

    if not isinstance(parsed, dict):
        raise CliError(f"Invalid {field_name}: must be a JSON object.")

    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))


def row_to_dict(row: Any, *, include_iso_time: bool = True) -> dict[str, Any]:
    d = dict(row)

    for key in ("command_json", "metadata_json", "orchesjob_start_options_json"):
        if d.get(key):
            try:
                d[key.removesuffix("_json")] = json.loads(d[key])
            except json.JSONDecodeError:
                d[key.removesuffix("_json")] = d[key]
            del d[key]

    if include_iso_time:
        for key in ("not_before", "expires_at", "created_at", "updated_at", "dispatched_at"):
            if d.get(key) is not None:
                d[f"{key}_iso"] = epoch_to_iso(int(d[key]))

    return d
