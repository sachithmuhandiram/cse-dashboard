from flask import Flask, render_template, request, redirect, url_for, flash
from contextlib import contextmanager
from datetime import date, datetime
import mysql.connector
import json
import logging
import re
import requests
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from get_daily_trades import fetch_and_save as _fetch_stock
from get_financial_announcements import get_financial_announcements, save_announcements
from fetch_gold_price import fetch_gold_price

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "cse-dashboard-local-only"  # only used for flash messages on localhost

DB_CONFIG = {
    "host":     "127.0.0.1",
    "port":     3306,
    "database": "cse_db",
    "user":     "cse",
    "password": "REDACTED",
}

SL_TZ             = pytz.timezone("Asia/Colombo")
UNUSUAL_MULT      = 2.0   # 2× 20-day average triggers amber
UNUSUAL_PRICE_PCT = 5.0   # ±5% price change triggers amber

RATING_CSS = {
    "Strong Buy":  "rb-strong-buy",
    "Accumulate":  "rb-accumulate",
    "Hold":        "rb-hold",
    "Trim":        "rb-trim",
    "Take Profit": "rb-take-profit",
    "Exit":        "rb-exit",
}


def get_rating(price, bands):
    """Returns (label, css_class, price_min, price_max) for the matching band, else all None."""
    if not price or not bands:
        return None, None, None, None
    for b in bands:
        mn = float(b["price_min"])
        mx = float(b["price_max"]) if b["price_max"] is not None else None
        if mx is None:
            if price >= mn:
                return b["label"], RATING_CSS.get(b["label"]), mn, mx
        elif mn <= price < mx:
            return b["label"], RATING_CSS.get(b["label"]), mn, mx
    return None, None, None, None


# ─── Market totals cache (5-min TTL) ──────────────────────────────────────────

_market_cache: dict = {"data": None, "ts": 0.0}
_gold_nav_cache: dict = {"data": None, "ts": 0.0}
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


def get_active_symbols() -> list[str]:
    """Symbols the scheduler should fetch. Queried fresh so manage-page edits take effect immediately."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT symbol FROM stocks WHERE active = 1 ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]


def get_active_prefixes() -> set[str]:
    """Symbol prefixes (pre-dot) of active stocks, for announcement filtering."""
    return {s.split(".")[0].upper() for s in get_active_symbols()}


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


def _eod_fetched_today() -> bool:
    """Returns True only if daily_data was successfully fetched after market close (15:30 SL) today."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            # fetched_at is stored in UTC by MySQL; convert to SL before comparing.
            cur.execute(
                "SELECT COUNT(*) FROM fetch_log "
                "WHERE fetch_type='daily_data' AND fetch_date=%s AND status='ok' "
                "AND TIME(CONVERT_TZ(fetched_at, '+00:00', '+05:30')) >= '15:30:00'",
                (date.today(),),
            )
            return cur.fetchone()[0] > 0
    except Exception:
        return False


def run_daily_fetch(period: int = 2):
    symbols = get_active_symbols()
    log.info("Daily fetch: %d symbols, period=%d", len(symbols), period)
    errors = []
    for sym in symbols:
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
    """Safety net: runs every hour. Fetches closing data if market is closed and EOD fetch hasn't run yet today."""
    now_sl = datetime.now(SL_TZ)
    after_close = now_sl.hour > 15 or (now_sl.hour == 15 and now_sl.minute >= 30)
    if now_sl.weekday() >= 5 or not after_close:
        return
    if not _eod_fetched_today():
        log.info("Hourly check: EOD fetch not yet done today, fetching now")
        run_daily_fetch()


def ensure_gold_table():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gold_prices (
                id                 INT            NOT NULL AUTO_INCREMENT,
                date               DATE           NOT NULL,
                price_8g_22k       DECIMAL(12,2)  NOT NULL,
                price_per_gram_22k DECIMAL(12,2),
                fetched_at         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uq_gold_date (date)
            )
        """)
        conn.commit()


def run_gold_price_fetch():
    log.info("Fetching 22K gold price from ideabeam.com")
    price_8g, price_per_gram = fetch_gold_price()
    if price_8g is None:
        log.warning("Gold price not found on page")
        _log_fetch("gold_price", date.today(), "error", "price not found")
        return
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO gold_prices (date, price_8g_22k, price_per_gram_22k)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    price_8g_22k       = VALUES(price_8g_22k),
                    price_per_gram_22k = VALUES(price_per_gram_22k),
                    fetched_at         = CURRENT_TIMESTAMP
            """, (date.today(), price_8g, price_per_gram))
            conn.commit()
        _log_fetch("gold_price", date.today(), "ok", f"8g={price_8g}")
        log.info("Gold price saved: 8g=%.0f, per_gram=%s", price_8g, price_per_gram)
    except Exception as exc:
        log.error("Gold price save failed: %s", exc)
        _log_fetch("gold_price", date.today(), "error", str(exc))


def run_announcement_fetch():
    log.info("Fetching CSE announcements")
    try:
        items    = get_financial_announcements()
        prefixes = get_active_prefixes()
        relevant = [
            i for i in items
            if (i.get("symbol") or "").split(".")[0].upper() in prefixes
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

    ensure_gold_table()
    if not _today_fetched("gold_price"):
        log.info("Gold price not fetched today — running now")
        run_gold_price_fetch()

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
            if after_close and not _eod_fetched_today():
                log.info("Market closed, fetching today's data (last: %s)", last_date)
                run_daily_fetch(period=2)
            else:
                log.info("Data current (last: %s)", last_date)
            return

        log.info("Gap of %d days since %s — backfilling", gap, last_date)
        run_daily_fetch(period=3 if gap <= 30 else 5)
    except Exception as exc:
        log.error("Backfill check failed: %s", exc)


# ─── nav gold context processor ────────────────────────────────────────────────

@app.context_processor
def inject_nav_gold():
    now = time.time()
    if _gold_nav_cache["data"] and now - _gold_nav_cache["ts"] < 3600:
        return {"nav_gold": _gold_nav_cache["data"]}
    try:
        with get_db() as conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT price_8g_22k, date FROM gold_prices ORDER BY date DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                data = {"price": float(row["price_8g_22k"]), "date": str(row["date"])}
                _gold_nav_cache["data"] = data
                _gold_nav_cache["ts"]   = now
                return {"nav_gold": data}
    except Exception:
        pass
    return {"nav_gold": None}


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
            SELECT s.symbol, t.label, t.price_min, t.price_max, t.sort_order
            FROM stock_targets t
            JOIN stocks s ON s.id = t.stock_id
            ORDER BY s.symbol, t.sort_order
        """)
        all_targets: dict = {}
        for row in cur.fetchall():
            all_targets.setdefault(row["symbol"], []).append(row)

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
            WHERE s.active = 1
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

            rating, rating_css, rating_min, rating_max = get_rating(close, all_targets.get(r["symbol"], []))

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
                "rating":        rating,
                "rating_css":    rating_css,
                "rating_min":    rating_min,
                "rating_max":    rating_max,
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
                   MAX(CONVERT_TZ(fetched_at, '+00:00', '+05:30')) AS last_at,
                   MAX(CASE WHEN status = 'ok'
                            THEN CONVERT_TZ(fetched_at, '+00:00', '+05:30') END) AS last_ok,
                   SUM(CASE WHEN status != 'ok' AND fetch_date = CURDATE() THEN 1 ELSE 0 END) AS errors_today
            FROM fetch_log
            GROUP BY fetch_type
        """)
        fetch_info = {r["fetch_type"]: dict(r) for r in cur.fetchall()}
        for fi in fetch_info.values():
            fi["last_ok"] = str(fi["last_ok"])[:16] if fi["last_ok"] else None

        cur.execute("""
            SELECT date, price_8g_22k, price_per_gram_22k
            FROM gold_prices
            ORDER BY date DESC
            LIMIT 2
        """)
        gold_rows = cur.fetchall()
        gold_today = gold_prev = None
        if gold_rows:
            g = gold_rows[0]
            gold_today = {
                "date":             str(g["date"]),
                "price_8g_22k":     float(g["price_8g_22k"]),
                "price_per_gram_22k": float(g["price_per_gram_22k"]) if g["price_per_gram_22k"] else None,
            }
        if len(gold_rows) > 1:
            g2 = gold_rows[1]
            gold_prev = {"price_8g_22k": float(g2["price_8g_22k"])}

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

    gold_change = gold_change_pct = None
    if gold_today and gold_prev:
        gold_change     = round(gold_today["price_8g_22k"] - gold_prev["price_8g_22k"], 2)
        gold_change_pct = round(gold_change / gold_prev["price_8g_22k"] * 100, 2)

    return render_template("index.html", stocks=stocks, market=market, announcements=announcements,
                           gold=gold_today, gold_change=gold_change, gold_change_pct=gold_change_pct)


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

        cur.execute("""
            SELECT label, price_min, price_max, note, sort_order
            FROM stock_targets
            WHERE stock_id = %s
            ORDER BY sort_order
        """, (stock["id"],))
        target_bands = [
            {
                "label":     row["label"],
                "price_min": float(row["price_min"]),
                "price_max": float(row["price_max"]) if row["price_max"] is not None else None,
                "note":      row["note"],
                "css":       RATING_CSS.get(row["label"], ""),
            }
            for row in cur.fetchall()
        ]

    latest = history[-1] if history else {}
    prev_h = history[-2] if len(history) > 1 else {}
    if latest and prev_h and latest.get("close_price") and prev_h.get("close_price"):
        change     = round(latest["close_price"] - prev_h["close_price"], 2)
        change_pct = round(change / prev_h["close_price"] * 100, 2)
    else:
        change = change_pct = None

    latest_price = latest.get("close_price") if latest else None
    rating, rating_css, _, _ = get_rating(latest_price, target_bands)

    return render_template("stock.html",
                           stock=stock,
                           history_json=json.dumps(history),
                           events=events,
                           announcements=announcements,
                           latest=latest,
                           change=change,
                           change_pct=change_pct,
                           target_bands=target_bands,
                           rating=rating,
                           rating_css=rating_css)


@app.route("/gold")
def gold_detail():
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT date, price_8g_22k, price_per_gram_22k
            FROM gold_prices
            WHERE date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
            ORDER BY date ASC
        """)
        history = []
        for row in cur.fetchall():
            history.append({
                "date":              str(row["date"]),
                "price_8g_22k":      float(row["price_8g_22k"]),
                "price_per_gram_22k": float(row["price_per_gram_22k"]) if row["price_per_gram_22k"] else None,
            })

    latest = history[-1] if history else None
    prev   = history[-2] if len(history) > 1 else None
    change = change_pct = None
    if latest and prev:
        change     = round(latest["price_8g_22k"] - prev["price_8g_22k"], 2)
        change_pct = round(change / prev["price_8g_22k"] * 100, 2)

    return render_template("gold.html",
                           history_json=json.dumps(history),
                           history_len=len(history),
                           latest=latest,
                           change=change,
                           change_pct=change_pct)


# ─── manage tickers ───────────────────────────────────────────────────────────

SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,8}\.[A-Z]\d{4}$")


def _normalize_symbol(raw: str) -> str:
    """Trim, uppercase, append trailing 0000 if the form is e.g. 'JKH.N'."""
    s = (raw or "").strip().upper()
    if "." in s and not s.endswith("0000") and len(s.split(".")[1]) == 1:
        s = s + "0000"
    return s


@app.route("/manage")
def manage():
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT s.symbol, s.name, s.active,
                   (SELECT MAX(date) FROM daily_data d WHERE d.stock_id = s.id) AS last_date,
                   (SELECT COUNT(*) FROM daily_data d WHERE d.stock_id = s.id) AS row_count
            FROM stocks s
            ORDER BY s.active DESC, s.symbol
        """)
        rows = cur.fetchall()
    active   = [r for r in rows if r["active"]]
    inactive = [r for r in rows if not r["active"]]
    return render_template("manage.html", active=active, inactive=inactive)


@app.route("/manage/add", methods=["POST"])
def manage_add():
    sym = _normalize_symbol(request.form.get("symbol", ""))
    if not SYMBOL_RE.match(sym):
        flash(f"Invalid symbol format: '{sym}'. Expected e.g. 'JKH.N0000'.", "error")
        return redirect(url_for("manage"))

    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, active FROM stocks WHERE symbol = %s", (sym,))
        existing = cur.fetchone()

    if existing and existing["active"]:
        flash(f"{sym} is already tracked.", "info")
        return redirect(url_for("manage"))

    if existing and not existing["active"]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE stocks SET active = 1 WHERE symbol = %s", (sym,))
            conn.commit()
        flash(f"{sym} re-activated (historical data preserved).", "success")
        return redirect(url_for("manage"))

    # Brand-new symbol: fetch 12-month history; fetch_and_save upserts stocks
    # row with default active=1, so success is "row now exists in stocks".
    try:
        _fetch_stock(sym, period=5, db_cfg=DB_CONFIG)
    except Exception as exc:
        log.error("Add ticker fetch failed [%s]: %s", sym, exc)
        flash(f"Failed to fetch {sym} from CSE: {exc}", "error")
        return redirect(url_for("manage"))

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM stocks WHERE symbol = %s", (sym,))
        if not cur.fetchone():
            flash(f"CSE returned no data for {sym}. Check the symbol and try again.", "error")
            return redirect(url_for("manage"))

    flash(f"{sym} added with 12-month history.", "success")
    return redirect(url_for("manage"))


@app.route("/manage/remove/<symbol>", methods=["POST"])
def manage_remove(symbol):
    sym = _normalize_symbol(symbol)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE stocks SET active = 0 WHERE symbol = %s", (sym,))
        affected = cur.rowcount
        conn.commit()
    if affected:
        flash(f"{sym} removed from active tracking. Historical data kept.", "success")
    else:
        flash(f"{sym} not found.", "error")
    return redirect(url_for("manage"))


@app.route("/manage/reactivate/<symbol>", methods=["POST"])
def manage_reactivate(symbol):
    sym = _normalize_symbol(symbol)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE stocks SET active = 1 WHERE symbol = %s", (sym,))
        affected = cur.rowcount
        conn.commit()
    if affected:
        flash(f"{sym} re-activated.", "success")
    else:
        flash(f"{sym} not found.", "error")
    return redirect(url_for("manage"))


if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone=SL_TZ)

    # Primary EOD fetch: 3:30 PM SL time, Mon-Fri (30 min after market close)
    scheduler.add_job(
        run_daily_fetch,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone=SL_TZ),
        id="eod_fetch",
        kwargs={"period": 2},
    )

    # Hourly safety net: fetch if market is closed and DB is still behind
    scheduler.add_job(hourly_check, IntervalTrigger(hours=1), id="hourly_check")

    # Announcement fetch at 9 AM, 12 PM, 3 PM SL time
    scheduler.add_job(
        run_announcement_fetch,
        CronTrigger(hour="9,12,15", minute=0, timezone=SL_TZ),
        id="ann_fetch",
    )

    # Gold price fetch twice per day: 10 AM (morning) and 3:30 PM (post-market) SL
    scheduler.add_job(
        run_gold_price_fetch,
        CronTrigger(hour=10, minute=0, timezone=SL_TZ),
        id="gold_fetch_morning",
    )
    scheduler.add_job(
        run_gold_price_fetch,
        CronTrigger(hour=15, minute=30, timezone=SL_TZ),
        id="gold_fetch_afternoon",
    )

    scheduler.start()
    startup_backfill()

    app.run(debug=False, port=5050)
