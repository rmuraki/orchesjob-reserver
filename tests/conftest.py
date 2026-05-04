from __future__ import annotations

import stat
from pathlib import Path

import pytest


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "reserver.sqlite3")


@pytest.fixture
def fake_orchesjob(tmp_path: Path) -> str:
    script = tmp_path / "orchesjob"
    script.write_text(
        '''#!/usr/bin/env bash
set -u
cmd="${1:-}"
shift || true
run_key=""
job_id=""
strict=false
bypass=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --run-key)
      shift
      run_key="${1:-}"
      ;;
    --job-id)
      shift
      job_id="${1:-}"
      ;;
    --strict)
      strict=true
      ;;
    --bypass)
      bypass=true
      ;;
    --)
      break
      ;;
  esac
  shift || true
done

case "$cmd" in
  start)
    if [ -z "$run_key" ]; then echo "missing --run-key" >&2; exit 2; fi
    if [[ "$run_key" == *fail-start* ]]; then echo "simulated start failure" >&2; exit 10; fi
    safe="$(printf '%s' "$run_key" | tr '/:' '__')"
    printf '{"job_id":"job-%s","run_key":"%s","status":"RUNNING","strict":%s,"bypass":%s}\n' "$safe" "$run_key" "$strict" "$bypass"
    ;;
  status)
    if [ -z "$job_id" ]; then echo "missing --job-id" >&2; exit 2; fi
    status=RUNNING
    if [[ "$job_id" == *done* ]]; then status=SUCCEEDED; fi
    printf '{"job_id":"%s","status":"%s"}\n' "$job_id" "$status"
    ;;
  result)
    if [ -z "$job_id" ]; then echo "missing --job-id" >&2; exit 2; fi
    printf '{"job_id":"%s","result":"ok"}\n' "$job_id"
    ;;
  cancel)
    if [ -z "$job_id" ]; then echo "missing --job-id" >&2; exit 2; fi
    printf '{"job_id":"%s","cancelled":true}\n' "$job_id"
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
''',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)
