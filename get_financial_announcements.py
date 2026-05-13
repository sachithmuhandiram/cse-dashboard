import requests
import mysql.connector
from datetime import datetime, date as _date

BASE_URL = "https://www.cse.lk/api/"
CDN_BASE  = "https://cdn.cse.lk/"


def get_financial_announcements(symbol: str = None) -> list[dict]:
    """
    Fetch the latest financial announcements from CSE.

    Args:
        symbol: Optional short ticker (e.g. "PINS", "DFCC") to filter results.
                The API itself does not support server-side filtering, so this
                is applied client-side.

    Returns:
        List of announcement dicts, newest first.
    """
    response = requests.post(BASE_URL + "getFinancialAnnouncement")
    response.raise_for_status()

    items = response.json().get("reqFinancialAnnouncemnets", [])

    if symbol:
        symbol_upper = symbol.upper()
        items = [
            item for item in items
            if symbol_upper in (item.get("symbol") or "").upper()
            or symbol_upper in (item.get("name") or "").upper()
        ]

    return items


def _parse_date(raw: str) -> str:
    """Parse CSE date strings into YYYY-MM-DD. Handles multiple formats."""
    raw = str(raw).strip()
    for fmt in ("%d %b %Y %I:%M:%S %p", "%d %b %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return _date.today().isoformat()


def save_announcements(items: list[dict], db_cfg: dict) -> int:
    """
    Upsert announcements into the DB. Returns number of new rows inserted.
    Only saves items that have a symbol; ignores duplicates via UNIQUE KEY.
    """
    conn = mysql.connector.connect(**db_cfg)
    try:
        cur = conn.cursor()
        cur.execute("SELECT symbol, id FROM stocks")
        sym_map = {row[0]: row[1] for row in cur.fetchall()}

        rows = []
        for item in items:
            symbol = (item.get("symbol") or "").strip()
            if not symbol:
                continue
            raw_date = item.get("authorizedDate") or item.get("uploadedDate") or ""
            ann_date = _parse_date(raw_date)
            rows.append((
                sym_map.get(symbol),
                symbol,
                (item.get("name") or "")[:200],
                (item.get("fileText") or "Announcement")[:500],
                ann_date,
                (CDN_BASE + item["path"]) if item.get("path") else None,
            ))

        if not rows:
            return 0
        cur.executemany(
            "INSERT IGNORE INTO announcements "
            "(stock_id, symbol, company, title, ann_date, pdf_url) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def format_announcement(item: dict) -> str:
    """Return a human-readable single-line summary of an announcement."""
    authorized = item.get("authorizedDate") or item.get("uploadedDate") or "?"
    symbol     = item.get("symbol") or "—"
    name       = (item.get("name") or "")[:40]
    file_text  = (item.get("fileText") or "")[:80]
    pdf_url    = CDN_BASE + item["path"] if item.get("path") else "—"
    return (
        f"[{authorized[:20]}]  {symbol:<8}  {name:<40}  {file_text}\n"
        f"  PDF: {pdf_url}"
    )


def print_announcements(items: list[dict]) -> None:
    if not items:
        print("No financial announcements found.")
        return

    print(f"{'='*100}")
    print(f"  CSE Financial Announcements  —  fetched {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total results: {len(items)}")
    print(f"{'='*100}\n")

    for item in items:
        print(format_announcement(item))
        print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch CSE financial announcements")
    parser.add_argument(
        "--symbol", "-s",
        default=None,
        help="Filter by ticker symbol (e.g. PINS, DFCC). Case-insensitive.",
    )
    args = parser.parse_args()

    announcements = get_financial_announcements(symbol=args.symbol)
    print_announcements(announcements)
