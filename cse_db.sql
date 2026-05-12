CREATE TABLE stocks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    name VARCHAR(100) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    UNIQUE (symbol)
);

CREATE TABLE daily_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_id INT NOT NULL,
    date DATE NOT NULL,
    open_price DECIMAL(10, 2) NOT NULL,
    high_price DECIMAL(10, 2) NOT NULL,
    low_price DECIMAL(10, 2) NOT NULL,
    close_price DECIMAL(10, 2) NOT NULL,
    volume INT NOT NULL,
    trades INT NOT NULL,
    turnover DECIMAL(20, 2) NOT NULL,
    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    UNIQUE (stock_id, date)
);

CREATE TABLE events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_id INT NOT NULL,
    date DATE NOT NULL,
    title VARCHAR(100) NOT NULL,
    description TEXT,
    FOREIGN KEY (stock_id) REFERENCES stocks(id)
);
