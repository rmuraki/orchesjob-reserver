from __future__ import annotations

import json
import shlex
import subprocess
import sys
from typing import Any

from .errors import ReserverError


def call_orchesjob_json(cmd: list[str], *, allow_non_json: bool = False) -> Any:
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    if completed.returncode != 0:
        raise ReserverError(
            "orchesjob command failed: "
            + shlex.join(cmd)
            + f"\nexit_code={completed.returncode}\nstderr={completed.stderr.strip()}"
        )

    stdout = completed.stdout.strip()
    if not stdout:
        return None

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        if allow_non_json:
            return {"raw_stdout": completed.stdout, "raw_stderr": completed.stderr}
        raise ReserverError(f"orchesjob returned non-JSON output: {stdout[:500]}")


def extract_job_id(start_output: Any) -> str:
    if not isinstance(start_output, dict):
        raise ReserverError("orchesjob start did not return a JSON object.")

    job_id = start_output.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ReserverError("orchesjob start output does not contain job_id.")

    return job_id


def build_start_command(
    *,
    orchesjob_bin: str,
    run_key: str,
    command: list[str],
    start_options: tuple[str, ...] = (),
) -> list[str]:
    # start_options are passed through to `orchesjob start` before `--`.
    return [orchesjob_bin, "start", "--run-key", run_key, *start_options, "--", *command]


def start(
    *,
    orchesjob_bin: str,
    run_key: str,
    command: list[str],
    start_options: tuple[str, ...] = (),
) -> str:
    start_cmd = build_start_command(
        orchesjob_bin=orchesjob_bin,
        run_key=run_key,
        command=command,
        start_options=start_options,
    )
    start_output = call_orchesjob_json(start_cmd)
    return extract_job_id(start_output)


def status(*, orchesjob_bin: str, job_id: str) -> Any:
    return call_orchesjob_json([orchesjob_bin, "status", "--job-id", job_id], allow_non_json=True)


def proxy_result(*, orchesjob_bin: str, job_id: str) -> int:
    return _proxy([orchesjob_bin, "result", "--job-id", job_id])


def proxy_cancel(*, orchesjob_bin: str, job_id: str) -> int:
    return _proxy([orchesjob_bin, "cancel", "--job-id", job_id])


def _proxy(cmd: list[str]) -> int:
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)

    return completed.returncode
