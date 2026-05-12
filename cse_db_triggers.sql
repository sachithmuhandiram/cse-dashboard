DELIMITER //
     CREATE TRIGGER large_volume_trigger
     AFTER INSERT ON daily_data
     FOR EACH ROW
     BEGIN
         DECLARE avg_volume DECIMAL(10, 2);
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

DELIMITER //
     CREATE TRIGGER price_change_trigger
     AFTER INSERT ON daily_data
     FOR EACH ROW
     BEGIN
         DECLARE prev_close_price DECIMAL(10, 2);
         DECLARE price_change_pct DECIMAL(5, 2);
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
