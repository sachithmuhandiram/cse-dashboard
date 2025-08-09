````markdown
# Colombo Stock Exchange (CSE) API 📈🏢

> **Unofficial API usage guide & Python example 🐍**  
> Explore stock market data from the Colombo Stock Exchange (CSE) via their public API endpoints — reverse-engineered since no official documentation exists. 🔍

---

## Overview 📋

The Colombo Stock Exchange provides real-time and historical stock data via several public endpoints used by their web portal.  
This repository documents some of the known API endpoints, example responses, and Python code to fetch and parse data.

---

## API Endpoints 🔗

| Endpoint URL                                 | Description                                     | HTTP Method |
|----------------------------------------------|------------------------------------------------|-------------|
| `https://www.cse.lk/api/companyInfoSummery` | Detailed info of a single stock/security by symbol | POST        |
| `https://www.cse.lk/api/tradeSummary`        | Summary of trades for all securities            | POST        |

---

## Usage Examples 💻

### Get detailed stock info by symbol 🔍

```python
import requests
from pprint import pprint

API_URL = "https://www.cse.lk/api/companyInfoSummery"
HEADERS = {
    # Include required headers here
}
COOKIES = {
    # Include required cookies here
}

def get_stock_details(symbol):
    data = {"symbol": symbol}
    response = requests.post(API_URL, headers=HEADERS, cookies=COOKIES, data=data)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    symbol = "LOLC.N0000"
    details = get_stock_details(symbol)
    pprint(details)
````

---

### Get summary of all recent trades 📊

```python
import requests

TRADE_SUMMARY_URL = "https://www.cse.lk/api/tradeSummary"

def get_trade_summary():
    response = requests.post(TRADE_SUMMARY_URL)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    trades = get_trade_summary()
    print(trades)
```

---

## Sample Response: `companyInfoSummery` 📝

```json
{
  "reqSymbolInfo": {
    "symbol": "LOLC.N0000",
    "name": "L O L C HOLDINGS PLC",
    "lastTradedPrice": 546.5,
    "change": -2.5,
    "changePercentage": -0.455,
    "marketCap": 259696800000,
    ...
  },
  "reqLogo": {
    "id": 2168,
    "path": "upload_logo/378_1601611239.jpeg"
  },
  "reqSymbolBetaInfo": {
    "betaValueSPSL": 1.0227,
    ...
  }
}
```

---

## Sample Response: `tradeSummary` 📈

```json
{
  "reqTradeSummery": [
    {
      "id": 204,
      "symbol": "ABAN.N0000",
      "name": "ABANS ELECTRICALS PLC",
      "price": 579.75,
      "change": 23.75,
      "percentageChange": 4.27,
      "sharevolume": 8290,
      "turnover": 4800716.75,
      ...
    },
    {
      "id": 1845,
      "symbol": "AFSL.N0000",
      "name": "ABANS FINANCE PLC",
      "price": 72.5,
      ...
    }
  ]
}
```

---

## Contribution 🤝

This is an **unofficial** reverse-engineered API.
If you discover more endpoints or useful parameters, please submit a **Pull Request**!
Help expand the community knowledge about the Colombo Stock Exchange API. 🚀

---

## Disclaimer ⚠️

* Use responsibly and verify data accuracy with official CSE sources.
* API endpoints and formats may change without notice.
* This repository is for educational purposes only.

```

---



If you want, I can save this as a `.md` file and share a download link for you to directly upload to GitHub. Would you like that?
```
