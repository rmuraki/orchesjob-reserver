# orchesjob-reserver

## Overview

`orchesjob-reserver` is a lightweight reservation and dispatch agent for `orchesjob`.

It is intended for remote orchestration scenarios where a central orchestrator such as Apache Airflow, Amazon MWAA, cron, CI/CD pipelines, or SSH-based automation can reach an edge host only at certain points in time.

The key value is that the central orchestrator can **reserve a job with a future dispatch time**, then disconnect. The edge host keeps that intent locally and independently dispatches the job at or after the requested time. This makes the execution path less dependent on a continuously available SSH session or a healthy central worker at the exact execution moment.

A primary goal of `orchesjob-reserver` is to decouple **reservation time** from **execution time**:

```text
Server/ Airflow / MWAA
  |
  | SSH
  v
orchesjob-reserver reserve
  - stores an execution reservation in local SQLite
  - returns immediately
  - does not execute the target command directly
  |
  v
reserver.sqlite3

supervisor / systemd / container process manager
  |
  v
orchesjob-reserver run
  - runs as a foreground dispatcher
  - polls local reservations
  - calls orchesjob start when a reservation is ready
  |
  v
orchesjob start --run-key ... -- <command...>
```

In short:

```text
reserve = store execution intent, optionally with a future dispatch time
run     = independently dispatch stored intent to orchesjob when it becomes ready
orchesjob = own actual process execution and job result
```

`orchesjob-reserver` does not manage job success or failure. Once a reservation is dispatched, the job state, PID management, logs, exit code, and result remain the responsibility of `orchesjob`.

## Features

- **Scheduled edge dispatch** — reserve a job now and let the edge host run it later using `--not-before`
- **Reservation first** — store execution intent before the central orchestrator needs the result
- **Idempotency** — repeated `reserve` calls with the same run key return the existing reservation
- **Dispatcher process** — `run` continuously dispatches ready reservations to `orchesjob`
- **SQLite backend** — reservations are stored locally on the edge host
- **Network interruption tolerance** — the central orchestrator does not need to hold an SSH session while the job runs
- **Pass-through start options** — pass options such as `--strict` or `--bypass` to `orchesjob start`
- **Structured output** — commands print JSON; the dispatcher prints JSON Lines operational logs
- **Readable dispatcher timestamps** — JSON Lines logs use ISO 8601 timestamps
- **No flow engine** — dependency control remains in Airflow or another central orchestrator

## Requirements

- Python ≥ 3.10
- `orchesjob` installed and available on the edge host
- No third-party runtime dependencies

## Installation

**Recommended — pipx (isolated, globally available CLI):**

```bash
pipx install orchesjob-reserver
```

**pip:**

```bash
pip install orchesjob-reserver
```

After installation, the command is available as:

```bash
orchesjob-reserver --help
```

The command name is provided by the package console script:

```toml
[project.scripts]
orchesjob-reserver = "orchesjob_reserver.cli:main"
```

`python -m orchesjob_reserver` can also run the package module, but the intended operational command is `orchesjob-reserver`.

## Environment Variables

### `ORCHESJOB_RESERVER_HOME`

Home directory for `orchesjob-reserver`.

If set, the default SQLite database path is:

```text
${ORCHESJOB_RESERVER_HOME}/reserver.sqlite3
```

### `ORCHESJOB_HOME`

Shared home directory for `orchesjob`-related tools.

Used only when `ORCHESJOB_RESERVER_HOME` is not set.

### Home priority

The default home directory is resolved with this priority, from low to high:

```text
/var/lib/orchesjob
ORCHESJOB_HOME
ORCHESJOB_RESERVER_HOME
```

So the default database path is:

```text
<resolved-home>/reserver.sqlite3
```

You can override the database path explicitly with `--db`.

### `ORCHESJOB_BIN`

Command path used when invoking `orchesjob`.

Default:

```text
orchesjob
```

Example:

```bash
ORCHESJOB_BIN=/usr/local/bin/orchesjob orchesjob-reserver run
```

## Quick Start

On the edge host, run the dispatcher under supervisor, systemd, or another process manager:

```bash
orchesjob-reserver run
```

From Airflow/MWAA or another orchestrator, reserve a job for a future dispatch time:

```bash
orchesjob-reserver reserve \
  --run-key nightly-backup-2026-05-04 \
  --not-before "2026-05-04T02:00:00+09:00" \
  -- /usr/local/bin/backup.sh
```

At this point, the reservation is stored locally on the edge host. The SSH session from the central orchestrator can end.

When the edge host's local `orchesjob-reserver run` process observes that `not_before` has passed, it independently dispatches the job:

```bash
orchesjob start \
  --run-key nightly-backup-2026-05-04 \
  -- /usr/local/bin/backup.sh
```

This is the main operational benefit: the central orchestrator only needs to reach the edge host when it creates the reservation and when it later checks status or collects the result. It does not need to remain connected at the exact execution time.

Check the reservation:

```bash
orchesjob-reserver status --run-key nightly-backup-2026-05-04
```

Include current `orchesjob` job state after dispatch:

```bash
orchesjob-reserver status \
  --run-key nightly-backup-2026-05-04 \
  --include-job
```

Get the job result through the reservation:

```bash
orchesjob-reserver result --run-key nightly-backup-2026-05-04
```

## Commands

### `reserve`

Create a reservation.

```
orchesjob-reserver reserve --run-key KEY [OPTIONS] [--] COMMAND [ARGS...]
```

| Flag | Description |
|------|-------------|
| `--run-key KEY` | Idempotency key for the reservation. Required. |
| `--not-before DATETIME` | Do not dispatch before this datetime. |
| `--expires-at DATETIME` | Expire the reservation if it has not been dispatched by this datetime. |
| `--metadata-json JSON` | Optional JSON object stored with the reservation. |
| `--orchesjob-start-option OPTION` | Option passed to `orchesjob start` before `--`. Repeatable. |
| `--db PATH` | SQLite database path. Overrides environment-based default. |
| `--orchesjob-bin PATH` | `orchesjob` executable used by proxy commands and dispatcher. |
| `--` | Separator between reserver flags and the target command. |

`--not-before` is the key option for scheduled edge dispatch. It allows the central orchestrator to create the reservation now, while the edge-side `run` process waits until that time before calling `orchesjob start`.

`--not-before` and `--expires-at` accept either Unix epoch seconds or ISO 8601 datetime strings. Internally, times are stored as integer epoch seconds.

**Idempotency rule:**

| Existing reservation for run key | Behaviour |
|----------------------------------|-----------|
| Exists | Returns the existing reservation; does not create a new one |
| None | Creates a new reservation |

A repeated `reserve` call is therefore safe across SSH failures, orchestrator retries, and worker restarts.

**Scheduled dispatch rule:**

| Reservation timing | Behaviour |
|--------------------|-----------|
| `--not-before` omitted | Dispatch as soon as `run` sees the reservation |
| `--not-before` in the future | Keep the reservation locally and dispatch at or after that time |
| `--expires-at` reached before dispatch | Mark the reservation as `EXPIRED`; do not call `orchesjob start` |

**Example:**

```bash
orchesjob-reserver reserve \
  --run-key daily-import-2026-05-04 \
  --not-before "2026-05-04T03:00:00+09:00" \
  --metadata-json '{"dag_id":"daily_import","task_id":"import"}' \
  --orchesjob-start-option=--strict \
  -- /jobs/import.sh --date 2026-05-04
```

**Example output:**

```json
{
  "created": true,
  "reservation": {
    "reservation_id": "7c09a7c4-...",
    "run_key": "daily-import-2026-05-04",
    "reservation_status": "RESERVED",
    "job_id": null,
    "command": ["/jobs/import.sh", "--date", "2026-05-04"],
    "orchesjob_start_options": ["--strict"],
    "metadata": {
      "dag_id": "daily_import",
      "task_id": "import"
    },
    "not_before": 1777831200,
    "not_before_iso": "2026-05-04T03:00:00+09:00",
    "expires_at": null,
    "expires_at_iso": null,
    "created_at": 1777830000,
    "created_at_iso": "2026-05-04T10:00:00+00:00",
    "updated_at": 1777830000,
    "updated_at_iso": "2026-05-04T10:00:00+00:00",
    "dispatched_at": null,
    "dispatched_at_iso": null,
    "last_error": null
  }
}
```

### `run`

Run the foreground dispatcher.

```
orchesjob-reserver run [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--poll-interval SECONDS` | Seconds between polling when there is no work. Default: `2.0`. |
| `--error-sleep SECONDS` | Sleep duration after an unexpected dispatcher error. Default: `5.0`. |
| `--orchesjob-start-option OPTION` | Global option passed to every `orchesjob start` call. Repeatable. |
| `--db PATH` | SQLite database path. |
| `--orchesjob-bin PATH` | `orchesjob` executable. |

`run` is intended to be managed by a process manager.

Example supervisor configuration:

```ini
[program:orchesjob-reserver]
command=orchesjob-reserver run --db /var/lib/orchesjob/reserver.sqlite3
autostart=true
autorestart=true
startsecs=3
startretries=10
stopasgroup=true
killasgroup=true
stopsignal=TERM
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
```

The dispatcher emits JSON Lines to stdout.

Important events:

| Event | Meaning |
|-------|---------|
| `reserver_started` | Dispatcher started |
| `reservation_accepted` | Dispatcher observed a reservation created after this `run` process started |
| `orchesjob_start_call` | Dispatcher is about to call `orchesjob start` |
| `dispatch_succeeded` | `orchesjob start` returned a `job_id` |
| `dispatch_failed` | Dispatch failed before a `job_id` was stored |
| `reservation_expired` | Reservation reached `expires_at` before dispatch |
| `recovered_dispatching` | Dispatcher recovered stale `DISPATCHING` reservations on startup |
| `reserver_stopped` | Dispatcher stopped |

Historical `DISPATCHED` records are not re-logged when `run` restarts.

**Example JSON Lines:**

```json
{"event":"reserver_started","db":"/var/lib/orchesjob/reserver.sqlite3","orchesjob_bin":"orchesjob","orchesjob_start_options":[],"poll_interval":2.0,"run_started_at":1777830000,"ts":"2026-05-04T10:00:00+00:00"}
{"event":"reservation_accepted","reservation_id":"7c09a7c4-...","run_key":"daily-import-2026-05-04","reservation_status":"RESERVED","command":["/jobs/import.sh","--date","2026-05-04"],"not_before":1777831200,"expires_at":null,"created_at":1777830000,"ts":"2026-05-04T10:00:01+00:00"}
{"event":"orchesjob_start_call","reservation_id":"7c09a7c4-...","run_key":"daily-import-2026-05-04","command":["orchesjob","start","--run-key","daily-import-2026-05-04","--strict","--","/jobs/import.sh","--date","2026-05-04"],"ts":"2026-05-04T10:00:02+00:00"}
{"event":"dispatch_succeeded","reservation_id":"7c09a7c4-...","run_key":"daily-import-2026-05-04","job_id":"3f2a1b4c-...","ts":"2026-05-04T10:00:03+00:00"}
```

### `status`

Show reservation status.

```
orchesjob-reserver status (--run-key KEY | --reservation-id ID) [--include-job]
```

| Flag | Description |
|------|-------------|
| `--run-key KEY` | Look up by run key |
| `--reservation-id ID` | Look up by reservation ID |
| `--include-job` | Also call `orchesjob status --job-id <job_id>` if dispatched |

Without `--include-job`, `status` returns only reserver state.

With `--include-job`, it includes proxied job state from `orchesjob`. The job state is not stored as reserver state.

**Example output:**

```json
{
  "reservation": {
    "reservation_id": "7c09a7c4-...",
    "run_key": "daily-import-2026-05-04",
    "reservation_status": "DISPATCHED",
    "job_id": "3f2a1b4c-...",
    "command": ["/jobs/import.sh", "--date", "2026-05-04"],
    "orchesjob_start_options": ["--strict"],
    "metadata": null,
    "created_at": 1777830000,
    "created_at_iso": "2026-05-04T10:00:00+00:00",
    "updated_at": 1777830003,
    "updated_at_iso": "2026-05-04T10:00:03+00:00",
    "dispatched_at": 1777830003,
    "dispatched_at_iso": "2026-05-04T10:00:03+00:00",
    "last_error": null
  },
  "job": {
    "job_id": "3f2a1b4c-...",
    "run_key": "daily-import-2026-05-04",
    "status": "RUNNING"
  }
}
```

### `result`

Proxy `orchesjob result` through a reservation.

```
orchesjob-reserver result (--run-key KEY | --reservation-id ID)
```

The reservation must already have a `job_id`.

`result` does not transform the job result. It prints the output from `orchesjob result`.

### `cancel`

Cancel a reservation or proxy cancellation to `orchesjob`.

```
orchesjob-reserver cancel (--run-key KEY | --reservation-id ID)
```

| Reservation state | Behaviour |
|-------------------|-----------|
| `RESERVED` / `DISPATCH_FAILED` / `EXPIRED` | Marks reservation as `CANCELLED` |
| Dispatched with `job_id` | Calls `orchesjob cancel --job-id <job_id>` |

### `list`

List reservations.

```
orchesjob-reserver list [--status STATUS] [--limit N]
```

| Flag | Description |
|------|-------------|
| `--status STATUS` | Restrict to one reservation status |
| `--limit N` | Maximum number of records to return. Default: `50` |

**Example output:**

```json
{
  "reservations": [
    {
      "reservation_id": "7c09a7c4-...",
      "run_key": "daily-import-2026-05-04",
      "reservation_status": "DISPATCHED",
      "job_id": "3f2a1b4c-...",
      "command": ["/jobs/import.sh", "--date", "2026-05-04"],
      "created_at": 1777830000,
      "created_at_iso": "2026-05-04T10:00:00+00:00",
      "updated_at": 1777830003,
      "updated_at_iso": "2026-05-04T10:00:03+00:00"
    }
  ]
}
```

### `clean`

Delete terminal reservation data.

```
orchesjob-reserver clean (--before DATETIME | --after DATETIME | --all | --job-id ID | --reservation-id ID) [--run-key KEY] [--dry-run]
```

| Flag | Description |
|------|-------------|
| `--before DATETIME` | Delete terminal reservations updated before this datetime |
| `--after DATETIME` | Delete terminal reservations updated at or after this datetime |
| `--all` | Delete all matching terminal reservation data |
| `--job-id ID` | Delete one terminal reservation by job ID |
| `--reservation-id ID` | Delete one terminal reservation by reservation ID |
| `--run-key KEY` | Restrict deletion to a run key; combine with `--before`, `--after`, or `--all` |
| `--dry-run` | Print what would be deleted without making changes |

`--before` and `--after` may be combined as a date range.

`--job-id` and `--reservation-id` cannot be combined with other selection options.

These statuses are terminal and eligible for deletion:

```text
DISPATCHED
CANCELLED
EXPIRED
DISPATCH_FAILED
```

These statuses are never deleted:

```text
RESERVED
DISPATCHING
```

**Examples:**

```bash
orchesjob-reserver clean --all
orchesjob-reserver clean --before 2026-06-01
orchesjob-reserver clean --after 2026-05-01 --before 2026-06-01
orchesjob-reserver clean --run-key daily-import-2026-05-04 --all
orchesjob-reserver clean --reservation-id 7c09a7c4-...
orchesjob-reserver clean --before 2026-06-01 --dry-run
```

**Example output:**

```json
{
  "deleted": 1,
  "dry_run": false,
  "matched": 1,
  "reservations": [
    {
      "reservation_id": "7c09a7c4-...",
      "run_key": "daily-import-2026-05-04",
      "reservation_status": "DISPATCHED",
      "job_id": "3f2a1b4c-...",
      "updated_at": 1777830003,
      "updated_at_iso": "2026-05-04T10:00:03+00:00"
    }
  ]
}
```

## Reservation Statuses

| Status | Description |
|--------|-------------|
| `RESERVED` | Reservation exists and has not been dispatched |
| `DISPATCHING` | Dispatcher claimed the reservation and is calling `orchesjob start` |
| `DISPATCHED` | `orchesjob start` returned a `job_id` |
| `CANCELLED` | Reservation was cancelled before dispatch |
| `EXPIRED` | `expires_at` was reached before dispatch |
| `DISPATCH_FAILED` | Dispatcher failed before storing a `job_id` |

`DISPATCHED` does not mean the underlying job succeeded. It only means that `orchesjob` accepted the job and returned a `job_id`.

## JSON Output Notes

Command output is JSON unless the command explicitly proxies `orchesjob` output.

Common fields:

| Field | Description |
|-------|-------------|
| `reservation_id` | Unique ID of the reservation |
| `run_key` | Idempotency key |
| `reservation_status` | State of the reservation |
| `job_id` | `orchesjob` job ID after dispatch; `null` before dispatch |
| `command` | Target command reserved for dispatch |
| `orchesjob_start_options` | Options passed to `orchesjob start` before `--` |
| `metadata` | Optional user-provided JSON object |
| `not_before` / `not_before_iso` | Dispatch lower bound |
| `expires_at` / `expires_at_iso` | Expiration time before dispatch |
| `created_at` / `created_at_iso` | Reservation creation time |
| `updated_at` / `updated_at_iso` | Last reservation update time |
| `dispatched_at` / `dispatched_at_iso` | Time dispatch succeeded |
| `last_error` | Last dispatch or validation error stored on the reservation |

Time fields stored in the database are Unix epoch seconds. JSON command output includes both epoch seconds and ISO 8601 strings where applicable.

`run` logs are JSON Lines. Each line is one JSON object and includes both a readable ISO 8601 `ts` field and a machine-friendly integer `ts_epoch` field.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 4 | Reservation not found |
| 5 | Reservation has not been dispatched; `job_id` is unavailable |
| 6 | Cancellation cannot be performed in the current state |

## License

MIT — Copyright (c) 2026 Ryosuke Muraki
