import requests
from datetime import datetime

BASE_URL = "https://www.cse.lk/api/"


def get_company_info(symbol: str) -> dict:
    resp = requests.post(BASE_URL + "companyInfoSummery", data={"symbol": symbol})
    resp.raise_for_status()
    return resp.json()


def get_today_share_prices() -> list[dict]:
    resp = requests.post(BASE_URL + "todaySharePrice")
    resp.raise_for_status()
    return resp.json()


def get_detailed_trades() -> list[dict]:
    resp = requests.post(BASE_URL + "detailedTrades")
    resp.raise_for_status()
    return resp.json().get("reqDetailTrades", [])


def get_trade_summary() -> list[dict]:
    resp = requests.post(BASE_URL + "tradeSummary")
    resp.raise_for_status()
    return resp.json().get("reqTradeSummery", [])


def get_market_status() -> str:
    resp = requests.post(BASE_URL + "marketStatus")
    resp.raise_for_status()
    return resp.json().get("status", "Unknown")


def find_by_symbol(items: list[dict], symbol: str) -> dict | None:
    symbol_upper = symbol.upper()
    for item in items:
        if (item.get("symbol") or "").upper() == symbol_upper:
            return item
    return None


def get_live_price(symbol: str) -> dict:
    """
    Aggregate live price data for a ticker from multiple CSE endpoints.

    Returns a dict with all available price fields merged from:
      - companyInfoSummery  (reference data, historical highs/lows, turnover)
      - todaySharePrice     (today's OHLC snapshot)
      - detailedTrades      (intraday traded price, volume, change — only present if traded today)
      - tradeSummary        (broader trade summary)
    """
    # Normalise: accept both "PINS.N" and "PINS.N0000"
    if "." in symbol and not symbol.endswith("0000"):
        symbol = symbol + "0000"

    market_status = get_market_status()

    # Fetch all sources in sequence (could be parallelised with threading if needed)
    info        = get_company_info(symbol)
    today_prices = get_today_share_prices()
    detail_trades = get_detailed_trades()
    trade_summary = get_trade_summary()

    sym_info   = info.get("reqSymbolInfo", {})
    today_snap = find_by_symbol(today_prices, symbol)
    detail     = find_by_symbol(detail_trades, symbol)
    summary    = find_by_symbol(trade_summary, symbol)

    return {
        "symbol":         sym_info.get("symbol") or symbol,
        "name":           sym_info.get("name"),
        "market_status":  market_status,
        "fetched_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

        # --- Live price (best available) ---
        "last_traded_price": (
            detail.get("price")
            or (today_snap or {}).get("lastTradedPrice")
            or sym_info.get("lastTradedPrice")
        ),
        "change":            (
            detail.get("change")
            or (today_snap or {}).get("change")
            or sym_info.get("change")
        ),
        "change_pct":        (
            detail.get("changePercentage")
            or (today_snap or {}).get("changePercentage")
            or sym_info.get("changePercentage")
        ),
        "previous_close":    sym_info.get("previousClose"),

        # --- Today's activity ---
        "today_volume":      sym_info.get("tdyShareVolume") or (detail or {}).get("qty") or 0,
        "today_trades":      (detail or {}).get("trades") or 0,
        "today_turnover":    sym_info.get("tdyTurnover") or 0,
        "today_high":        sym_info.get("hiTrade") or (today_snap or {}).get("highPrice"),
        "today_low":         sym_info.get("lowTrade") or (today_snap or {}).get("lowPrice"),

        # --- Historical ranges ---
        "wtd_high": sym_info.get("wtdHiPrice"),  "wtd_low": sym_info.get("wtdLowPrice"),
        "mtd_high": sym_info.get("mtdHiPrice"),  "mtd_low": sym_info.get("mtdLowPrice"),
        "ytd_high": sym_info.get("ytdHiPrice"),  "ytd_low": sym_info.get("ytdLowPrice"),
        "p12_high": sym_info.get("p12HiPrice"),  "p12_low": sym_info.get("p12LowPrice"),
        "all_high": sym_info.get("allHiPrice"),  "all_low": sym_info.get("allLowPrice"),

        # --- Company fundamentals ---
        "market_cap":        sym_info.get("marketCap"),
        "market_cap_pct":    sym_info.get("marketCapPercentage"),
        "shares_issued":     sym_info.get("quantityIssued"),
        "par_value":         sym_info.get("parValue"),
        "isin":              sym_info.get("isin"),

        # --- Beta ---
        "beta_triasi":       info.get("reqSymbolBetaInfo", {}).get("triASIBetaValue"),
        "beta_spsl":         info.get("reqSymbolBetaInfo", {}).get("betaValueSPSL"),
    }


def print_live_price(data: dict) -> None:
    price = data["last_traded_price"]
    change = data["change"]
    pct = data["change_pct"]

    price_str = f"LKR {price:.2f}" if price else "No trades yet"
    change_str = ""
    if change is not None and pct is not None:
        arrow = "▲" if change >= 0 else "▼"
        change_str = f"  {arrow} {change:+.2f}  ({pct:+.4f}%)"

    print(f"\n{'='*60}")
    print(f"  {data['symbol']}  —  {data['name']}")
    print(f"  Market: {data['market_status']}   |   {data['fetched_at']}")
    print(f"{'='*60}")
    print(f"  Last Price   : {price_str}{change_str}")
    print(f"  Prev Close   : LKR {data['previous_close']:.2f}" if data['previous_close'] else "  Prev Close   : —")
    print(f"  Today Vol    : {data['today_volume']:,} shares  |  {data['today_trades']} trades")
    print(f"  Today Turn   : LKR {data['today_turnover']:,.2f}")

    h = data['today_high']
    l = data['today_low']
    if h or l:
        print(f"  Today H/L    : {h or '—'} / {l or '—'}")

    print(f"\n  --- Historical Price Range ---")
    print(f"  {'Period':<10} {'High (LKR)':>12} {'Low (LKR)':>12}")
    print(f"  {'-'*36}")
    for label, hi_key, lo_key in [
        ("Week",   "wtd_high", "wtd_low"),
        ("Month",  "mtd_high", "mtd_low"),
        ("YTD",    "ytd_high", "ytd_low"),
        ("12-Mon", "p12_high", "p12_low"),
        ("All-Time","all_high","all_low"),
    ]:
        hi = data[hi_key]
        lo = data[lo_key]
        hi_s = f"{hi:.2f}" if hi else "—"
        lo_s = f"{lo:.2f}" if lo else "—"
        print(f"  {label:<10} {hi_s:>12} {lo_s:>12}")

    mc = data["market_cap"]
    print(f"\n  --- Fundamentals ---")
    print(f"  Market Cap   : LKR {mc:,.0f}  ({data['market_cap_pct']:.4f}% of market)" if mc else "  Market Cap   : —")
    print(f"  Shares Issued: {data['shares_issued']:,}" if data['shares_issued'] else "")
    print(f"  Par Value    : LKR {data['par_value']:.2f}" if data['par_value'] else "")
    print(f"  ISIN         : {data['isin'] or '—'}")
    print(f"  Beta (TRIASI): {data['beta_triasi']}" if data['beta_triasi'] else "")
    print(f"  Beta (SPSL)  : {data['beta_spsl']}" if data['beta_spsl'] else "")
    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Get live CSE price for a ticker")
    parser.add_argument("symbol", help="Ticker symbol (e.g. PINS.N0000 or PINS.N)")
    args = parser.parse_args()

    data = get_live_price(args.symbol)
    print_live_price(data)
