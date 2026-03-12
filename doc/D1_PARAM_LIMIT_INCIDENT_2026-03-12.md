# 2026-03-12 D1 参数上限告警复盘

## 告警信息

- 类型: 扫描异常
- 错误: `too many SQL variables ... SQLITE_ERROR`
- 触发 SQL 片段: `WHERE (product.blindbox_id, product.items_id, product.sku_id) IN ((?, ?, ?), ...)`

## 根因

Cloudflare D1 对单条 SQL 绑定参数数量限制为 `100`。  
该查询使用三元组条件，每个 key 占 `3` 个参数:

- 33 组 key = 99 参数 (安全)
- 34 组 key = 102 参数 (超限)

本次告警请求包含 35 组三元组，参数总数为 105，触发 D1 拒绝执行。

## 修复

文件: `src/bsm/db.py`

1. 在 `save_items_data_phase` 的 product id 回查步骤，将三元组查询按 `_D1_MAX_PARAMS // 3` 分块执行。
2. 同时修复 fallback inserted-id 校验查询，将 `c2c_items_id IN (...)` 按 `_D1_MAX_PARAMS` 分块执行，避免后续同类超限。

## 回归测试

文件: `src/backend/testsuite/test_db.py`

- 新增 `test_save_items_data_phase_chunks_lookup_queries_under_d1_param_limit`
- 测试通过 SQLAlchemy `before_cursor_execute` 事件模拟 D1 单条 SQL 最大 100 参数限制，验证:
  - `save_items_data_phase` 在 35 个 detail key 场景下不再超限；
  - 数据写入完整（`product` 与 `snapshot` 均为 35 条）。
