# Clockwork Runbook Scheduler

Clockwork Runbook Scheduler is a scheduling service for defining cron-like jobs and tracking their execution outcomes over time.

## Datastore

### `jobs.json` — list of 12 records
Holds the configured scheduled jobs (name, schedule, command, and enabled flag) so the service can list, create, update, and remove job definitions.

- `job_id` — string
- `name` — string
- `schedule` — string
- `enabled` — boolean
- `command` — string

### `job_histories.json` — list of 144 records
Holds per-run execution history entries for jobs (start time, duration, and outcome) so the service can provide job run history and status reporting.
Lifecycle field `status`, states observed: failed, success, timeout

- `run_id` — string
- `job_id` — string
- `started_at` — string
- `status` — string — one of failed, success, timeout
- `duration_s` — integer
