# RTO Dashboard — FDP Automation Tool

Scrapes RTO / ZRTO data from FDP (QAAS) via direct API calls and refreshes the CSV used by the Streamlit dashboard.

## Files

- `scraper.py` — automation agent (Playwright cookie extraction + QAAS REST API)
- `config.yaml` — scraper configuration (API, output paths, GitHub push)
- `query.sql` — the SQL query to execute (supports `{end_date}` placeholder → yesterday, YYYYMMDD)
- `run_scraper.bat` — Windows launcher that loads `.env` and runs the scraper
- `.env.example` — copy to `.env` and fill in FDP_USERNAME / FDP_PASSWORD
- `app.py` — Streamlit dashboard (reads `601168f592cc35c1ef35fc3672be19d9.csv`)

## First-time setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env   # then edit .env with your LDAP creds
```

Paste your QAAS SQL into `query.sql`. Use `{end_date}` anywhere you want yesterday auto-substituted.

## Run

```powershell
run_scraper.bat
```

Or directly:

```powershell
python scraper.py
```

Output:

1. Raw CSV lands in `downloads/`.
2. It is then moved to `data/rto_data_<YYYY-MM-DD>.csv`.
3. A copy is also written to `601168f592cc35c1ef35fc3672be19d9.csv` in the project root so the Streamlit dashboard picks up fresh data on next load (clear Streamlit cache if needed).

## Schedule (Windows)

Create a Task Scheduler job that runs `run_scraper.bat` at your preferred time (default reference: 08:00 IST in `config.yaml`).
