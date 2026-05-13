USE cse_db;

CREATE TABLE IF NOT EXISTS announcements (
    id        INT          NOT NULL AUTO_INCREMENT,
    stock_id  INT          DEFAULT NULL,
    symbol    VARCHAR(20)  NOT NULL,
    company   VARCHAR(200) DEFAULT NULL,
    title     VARCHAR(500) NOT NULL,
    ann_date  DATE         NOT NULL,
    pdf_url   VARCHAR(500) DEFAULT NULL,
    seen_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_ann (symbol, ann_date, title(100)),
    KEY idx_symbol (symbol),
    CONSTRAINT fk_ann_stock FOREIGN KEY (stock_id) REFERENCES stocks(id)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id          INT          NOT NULL AUTO_INCREMENT,
    fetch_type  VARCHAR(50)  NOT NULL,
    fetch_date  DATE         NOT NULL,
    fetched_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status      VARCHAR(20)  NOT NULL DEFAULT 'ok',
    message     TEXT         DEFAULT NULL,
    PRIMARY KEY (id),
    KEY idx_type_date (fetch_type, fetch_date)
);
