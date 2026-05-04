from __future__ import annotations

import datetime as dt
import json

from orchesjob_reserver.log import build_log_payload, log_json_line


def test_build_log_payload_has_iso_ts_and_epoch() -> None:
    payload = build_log_payload("sample_event", run_key="rk")

    assert payload["event"] == "sample_event"
    assert payload["run_key"] == "rk"
    assert isinstance(payload["ts"], str)
    assert isinstance(payload["ts_epoch"], int)

    parsed = dt.datetime.fromisoformat(payload["ts"])
    assert parsed.tzinfo is not None


def test_log_json_line_outputs_iso_ts_and_epoch(capsys) -> None:
    log_json_line("sample_event", reservation_id="rid")

    payload = json.loads(capsys.readouterr().out.strip())

    assert payload["event"] == "sample_event"
    assert payload["reservation_id"] == "rid"
    assert isinstance(payload["ts"], str)
    assert isinstance(payload["ts_epoch"], int)
    assert dt.datetime.fromisoformat(payload["ts"]).tzinfo is not None
