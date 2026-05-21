"""
Fetch daily trade data for a CSE ticker and persist to MySQL.

CSE API endpoints used here (companyChartDataByStock, companyInfoSummery,
detailedTrades) are reverse-engineered and documented by GH0STH4CKER:
https://github.com/GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation

Data sources
------------
Historical (up to 12 months)  : companyChartDataByStock  (period=5)
Today exact turnover/trades    : companyInfoSummery + detailedTrades

Period reference
----------------
  period=1  intraday ticks (today only)
  period=2  current week   (~5 daily bars)
  period=3  last ~1 month  (~20 daily bars)
  period=4  last ~2 months (~40 daily bars)
  period=5  last 12 months (~250 daily bars)
"""

import argparse
from datetime import datetime, timezone, date

import mysql.connector
import requests

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL = "https://www.cse.lk/api/"

from db_config import DB_CONFIG

# ── CSE API helpers ─────────────────────────────────────────────────────────────

def _post(endpoint: str, data: dict = None) -> dict | list:
    resp = requests.post(BASE_URL + endpoint, data=data or {})
    resp.raise_for_status()
    return resp.json()


def get_company_info(symbol: str) -> dict:
    return _post("companyInfoSummery", {"symbol": symbol})


def get_chart_data(security_id: int, period: int = 5) -> list[dict]:
    """Return daily OHLCV bars. period=5 → last 12 months."""
    data = _post("companyChartDataByStock", {"stockId": security_id, "period": period})
    return data.get("chartData", [])


def get_detailed_trades() -> list[dict]:
    data = _post("detailedTrades")
    return data.get("reqDetailTrades", [])


def get_market_status() -> str:
    return _post("marketStatus").get("status", "Unknown")


# ── Data transformation ─────────────────────────────────────────────────────────

def _ts_to_date(ts_ms: int) -> date:
    """Convert millisecond epoch → UTC date (CSE closes at 14:30 SL time = 09:00 UTC)."""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()


def build_historical_rows(symbol: str, chart_pts: list[dict]) -> list[dict]:
    """Convert raw chart API points into DB row dicts."""
    rows = []
    for pt in chart_pts:
        ts = pt.get("t")
        if not ts:
            continue
        rows.append({
            "symbol":      symbol,
            "date":        _ts_to_date(ts),
            "open_price":  pt.get("o") or 0,
            "high_price":  pt.get("h") or 0,
            "low_price":   pt.get("l") or 0,
            "close_price": pt.get("p") or 0,
            "volume":      pt.get("q") or 0,
            "trades":      0,       # not available in chart API
            "turnover":    0,       # not available in chart API
        })
    return rows


def build_today_row(symbol: str, info: dict, detail: dict | None) -> dict:
    """Build today's row from companyInfoSummery + detailedTrades."""
    sym = info.get("reqSymbolInfo", {})

    close = (
        (detail or {}).get("price")
        or sym.get("lastTradedPrice")
        or sym.get("closingPrice")
        or 0
    )

    return {
        "symbol":      symbol,
        "date":        date.today(),
        "open_price":  0,
        "high_price":  sym.get("hiTrade") or 0,
        "low_price":   sym.get("lowTrade") or 0,
        "close_price": close,
        "volume":      sym.get("tdyShareVolume") or (detail or {}).get("qty") or 0,
        "trades":      (detail or {}).get("trades") or 0,
        "turnover":    sym.get("tdyTurnover") or 0,
    }


# ── MySQL helpers ───────────────────────────────────────────────────────────────

UPSERT_STOCK_SQL = """
INSERT INTO stocks (symbol, name, exchange)
VALUES (%(symbol)s, %(name)s, %(exchange)s)
ON DUPLICATE KEY UPDATE
    name     = VALUES(name),
    exchange = VALUES(exchange)
"""

GET_STOCK_ID_SQL = "SELECT id FROM stocks WHERE symbol = %s"

UPSERT_DAILY_SQL = """
INSERT INTO daily_data
    (stock_id, date, open_price, high_price, low_price, close_price,
     volume, trades, turnover)
VALUES
    (%(stock_id)s, %(date)s, %(open_price)s, %(high_price)s, %(low_price)s, %(close_price)s,
     %(volume)s, %(trades)s, %(turnover)s)
ON DUPLICATE KEY UPDATE
    open_price  = VALUES(open_price),
    high_price  = VALUES(high_price),
    low_price   = VALUES(low_price),
    close_price = COALESCE(VALUES(close_price), close_price),
    volume      = COALESCE(VALUES(volume),      volume),
    trades      = COALESCE(VALUES(trades),      trades),
    turnover    = COALESCE(VALUES(turnover),    turnover)
"""


def save_stock(symbol: str, name: str, db_cfg: dict) -> int:
    """Upsert stock record and return its id."""
    conn = mysql.connector.connect(**db_cfg)
    try:
        cur = conn.cursor()
        cur.execute(UPSERT_STOCK_SQL, {"symbol": symbol, "name": name, "exchange": "CSE"})
        conn.commit()
        cur.execute(GET_STOCK_ID_SQL, (symbol,))
        return cur.fetchone()[0]
    finally:
        conn.close()


def save_rows(rows: list[dict], stock_id: int, db_cfg: dict) -> int:
    """Upsert rows into daily_data. Returns number of rows affected."""
    if not rows:
        return 0
    for row in rows:
        row["stock_id"] = stock_id
    conn = mysql.connector.connect(**db_cfg)
    try:
        cur = conn.cursor()
        cur.executemany(UPSERT_DAILY_SQL, rows)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ── Main fetch + save ───────────────────────────────────────────────────────────

def fetch_and_save(symbol: str, period: int = 5, db_cfg: dict = None) -> None:
    if db_cfg is None:
        db_cfg = DB_CONFIG

    # Normalise symbol
    if "." in symbol and not symbol.endswith("0000"):
        symbol = symbol + "0000"

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Fetching data for {symbol}...")

    # 1. Company info (also gives us securityId)
    info         = get_company_info(symbol)
    sym_info     = info.get("reqSymbolInfo", {})
    security_id  = info.get("reqSymbolBetaInfo", {}).get("securityId")
    company_name = sym_info.get("name", symbol)

    # stockId for companyChartDataByStock is reqSymbolInfo.id (NOT reqSymbolBetaInfo.securityId)
    stock_id_api = info.get("reqSymbolInfo", {}).get("id")

    if not security_id or not stock_id_api:
        print(f"  ERROR: could not resolve IDs for {symbol}.")
        return

    print(f"  Company  : {company_name}  (securityId={security_id}, stockId={stock_id_api})")

    # 2. Upsert stock reference → get DB stock_id
    db_stock_id = save_stock(symbol, company_name, db_cfg)

    # 3. Historical daily bars
    chart_pts = get_chart_data(stock_id_api, period=period)
    hist_rows = build_historical_rows(symbol, chart_pts)
    print(f"  Chart    : {len(hist_rows)} daily bars (period={period})")

    # 4. Today's exact data
    all_details = get_detailed_trades()
    detail = next(
        (d for d in all_details if (d.get("symbol") or "").upper() == symbol.upper()),
        None,
    )
    market_status = get_market_status()
    today_row = build_today_row(symbol, info, detail)

    # Only include today if market has traded
    if today_row["volume"] or today_row["close_price"]:
        rows = hist_rows + [today_row]
    else:
        rows = hist_rows

    # 5. Deduplicate (today might already be in chart data; keep today's row)
    seen = {}
    for r in rows:
        key = str(r["date"])
        if key not in seen or r.get("trades", 0) > 0:
            seen[key] = r
    final_rows = list(seen.values())

    # 6. Save
    affected = save_rows(final_rows, db_stock_id, db_cfg)
    print(f"  Saved    : {len(final_rows)} rows → MySQL ({affected} rows affected)")
    print(f"  Market   : {market_status}")

    # 7. Print today's snapshot
    tr = today_row
    price_str = f"LKR {tr['close_price']:.2f}" if tr["close_price"] else "No trade yet"
    print(f"\n  Today ({tr['date']}):")
    print(f"    Price    : {price_str}")
    print(f"    Volume   : {tr['volume']:,} shares  |  {tr['trades']} trades")
    print(f"    Turnover : LKR {tr['turnover']:,.2f}")
    if tr["high_price"]:
        print(f"    H / L    : {tr['high_price']} / {tr['low_price']}")
    print()


# ── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch CSE daily trade data and save to MySQL"
    )
    parser.add_argument("symbol",  help="Ticker (e.g. PINS.N0000 or LOLC.N)")
    parser.add_argument(
        "--period", "-p", type=int, default=5,
        help="History window: 2=week, 3=1month, 4=2months, 5=12months (default: 5)"
    )
    parser.add_argument("--host",     default=DB_CONFIG["host"])
    parser.add_argument("--port",     default=DB_CONFIG["port"], type=int)
    parser.add_argument("--db",       default=DB_CONFIG["database"])
    parser.add_argument("--user",     default=DB_CONFIG["user"])
    parser.add_argument("--password", default=DB_CONFIG["password"])

    args = parser.parse_args()

    cfg = {
        "host":     args.host,
        "port":     args.port,
        "database": args.db,
        "user":     args.user,
        "password": args.password,
    }

    fetch_and_save(args.symbol, period=args.period, db_cfg=cfg)
