-- v2.0.0: introduce active flag on stocks so tracking can be toggled
-- without losing historical daily_data / announcements / stock_targets.
--
-- Default 1 keeps every existing stock in the active scheduler set.
-- Idempotent: re-running is safe; the column is only added if missing.

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'stocks'
      AND COLUMN_NAME  = 'active'
);

SET @ddl := IF(
    @col_exists = 0,
    'ALTER TABLE stocks ADD COLUMN active TINYINT(1) NOT NULL DEFAULT 1, ADD INDEX idx_stocks_active (active)',
    'SELECT "stocks.active already present, skipping"'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
