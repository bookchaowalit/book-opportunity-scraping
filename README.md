# book-opportunity-scraping

**Tier:** C / tool prototype (portfolio breadth, not interview flagship)  
**Owner path:** `bookchaowalit/book-apps/tools/book-opportunity-scraping`

## Purpose

Loose bag of opportunity/market scrape scripts (crypto, DeFi, FX, flights, SEO, stocks, FB local, AI tools).

## Entry points

- `scrape_*.py and opportunities/`

## Stack

Python scripts at repo root

## How to run (local)

```bash
# From this repository root
python3 -m venv .venv && source .venv/bin/activate
# Install whatever deps the script imports (often requests/httpx/bs4).
# Prefer reading the scraper module docstring/imports first — no lockfile yet.
python3 scrape_*.py and opportunities/
```

## Boundaries

- **Not** a lake-first data product. Durable market datasets live under `book-*-data` repos.
- **Not** coupled to Solo Empire monorepo runtime. Nested Git repo; commit only inside this tree.
- Never commit `.env`, cookies, session dumps, or scraped PII dumps to Git.

## Limitations (honest)

Not a unified product. Prefer dedicated *-data lake products for durable datasets. Do not commit API keys.

## Related

- Active collection product: `book-job-scraping` (Tier A tool)
- Lake products: `book-crypto-data`, `book-fx-data`, `book-stock-data`, …
- Solo Empire catalog: `repository-catalog/BOOK-DEV-BACKLOG-BD.md` (BD-012)
