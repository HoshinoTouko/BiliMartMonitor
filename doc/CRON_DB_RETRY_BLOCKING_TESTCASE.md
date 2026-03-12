# Cron DB Retry / Blocking Test Cases

Date: 2026-03-12
Version: 0.9.5.7

## Scope

Validate cron behavior when DB writes fail or become slow:

- DB write phase retries up to 3 attempts.
- DB write failure does not terminate cron loop.
- Scheduler blocking time (execution over interval) is accumulated and surfaced in heartbeat logs.
- DB breakdown log output is disabled (commented out).

## Automated Cases

Implemented in:

- `src/backend/testsuite/test_cron_runner.py`

Cases:

1. `test_db_write_retries_three_times_then_succeeds`
   - Arrange `save_items_data_phase` to fail twice, succeed on third call.
   - Expect total call count is 3.
   - Expect scan result still returns inserted data and session result application still runs.

2. `test_cron_loop_records_blocked_duration_when_round_exceeds_interval`
   - Arrange first scan round duration > configured interval.
   - Expect `cron_state.record_blocked_duration(...)` is called with positive value.

## Manual Verification Checklist

1. Trigger temporary DB write error (e.g. lock DB or inject transient failure).
2. Confirm logs include retry attempt messages (`尝试 1/3`, `2/3`, `3/3` when needed).
3. Confirm cron keeps running after failure and continues to next round.
4. Wait one heartbeat cycle and confirm log includes:
   - `blocked_total=...s`
   - `blocked_max=...s`
   - `blocked_count=...`
5. Confirm no `DB打点 | ...` lines are printed in cron logs.

