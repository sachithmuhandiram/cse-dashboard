USE cse_db;

CREATE TABLE IF NOT EXISTS stock_targets (
    id         INT           NOT NULL AUTO_INCREMENT,
    stock_id   INT           NOT NULL,
    label      VARCHAR(50)   NOT NULL,
    price_min  DECIMAL(10,2) NOT NULL,
    price_max  DECIMAL(10,2),
    note       VARCHAR(100),
    sort_order TINYINT       NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT fk_target_stock FOREIGN KEY (stock_id) REFERENCES stocks(id)
);

-- add note column if running against an existing table
ALTER TABLE stock_targets ADD COLUMN IF NOT EXISTS note VARCHAR(100) AFTER price_max;

-- COMB.X0000 target bands
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy',  150.00, 175.00, NULL, 1 FROM stocks WHERE symbol = 'COMB.X0000' UNION ALL
SELECT id, 'Accumulate',  175.00, 210.00, NULL, 2 FROM stocks WHERE symbol = 'COMB.X0000' UNION ALL
SELECT id, 'Hold',        210.00, 245.00, NULL, 3 FROM stocks WHERE symbol = 'COMB.X0000' UNION ALL
SELECT id, 'Trim',        245.00, 280.00, NULL, 4 FROM stocks WHERE symbol = 'COMB.X0000' UNION ALL
SELECT id, 'Take Profit', 280.00, NULL,   NULL, 5 FROM stocks WHERE symbol = 'COMB.X0000';

-- NTB.X0000 target bands (gap between 270–340 is intentional — no rating in that zone)
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy', 200.00, 270.00, NULL,           1 FROM stocks WHERE symbol = 'NTB.X0000' UNION ALL
SELECT id, 'Accumulate', 340.00, 420.00, NULL,           2 FROM stocks WHERE symbol = 'NTB.X0000' UNION ALL
SELECT id, 'Hold',       420.00, 500.00, NULL,           3 FROM stocks WHERE symbol = 'NTB.X0000' UNION ALL
SELECT id, 'Trim',       500.00, 600.00, '1.6–1.93x P/B', 4 FROM stocks WHERE symbol = 'NTB.X0000' UNION ALL
SELECT id, 'Exit',       600.00, NULL,   NULL,           5 FROM stocks WHERE symbol = 'NTB.X0000';

-- HHL.N0000 (Hemas Holdings) target bands
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy', 21.00, 26.00, NULL, 1 FROM stocks WHERE symbol = 'HHL.N0000' UNION ALL
SELECT id, 'Accumulate', 26.00, 32.00, NULL, 2 FROM stocks WHERE symbol = 'HHL.N0000' UNION ALL
SELECT id, 'Hold',       32.00, 40.00, NULL, 3 FROM stocks WHERE symbol = 'HHL.N0000' UNION ALL
SELECT id, 'Trim',       40.00, 50.00, NULL, 4 FROM stocks WHERE symbol = 'HHL.N0000' UNION ALL
SELECT id, 'Exit',       50.00, NULL,  NULL, 5 FROM stocks WHERE symbol = 'HHL.N0000';

-- PINS.N0000 (People's Insurance) target bands (gap 36–38 is intentionally unrated)
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy', 24.00, 26.50, NULL, 1 FROM stocks WHERE symbol = 'PINS.N0000' UNION ALL
SELECT id, 'Accumulate', 26.50, 30.00, NULL, 2 FROM stocks WHERE symbol = 'PINS.N0000' UNION ALL
SELECT id, 'Hold',       30.00, 36.00, NULL, 3 FROM stocks WHERE symbol = 'PINS.N0000' UNION ALL
SELECT id, 'Trim',       38.00, 42.00, NULL, 4 FROM stocks WHERE symbol = 'PINS.N0000' UNION ALL
SELECT id, 'Exit',       42.00, NULL,  NULL, 5 FROM stocks WHERE symbol = 'PINS.N0000';

-- PLC.N0000 (Lanka Phosphate / People's Leasing) target bands
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy', 17.00, 21.00, NULL, 1 FROM stocks WHERE symbol = 'PLC.N0000' UNION ALL
SELECT id, 'Accumulate', 21.00, 25.00, NULL, 2 FROM stocks WHERE symbol = 'PLC.N0000' UNION ALL
SELECT id, 'Hold',       25.00, 33.00, NULL, 3 FROM stocks WHERE symbol = 'PLC.N0000' UNION ALL
SELECT id, 'Trim',       33.00, 40.00, NULL, 4 FROM stocks WHERE symbol = 'PLC.N0000' UNION ALL
SELECT id, 'Exit',       40.00, NULL,  NULL, 5 FROM stocks WHERE symbol = 'PLC.N0000';

-- SUN.N0000 (Sunshine Holdings) target bands
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy', 19.00, 22.00, NULL, 1 FROM stocks WHERE symbol = 'SUN.N0000' UNION ALL
SELECT id, 'Accumulate', 22.00, 27.00, NULL, 2 FROM stocks WHERE symbol = 'SUN.N0000' UNION ALL
SELECT id, 'Hold',       27.00, 33.00, NULL, 3 FROM stocks WHERE symbol = 'SUN.N0000' UNION ALL
SELECT id, 'Trim',       33.00, 40.00, NULL, 4 FROM stocks WHERE symbol = 'SUN.N0000' UNION ALL
SELECT id, 'Exit',       40.00, NULL,  NULL, 5 FROM stocks WHERE symbol = 'SUN.N0000';

-- HNB.X0000 (Hatton National Bank) target bands
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy', 270.00, 305.00, NULL, 1 FROM stocks WHERE symbol = 'HNB.X0000' UNION ALL
SELECT id, 'Accumulate', 305.00, 345.00, NULL, 2 FROM stocks WHERE symbol = 'HNB.X0000' UNION ALL
SELECT id, 'Hold',       345.00, 385.00, NULL, 3 FROM stocks WHERE symbol = 'HNB.X0000' UNION ALL
SELECT id, 'Trim',       385.00, 430.00, NULL, 4 FROM stocks WHERE symbol = 'HNB.X0000' UNION ALL
SELECT id, 'Exit',       430.00, NULL,   NULL, 5 FROM stocks WHERE symbol = 'HNB.X0000';

-- CIC.X0000 (C I C Holdings) target bands
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy', 16.00, 19.00, NULL, 1 FROM stocks WHERE symbol = 'CIC.X0000' UNION ALL
SELECT id, 'Accumulate', 19.00, 24.00, NULL, 2 FROM stocks WHERE symbol = 'CIC.X0000' UNION ALL
SELECT id, 'Hold',       24.00, 27.00, NULL, 3 FROM stocks WHERE symbol = 'CIC.X0000' UNION ALL
SELECT id, 'Trim',       27.00, 35.00, NULL, 4 FROM stocks WHERE symbol = 'CIC.X0000' UNION ALL
SELECT id, 'Exit',       35.00, NULL,  NULL, 5 FROM stocks WHERE symbol = 'CIC.X0000';

-- JKH.N0000 (John Keells Holdings) target bands  (Strong Buy = ≤ 18)
INSERT INTO stock_targets (stock_id, label, price_min, price_max, note, sort_order)
SELECT id, 'Strong Buy',  0.01, 18.00, NULL, 1 FROM stocks WHERE symbol = 'JKH.N0000' UNION ALL
SELECT id, 'Accumulate', 18.00, 22.00, NULL, 2 FROM stocks WHERE symbol = 'JKH.N0000' UNION ALL
SELECT id, 'Hold',       22.00, 26.00, NULL, 3 FROM stocks WHERE symbol = 'JKH.N0000' UNION ALL
SELECT id, 'Trim',       26.00, 30.00, NULL, 4 FROM stocks WHERE symbol = 'JKH.N0000' UNION ALL
SELECT id, 'Exit',       30.00, NULL,  NULL, 5 FROM stocks WHERE symbol = 'JKH.N0000';
