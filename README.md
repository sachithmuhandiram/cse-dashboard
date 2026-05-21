# CSE Dashboard

A self-hosted Flask dashboard for the Colombo Stock Exchange. Tracks a personal
watchlist of CSE tickers, fetches end-of-day OHLCV via the (unofficial) CSE API,
pulls relevant financial announcements, and shows the daily 22K gold price.

> **Built on the [Colombo-Stock-Exchange-CSE-API-Documentation](https://github.com/GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation)
> project by [GH0STH4CKER](https://github.com/GH0STH4CKER).** All CSE API
> endpoints, request payloads, and response shapes used in this dashboard were
> reverse-engineered and documented there. Please star the upstream project if
> you find it useful.

## Features

- **Watchlist dashboard** — latest close, daily change, 20-day volume/turnover
  baselines, "unusual activity" highlight, configurable target bands per stock.
- **Manage page (`/manage`)** — add/remove/re-activate tickers without
  redeploying. Removing a ticker stops new fetches but keeps historical data.
- **Scheduler** — APScheduler jobs (Asia/Colombo timezone):
  - EOD stock data: weekdays 15:30 SL, plus an hourly safety-net catch-up.
  - Announcements: 09:00, 12:00, 15:00 SL.
  - 22K gold price: 10:00 and 15:30 SL (scraped from ideabeam.com).
- **Startup backfill** — on launch, detects missing trading days and fills the
  gap.

## Quickstart

### 1. MySQL

Either run MySQL in Docker:

```bash
docker run -d --name cse-mysql \
  -e MYSQL_ROOT_PASSWORD=changeme \
  -p 3306:3306 \
  -v cse-mysql-data:/var/lib/mysql \
  mysql:8
```

…or use an existing standalone MySQL 8 instance.

Create a dedicated user (adjust the password):

```sql
CREATE USER 'cse'@'%' IDENTIFIED BY 'your-strong-password';
GRANT ALL PRIVILEGES ON cse_db.* TO 'cse'@'%';
FLUSH PRIVILEGES;
```

### 2. Schema

Apply the schema and migrations in order. They are idempotent.

```bash
mysql -h 127.0.0.1 -u cse -p < schema.sql
mysql -h 127.0.0.1 -u cse -p cse_db < migrate_v2.sql
mysql -h 127.0.0.1 -u cse -p cse_db < migrate_targets.sql
mysql -h 127.0.0.1 -u cse -p cse_db < migrate_v2_active.sql
mysql -h 127.0.0.1 -u cse -p cse_db < cse_db_triggers.sql
```

### 3. App

```bash
git clone https://github.com/sachithmuhandiram/cse-dashboard.git
cd cse-dashboard

cp .env.example .env
# Edit .env and set DB_PASSWORD (and DB_HOST etc. if not localhost).

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 app.py
```

Open <http://localhost:5050>. Add tickers from <http://localhost:5050/manage>.

### 4. (optional) Run as a systemd service

A sample unit lives in `cse-dashboard.service`. Edit the `User=` and
`WorkingDirectory=` fields, then:

```bash
sudo cp cse-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cse-dashboard
```

## Configuration

All DB settings come from `.env` (see `.env.example`):

| Variable     | Default     | Notes                                |
| ------------ | ----------- | ------------------------------------ |
| `DB_HOST`    | `127.0.0.1` |                                      |
| `DB_PORT`    | `3306`      |                                      |
| `DB_NAME`    | `cse_db`    |                                      |
| `DB_USER`    | `cse`       |                                      |
| `DB_PASSWORD`| (required)  | Must match the MySQL user you created |

The tracked symbol list is no longer hardcoded — it lives in the `stocks`
table with an `active` flag, managed from the `/manage` page.

## Project layout

```
app.py                       Flask app, routes, scheduler wiring
db_config.py                 Loads DB_CONFIG from .env
get_daily_trades.py          CSE API client + daily_data upsert
get_financial_announcements.py  Announcement scraper
fetch_gold_price.py          22K gold price scraper (ideabeam.com)
templates/                   Jinja templates (base, index, stock, gold, manage)
schema.sql                   Core schema (stocks, daily_data, fetch_log)
migrate_v2.sql               Announcements table
migrate_targets.sql          Stock target / rating bands
migrate_v2_active.sql        active flag on stocks
cse_db_triggers.sql          DB triggers
cse-dashboard.service        Sample systemd unit
```

## Credits

- **CSE API endpoints, request payloads, and response shapes** — all reverse-
  engineered and documented by
  [GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation](https://github.com/GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation).
  This dashboard would not exist without that work. The endpoint catalogue,
  field names, and the `companyChartDataByStock` / `detailedTrades` /
  `getFinancialAnnouncement` calls used by `get_daily_trades.py` and
  `get_financial_announcements.py` all originate from that project.
- **22K gold price** — scraped from [ideabeam.com](https://ideabeam.com).

## License

The upstream CSE API documentation is unofficial; this project inherits no
warranty. Use at your own discretion.
