from flask import Flask, render_template
from contextlib import contextmanager
from datetime import date, datetime
import mysql.connector
import json
import logging
import requests
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from get_daily_trades import fetch_and_save as _fetch_stock
from get_financial_announcements import get_financial_announcements, save_announcements

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

DB_CONFIG = {
    "host":     "127.0.0.1",
    "port":     3306,
    "database": "cse_db",
    "user":     "cse",
    "password": "REDACTED",
}

TRACKED_SYMBOLS = [
    "AEL.N0000", "COMB.X0000", "CTEA.N0000", "DIAL.N0000",
    "HHL.N0000", "HNB.X0000", "JKH.N0000", "LFIN.N0000",
    "PINS.N0000", "PLC.N0000", "SUN.N0000",
]
TRACKED_PREFIXES  = {s.split(".")[0].upper() for s in TRACKED_SYMBOLS}
SL_TZ             = pytz.timezone("Asia/Colombo")
UNUSUAL_MULT      = 2.0   # 2× 20-day average triggers amber
UNUSUAL_PRICE_PCT = 5.0   # ±5% price change triggers amber


# ─── Market totals cache (5-min TTL) ──────────────────────────────────────────

_market_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 300  # seconds


def get_cse_market_totals() -> dict:
    """Fetch total volume, turnover, and trades across all CSE stocks via tradeSummary.
    Result is cached for 5 minutes to avoid API hammering on every page load."""
    now = time.time()
    if _market_cache["data"] and now - _market_cache["ts"] < _CACHE_TTL:
        return _market_cache["data"]
    try:
        resp = requests.post("https://www.cse.lk/api/tradeSummary", timeout=10)
        resp.raise_for_status()
        items = resp.json().get("reqTradeSummery", [])
        totals = {
            "total_vol":    sum(int(i.get("sharevolume") or 0) for i in items),
            "total_turn":   sum(float(i.get("turnover")   or 0) for i in items),
            "total_trades": sum(int(i.get("tradevolume")  or 0) for i in items),
            "listed_stocks": len(items),
            "source": "live",
        }
        _market_cache["data"] = totals
        _market_cache["ts"]   = now
        return totals
    except Exception as exc:
        log.warning("Market totals fetch failed: %s", exc)
        return {"total_vol": 0, "total_turn": 0, "total_trades": 0, "listed_stocks": 0, "source": "error"}


# ─── DB helper ─────────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        yield conn
    finally:
        conn.close()


# ─── scheduled jobs ────────────────────────────────────────────────────────────

def _log_fetch(fetch_type: str, fetch_date: date, status: str, message: str = None):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO fetch_log (fetch_type, fetch_date, status, message) "
                "VALUES (%s, %s, %s, %s)",
                (fetch_type, fetch_date, status, message),
            )
            conn.commit()
    except Exception as exc:
        log.error("fetch_log write failed: %s", exc)


def _today_fetched(fetch_type: str) -> bool:
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM fetch_log "
                "WHERE fetch_type=%s AND fetch_date=%s AND status='ok'",
                (fetch_type, date.today()),
            )
            return cur.fetchone()[0] > 0
    except Exception:
        return False


def run_daily_fetch(period: int = 2):
    log.info("Daily fetch: %d symbols, period=%d", len(TRACKED_SYMBOLS), period)
    errors = []
    for sym in TRACKED_SYMBOLS:
        try:
            _fetch_stock(sym, period=period, db_cfg=DB_CONFIG)
        except Exception as exc:
            log.error("Fetch failed [%s]: %s", sym, exc)
            errors.append(f"{sym}: {exc}")
    if errors:
        _log_fetch("daily_data", date.today(), "error", "; ".join(errors))
    else:
        _log_fetch("daily_data", date.today(), "ok")
        log.info("Daily fetch complete")


def hourly_check():
    """Runs every hour. Fetches today's data if market has closed and data is missing."""
    now_sl = datetime.now(SL_TZ)
    after_close = now_sl.hour > 15 or (now_sl.hour == 15 and now_sl.minute >= 30)
    if now_sl.weekday() >= 5 or not after_close:
        return
    if not _today_fetched("daily_data"):
        log.info("Hourly check: fetching missing data for today")
        run_daily_fetch()


def run_announcement_fetch():
    log.info("Fetching CSE announcements")
    try:
        items    = get_financial_announcements()
        relevant = [
            i for i in items
            if (i.get("symbol") or "").split(".")[0].upper() in TRACKED_PREFIXES
        ]
        saved = save_announcements(relevant, DB_CONFIG) if relevant else 0
        _log_fetch("announcements", date.today(), "ok", f"{saved} new")
        log.info("Announcements: %d relevant, %d new saved", len(relevant), saved)
    except Exception as exc:
        log.error("Announcement fetch failed: %s", exc)
        _log_fetch("announcements", date.today(), "error", str(exc))


def startup_backfill():
    """On startup, detect missing trading days and backfill. Also catch any missed scheduled jobs."""
    log.info("Startup: checking for data gaps...")

    if not _today_fetched("announcements"):
        log.info("Announcements not fetched today — running now")
        run_announcement_fetch()
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM daily_data")
            row = cur.fetchone()
        last_date = row[0] if row else None
        today     = date.today()

        if last_date is None:
            log.info("No data found, fetching 12-month history")
            run_daily_fetch(period=5)
            return

        gap = (today - last_date).days
        if gap <= 3:  # weekend gap tolerance
            now_sl = datetime.now(SL_TZ)
            after_close = now_sl.weekday() < 5 and (
                now_sl.hour > 15 or (now_sl.hour == 15 and now_sl.minute >= 30)
            )
            if after_close and not _today_fetched("daily_data"):
                log.info("Market closed, fetching today's data (last: %s)", last_date)
                run_daily_fetch(period=2)
            else:
                log.info("Data current (last: %s)", last_date)
            return

        log.info("Gap of %d days since %s — backfilling", gap, last_date)
        run_daily_fetch(period=3 if gap <= 30 else 5)
    except Exception as exc:
        log.error("Backfill check failed: %s", exc)


# ─── template filters ──────────────────────────────────────────────────────────

@app.template_filter("lkr")
def lkr_fmt(v):
    if v is None:
        return "—"
    v = float(v)
    if v >= 1_000_000_000:
        return f"LKR {v/1_000_000_000:.2f} Bn"
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


# ─── helpers ───────────────────────────────────────────────────────────────────

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


# ─── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT s.symbol, s.name,
                   d1.date        AS trade_date,
                   d1.close_price, d1.volume, d1.turnover,
                   d1.trades, d1.high_price, d1.low_price,
                   d2.close_price AS prev_close,
                   (SELECT AVG(dh.volume)
                    FROM daily_data dh
                    WHERE dh.stock_id = s.id
                      AND dh.date >= DATE_SUB(d1.date, INTERVAL 20 DAY)
                      AND dh.date < d1.date)  AS avg_vol_20d,
                   (SELECT AVG(dh.turnover)
                    FROM daily_data dh
                    WHERE dh.stock_id = s.id
                      AND dh.date >= DATE_SUB(d1.date, INTERVAL 20 DAY)
                      AND dh.date < d1.date)  AS avg_turn_20d
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

        stocks = []

        for r in cur.fetchall():
            close    = float(r["close_price"]) if r["close_price"] else None
            prev     = float(r["prev_close"])  if r["prev_close"]  else None
            vol      = int(r["volume"])    if r["volume"]    else 0
            turn     = float(r["turnover"]) if r["turnover"] else 0.0
            trades   = int(r["trades"])    if r["trades"]    else 0
            avg_vol  = float(r["avg_vol_20d"])  if r["avg_vol_20d"]  else None
            avg_turn = float(r["avg_turn_20d"]) if r["avg_turn_20d"] else None

            change = change_pct = None
            if close and prev:
                change     = round(close - prev, 2)
                change_pct = round((close - prev) / prev * 100, 2)

            vol_unusual   = bool(avg_vol  and vol  > avg_vol  * UNUSUAL_MULT)
            turn_unusual  = bool(avg_turn and turn > avg_turn * UNUSUAL_MULT)
            price_unusual = bool(change_pct is not None and abs(change_pct) >= UNUSUAL_PRICE_PCT)

            stocks.append({
                "symbol":        r["symbol"],
                "name":          r["name"],
                "trade_date":    str(r["trade_date"]),
                "close_price":   close,
                "prev_close":    prev,
                "high_price":    float(r["high_price"]) if r["high_price"] else None,
                "low_price":     float(r["low_price"])  if r["low_price"]  else None,
                "volume":        vol,
                "turnover":      turn,
                "trades":        trades,
                "change":        change,
                "change_pct":    change_pct,
                "unusual":       vol_unusual or turn_unusual or price_unusual,
                "vol_unusual":   vol_unusual,
                "turn_unusual":  turn_unusual,
                "price_unusual": price_unusual,
            })

        cur.execute("""
            SELECT symbol, company, title, ann_date, pdf_url, seen_at
            FROM announcements
            ORDER BY ann_date DESC, seen_at DESC
            LIMIT 20
        """)
        announcements = []
        for a in cur.fetchall():
            a["ann_date"] = str(a["ann_date"])
            a["seen_at"]  = str(a["seen_at"])[:16]
            announcements.append(a)

        cur.execute("""
            SELECT fetch_type,
                   MAX(fetched_at) AS last_at,
                   MAX(CASE WHEN status = 'ok' THEN fetched_at END) AS last_ok,
                   SUM(CASE WHEN status != 'ok' AND fetch_date = CURDATE() THEN 1 ELSE 0 END) AS errors_today
            FROM fetch_log
            GROUP BY fetch_type
        """)
        fetch_info = {r["fetch_type"]: dict(r) for r in cur.fetchall()}
        for fi in fetch_info.values():
            fi["last_ok"] = str(fi["last_ok"])[:16] if fi["last_ok"] else None

    cse_totals = get_cse_market_totals()
    market = {
        "total_vol":     cse_totals["total_vol"],
        "total_turn":    cse_totals["total_turn"],
        "total_trades":  cse_totals["total_trades"],
        "listed_stocks": cse_totals["listed_stocks"],
        "stock_count":   len(stocks),
        "last_date":     stocks[0]["trade_date"] if stocks else "—",
        "fetch_info":    fetch_info,
        "totals_source": cse_totals["source"],
    }

    return render_template("index.html", stocks=stocks, market=market, announcements=announcements)


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
        history = []
        for row in cur.fetchall():
            history.append({
                "date":        str(row["date"]),
                "open_price":  float(row["open_price"])  if row["open_price"]  else None,
                "high_price":  float(row["high_price"])  if row["high_price"]  else None,
                "low_price":   float(row["low_price"])   if row["low_price"]   else None,
                "close_price": float(row["close_price"]) if row["close_price"] else None,
                "volume":      int(row["volume"])    if row["volume"]    else 0,
                "trades":      int(row["trades"])    if row["trades"]    else 0,
                "turnover":    float(row["turnover"]) if row["turnover"] else 0.0,
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

        cur.execute("""
            SELECT title, ann_date, pdf_url, seen_at
            FROM announcements
            WHERE symbol = %s
            ORDER BY ann_date DESC
            LIMIT 10
        """, (symbol,))
        announcements = []
        for a in cur.fetchall():
            a["ann_date"] = str(a["ann_date"])
            a["seen_at"]  = str(a["seen_at"])[:16]
            announcements.append(a)

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
                           announcements=announcements,
                           latest=latest,
                           change=change,
                           change_pct=change_pct)


if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone=SL_TZ)

    # Hourly safety net: fetch if market is closed and today's data is missing
    scheduler.add_job(hourly_check, IntervalTrigger(hours=1), id="hourly_check")

    # Announcement fetch at 9 AM, 12 PM, 3 PM SL time
    scheduler.add_job(
        run_announcement_fetch,
        CronTrigger(hour="9,12,15", minute=0, timezone=SL_TZ),
        id="ann_fetch",
    )

    scheduler.start()
    startup_backfill()

    app.run(debug=False, port=5050)
