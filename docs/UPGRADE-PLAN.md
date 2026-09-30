# Upgrade plan — book-opportunity-scraping

## Current state

Score: **4/10** (was 1/10) — every script now imports and runs from a
standalone clone, core scoring logic is tested, lint/CI exist. Still a loose
bag of scripts with browser-UA/search-engine scraping and one PII-harvesting
script.

## Backlog

### P0
- Owner decision on `scrape_fb_local.py`: it collects personal e-mail
  addresses from Facebook group posts for outreach. Recommended: delete it, or
  restrict it to role addresses (hr@/jobs@) and company pages with a lawful
  basis under PDPA. Until then do not schedule it.

### P1
- Add a shared `http_client.py` (identifying UA, timeout, bounded retry on
  429/5xx, per-host delay) and route all scripts through it; tested pattern
  exists in `book-restaurant-scraping/restaurants/http.py`.
- Replace search-engine HTML scraping (DDG/Bing/Brave/Google) with official
  APIs or drop those sources.
- Add fixture tests for each parser (`scrape_hackernews`, GitHub trending,
  DeFi/crypto JSON) using saved responses under `tests/fixtures/`.
- Split `opportunities/scrape_money_opportunities.py` (1.8k lines) into
  sources / scoring / outputs modules.

### P2
- Move the domain scripts (crypto, FX, stocks, DeFi, flights) to their
  `book-*-data` lake products as the README boundary suggests.
- `setup_cron()` in the money script writes to crontab directly; replace with
  a reviewed `setup_cron.sh plan|install` like the sibling scraper repos.

## Done in this pass
- Fixed monorepo `parents[4]` path lookups (IndexError on import in 8
  scripts) and the hard `db_connect` import; outputs now go to repo `data/`.
- `scrape_flight_prices.py` now actually parses its documented CLI flags
  (they were silently ignored) and honours `--output-dir`.
- AI keyword scoring used substring matching ("said", "email", "Thailand"
  counted as AI); now whole-word for short tokens. Short titles no longer
  fuzzy-merge unrelated items.
- `scrape_fb_local.py`: e-mails masked in logs; contact file kept inside the
  repository's ignored `data/`.
- Removed runtime `pip install`; added `requirements.txt`, ruff, pytest
  config, 14 offline tests, CI; untracked committed runtime data, `cron.log`
  (contained a local home path) and `__pycache__`.
