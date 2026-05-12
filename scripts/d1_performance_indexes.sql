CREATE INDEX IF NOT EXISTS idx_access_users_status_created_id_username
ON access_users (status, created_at, id, username);

CREATE INDEX IF NOT EXISTS idx_bili_sessions_status_last_used_created_id
ON bili_sessions (status, last_used_at, created_at, id);

CREATE INDEX IF NOT EXISTS idx_bili_sessions_status_use_order
ON bili_sessions (status, coalesce(last_used_at, created_at), id);

CREATE INDEX IF NOT EXISTS idx_c2c_items_created_updated_id
ON c2c_items (created_at, updated_at, c2c_items_id);

CREATE INDEX IF NOT EXISTS idx_c2c_items_category_created_updated_id
ON c2c_items (category_id, created_at, updated_at, c2c_items_id);

CREATE INDEX IF NOT EXISTS idx_c2c_items_price_created_id
ON c2c_items (price, created_at, c2c_items_id);

CREATE INDEX IF NOT EXISTS idx_c2c_items_updated_id
ON c2c_items (updated_at, c2c_items_id);

CREATE INDEX IF NOT EXISTS idx_product_sku_items
ON product (sku_id, items_id);

CREATE INDEX IF NOT EXISTS idx_c2c_snapshot_c2c_product_at
ON c2c_items_snapshot (c2c_items_id, product_id, snapshot_at);

CREATE INDEX IF NOT EXISTS idx_c2c_snapshot_product_at_c2c
ON c2c_items_snapshot (product_id, snapshot_at, c2c_items_id);

DROP INDEX IF EXISTS idx_c2c_items_created_id;
DROP INDEX IF EXISTS idx_c2c_items_category_created_id;
DROP INDEX IF EXISTS idx_c2c_items_updated_at;
