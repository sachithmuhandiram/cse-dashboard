from flask import Flask, render_template
from contextlib import contextmanager
from decimal import Decimal
import mysql.connector
import json

app = Flask(__name__)

DB_CONFIG = {
    "host":     "127.0.0.1",
    "port":     3306,
    "database": "cse_db",
    "user":     "cse",
    "password": "REDACTED",
}

@contextmanager
def get_db():
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        yield conn
    finally:
        conn.close()

def to_float(v):
    return float(v) if v is not None else None

def to_int(v):
    return int(v) if v is not None else 0

def classify_event(title: str) -> str:
    if "Large Volume" in title:
        return "volume"
    if "Price Change" in title:
        try:
            pct = float(title.split(": ")[1].replace("%", ""))
            return "price_up" if pct >= 0 else "price_down"
        except Exception:
            pass
    return "other"

@app.template_filter("lkr")
def lkr_fmt(v):
    if v is None:
        return "—"
    v = float(v)
    if v >= 1_000_000:
        return f"LKR {v/1_000_000:.2f} Mn"
    if v >= 1_000:
        return f"LKR {v/1_000:.1f} K"
    return f"LKR {v:.2f}"

@app.template_filter("num")
def num_fmt(v):
    if v is None:
        return "—"
    return f"{int(v):,}"


@app.route("/")
def index():
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT s.symbol, s.name,
                   d1.date        AS trade_date,
                   d1.close_price, d1.volume, d1.turnover,
                   d1.trades, d1.high_price, d1.low_price,
                   d2.close_price AS prev_close
            FROM stocks s
            JOIN daily_data d1 ON d1.stock_id = s.id
            JOIN (
                SELECT stock_id, MAX(date) AS max_date
                FROM daily_data GROUP BY stock_id
            ) latest ON d1.stock_id = latest.stock_id AND d1.date = latest.max_date
            LEFT JOIN daily_data d2
                ON d2.stock_id = d1.stock_id
               AND d2.date = (
                    SELECT MAX(date) FROM daily_data
                    WHERE stock_id = d1.stock_id AND date < d1.date
               )
            ORDER BY s.symbol
        """)
        rows = cur.fetchall()

        stocks = []
        for r in rows:
            close = to_float(r["close_price"])
            prev  = to_float(r["prev_close"])
            r["close_price"] = close
            r["prev_close"]  = prev
            r["high_price"]  = to_float(r["high_price"])
            r["low_price"]   = to_float(r["low_price"])
            r["turnover"]    = to_float(r["turnover"])
            r["volume"]      = to_int(r["volume"])
            r["trades"]      = to_int(r["trades"])
            r["trade_date"]  = str(r["trade_date"])
            if close and prev:
                r["change"]     = round(close - prev, 2)
                r["change_pct"] = round((close - prev) / prev * 100, 2)
            else:
                r["change"] = r["change_pct"] = None
            stocks.append(r)

        cur.execute("""
            SELECT e.date, e.title, s.symbol, s.name
            FROM events e
            JOIN stocks s ON s.id = e.stock_id
            ORDER BY e.date DESC
            LIMIT 30
        """)
        events = []
        for e in cur.fetchall():
            e["date"] = str(e["date"])
            e["kind"] = classify_event(e["title"])
            events.append(e)

    return render_template("index.html", stocks=stocks, events=events)


@app.route("/stock/<symbol>")
def stock_detail(symbol):
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT * FROM stocks WHERE symbol = %s", (symbol,))
        stock = cur.fetchone()
        if not stock:
            return "Stock not found", 404

        cur.execute("""
            SELECT date, open_price, high_price, low_price, close_price,
                   volume, trades, turnover
            FROM daily_data
            WHERE stock_id = %s
            ORDER BY date
        """, (stock["id"],))
        raw = cur.fetchall()

        history = []
        for row in raw:
            history.append({
                "date":        str(row["date"]),
                "open_price":  to_float(row["open_price"]),
                "high_price":  to_float(row["high_price"]),
                "low_price":   to_float(row["low_price"]),
                "close_price": to_float(row["close_price"]),
                "volume":      to_int(row["volume"]),
                "trades":      to_int(row["trades"]),
                "turnover":    to_float(row["turnover"]),
            })

        cur.execute("""
            SELECT date, title, description
            FROM events WHERE stock_id = %s
            ORDER BY date DESC
        """, (stock["id"],))
        events = []
        for e in cur.fetchall():
            e["date"] = str(e["date"])
            e["kind"] = classify_event(e["title"])
            events.append(e)

    latest = history[-1] if history else {}
    prev_h = history[-2] if len(history) > 1 else {}
    if latest and prev_h and latest.get("close_price") and prev_h.get("close_price"):
        change     = round(latest["close_price"] - prev_h["close_price"], 2)
        change_pct = round(change / prev_h["close_price"] * 100, 2)
    else:
        change = change_pct = None

    return render_template("stock.html",
                           stock=stock,
                           history_json=json.dumps(history),
                           events=events,
                           latest=latest,
                           change=change,
                           change_pct=change_pct)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
