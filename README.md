# book-opportunity-scraping

**Tier:** C / tool prototype (portfolio breadth, not interview flagship)  
**Owner path:** `bookchaowalit/book-apps/tools/book-opportunity-scraping`

## Purpose

Loose bag of opportunity/market scrape scripts (crypto, DeFi, FX, flights, SEO, stocks, FB local, AI tools).

## Entry points

| Script | What it collects | Output (git-ignored) |
| --- | --- | --- |
| `opportunities/scrape_money_opportunities.py` | HN, GitHub, Reddit/Etsy/eBay via search, scored opportunities | `opportunities/data/` |
| `scrape_ai_tools.py` | AI tool directories | `data/book-ai/` |
| `scrape_crypto_prices.py`, `scrape_defi_yields.py`, `scrape_exchange_rates.py`, `scrape_stock_prices.py` | market prices/yields | `data/book-finance/` |
| `scrape_flight_prices.py` | flight prices for fixed routes | `data/book-travel/` |
| `scrape_seo_rankings.py` | search rankings for a domain | `data/book-marketing/` |
| `scrape_fb_local.py` | job posts in Facebook groups via search (see privacy note) | `data/contact_emails.json` |

## Stack

Python 3.10+ scripts at the repository root; dependencies in `requirements.txt`.

## How to run (local)

```bash
# From this repository root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scrape_crypto_prices.py --help
python3 scrape_flight_prices.py --routes BKK-SIN,BKK-TYO
python3 opportunities/scrape_money_opportunities.py --help
```

All scripts now resolve paths from this repository (the old monorepo
`parents[4]` lookup crashed every script on import in a standalone clone).
`scrape_money_opportunities.py` only enables its SQLite action tracker and
dashboard merge when a parent Solo Empire checkout is found (walk-up or
`SOLO_EMPIRE_ROOT`); otherwise those features are skipped.

## Privacy and crawling (honest)

- `scrape_fb_local.py` harvests non-generic (i.e. likely personal) e-mail
  addresses from Facebook group posts found via Bing. Console/cron output now
  masks them (`j***@domain`) and the contact file stays in git-ignored
  `data/`, but the collection itself is a PDPA/Facebook-ToS risk; see
  `docs/UPGRADE-PLAN.md` P0.
- Several scripts send browser-like User-Agents and scrape search-engine HTML
  (DuckDuckGo/Bing/Brave/Google). Requests have timeouts; there is no shared
  retry/backoff or robots.txt handling yet.
- Runtime data (`opportunities/data/`, `data/`) and `cron.log` are not
  committed.

## Checks (offline)

```bash
pip install -r requirements.txt pytest ruff
ruff check .
python -m pytest -q
```

Tests cover scoring, keyword matching, dedupe, route parsing and e-mail
masking without network access; CI (`.github/workflows/ci.yml`) runs them.

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
