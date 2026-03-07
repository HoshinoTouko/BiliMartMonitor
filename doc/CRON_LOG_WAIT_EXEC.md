# Cron Log WAIT/EXEC Tags

## Purpose

Improve scan-loop observability by separating log intents:

- `[WAIT]`: scheduler state, sleep, cooldown, next actions
- `[EXEC]`: active scan execution, completion, errors, execution-time metrics

## Scope

Implemented in `src/backend/cron_runner.py`.

### Added

- `_log_wait()` and `_log_exec()` wrappers
- `duration_ms` timing for per-category scan jobs (`time.perf_counter()`)
- duration field in scan summary rows

### Replaced

Direct `cron_state.info/warn/error` calls in the scan loop with tagged helpers where applicable.

## Example

- `[EXEC] 开始扫描 | 账号 ... | 分类 ... | 模式 ... | 第 N 页`
- `[EXEC] 扫描完成 | ... | 新增 X 条 | 耗时 123 ms`
- `[WAIT] 分类 ... 休眠中，剩余 N 轮`
- `[WAIT] 等待 20 秒`

## Operational Benefit

Operators can quickly filter by tag to distinguish:

1. execution-path problems (`[EXEC]`)
2. expected scheduler idle/cooldown behavior (`[WAIT]`)
