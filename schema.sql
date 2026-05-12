-- ============================================================
-- CSE Market Data Schema
-- ============================================================

CREATE DATABASE IF NOT EXISTS cse_db;
USE cse_db;

-- ------------------------------------------------------------
-- Company reference table
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stocks (
    id       INT          NOT NULL AUTO_INCREMENT,
    symbol   VARCHAR(10)  NOT NULL,
    name     VARCHAR(100) NOT NULL,
    exchange VARCHAR(50)  NOT NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_symbol (symbol)
);

-- ------------------------------------------------------------
-- Daily trade summary per symbol
-- Populated from:
--   - companyChartDataByStock (period=5)  → historical bars
--   - companyInfoSummery + detailedTrades → today's exact data
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_data (
    id          INT            NOT NULL AUTO_INCREMENT,
    stock_id    INT            NOT NULL,
    date        DATE           NOT NULL,

    open_price  DECIMAL(10,2)  NOT NULL,
    high_price  DECIMAL(10,2)  NOT NULL,
    low_price   DECIMAL(10,2)  NOT NULL,
    close_price DECIMAL(10,2)  NOT NULL,

    volume      INT            NOT NULL,
    trades      INT            NOT NULL,
    turnover    DECIMAL(20,2)  NOT NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_stock_date (stock_id, date),
    CONSTRAINT fk_daily_stock FOREIGN KEY (stock_id) REFERENCES stocks(id)
);

-- ------------------------------------------------------------
-- Events — auto-populated by triggers below
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id          INT          NOT NULL AUTO_INCREMENT,
    stock_id    INT          NOT NULL,
    date        DATE         NOT NULL,
    title       VARCHAR(100) NOT NULL,
    description TEXT,

    PRIMARY KEY (id),
    CONSTRAINT fk_event_stock FOREIGN KEY (stock_id) REFERENCES stocks(id)
);

-- ------------------------------------------------------------
-- Trigger: flag sudden large volume (> 2× 30-day average)
-- ------------------------------------------------------------
DELIMITER //
CREATE TRIGGER large_volume_trigger
AFTER INSERT ON daily_data
FOR EACH ROW
BEGIN
    DECLARE avg_volume DECIMAL(10,2);
    SET avg_volume = (
        SELECT AVG(volume)
        FROM daily_data
        WHERE stock_id = NEW.stock_id
          AND date >= DATE_SUB(NEW.date, INTERVAL 30 DAY)
    );
    IF NEW.volume > avg_volume * 2 THEN
        INSERT INTO events (stock_id, date, title)
        VALUES (NEW.stock_id, NEW.date, 'Sudden Large Volume');
    END IF;
END //
DELIMITER ;

-- ------------------------------------------------------------
-- Trigger: flag price changes larger than 5 %
-- ------------------------------------------------------------
DELIMITER //
CREATE TRIGGER price_change_trigger
AFTER INSERT ON daily_data
FOR EACH ROW
BEGIN
    DECLARE prev_close_price DECIMAL(10,2);
    DECLARE price_change_pct DECIMAL(5,2);
    SET prev_close_price = (
        SELECT close_price
        FROM daily_data
        WHERE stock_id = NEW.stock_id
          AND date < NEW.date
        ORDER BY date DESC
        LIMIT 1
    );
    SET price_change_pct = ((NEW.close_price - prev_close_price) / prev_close_price) * 100;
    IF ABS(price_change_pct) > 5 THEN
        INSERT INTO events (stock_id, date, title)
        VALUES (NEW.stock_id, NEW.date, CONCAT('Price Change: ', price_change_pct, '%'));
    END IF;
END //
DELIMITER ;

-- ------------------------------------------------------------
-- Useful analysis views
-- ------------------------------------------------------------

-- Latest price per symbol
CREATE OR REPLACE VIEW latest_prices AS
SELECT
    s.symbol,
    s.name,
    d.date,
    d.close_price,
    d.volume,
    d.turnover,
    d.trades,
    d.high_price,
    d.low_price
FROM daily_data d
INNER JOIN stocks s ON s.id = d.stock_id
INNER JOIN (
    SELECT stock_id, MAX(date) AS max_date
    FROM daily_data
    GROUP BY stock_id
) latest ON d.stock_id = latest.stock_id AND d.date = latest.max_date;

-- Monthly aggregates per symbol
CREATE OR REPLACE VIEW monthly_summary AS
SELECT
    s.symbol,
    s.name,
    DATE_FORMAT(d.date, '%Y-%m')   AS month,
    MAX(d.high_price)              AS month_high,
    MIN(d.low_price)               AS month_low,
    SUM(d.volume)                  AS total_volume,
    SUM(d.turnover)                AS total_turnover,
    SUM(d.trades)                  AS total_trades,
    COUNT(*)                       AS trading_days,
    ROUND(AVG(d.close_price), 4)   AS avg_close
FROM daily_data d
INNER JOIN stocks s ON s.id = d.stock_id
GROUP BY s.symbol, s.name, DATE_FORMAT(d.date, '%Y-%m');
