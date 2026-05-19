import re
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_URL     = "https://www.ideabeam.com/finance/rates/goldprice.php"
_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def fetch_gold_price():
    """Scrape 22K 8g and per-gram gold price from ideabeam.com.
    Returns (price_8g_22k, price_per_gram_22k) as floats, or (None, None) on failure."""
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        price_8g = _extract_near(text, r'22\s*Carat\s*8\s*Grams', r'Rs\.?\s*([\d,]+)')
        if price_8g is None:
            price_8g = _extract_near(text, r'1\s*Pawn', r'Rs\.?\s*([\d,]+)')

        price_per_gram = round(price_8g / 8, 2) if price_8g else None
        return price_8g, price_per_gram
    except Exception as exc:
        log.error("Gold price fetch failed: %s", exc)
        return None, None


def _extract_near(text, anchor_pat, price_pat):
    """Find price_pat within 120 chars after anchor_pat."""
    m = re.search(anchor_pat, text, re.IGNORECASE)
    if not m:
        return None
    window = text[m.start(): m.start() + 120]
    pm = re.search(price_pat, window, re.IGNORECASE)
    if pm:
        try:
            return float(pm.group(1).replace(",", ""))
        except ValueError:
            pass
    return None
