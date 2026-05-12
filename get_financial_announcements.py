import requests
from datetime import datetime

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
