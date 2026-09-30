# Upgrade plan — book-opportunity-scraping

## Current state

Score: **4.5/10** (pass 1: 1 -> 4; pass 2: 4 -> 4.5) — every script runs
from a standalone clone; scoring and the HN / GitHub / DeFiLlama JSON sources
are fixture-tested; lint/CI exist. Still a loose bag of scripts with
browser-UA/search-engine scraping and one PII-harvesting script.

## Backlog

### P0
- Owner decision on `scrape_fb_local.py`: it collects personal e-mail
  addresses from Facebook group posts for outreach. Recommended: delete it, or
  restrict it to role addresses (hr@/jobs@) and company pages with a lawful
  basis under PDPA. Until then do not schedule it.

### P1
- Add a shared `http_client.py` (timeout, bounded retry on 429/5xx, per-host
  delay) and route all scripts through it; tested pattern exists in
  `book-restaurant-scraping/restaurants/http.py`. Owner decision needed first
  on the browser `User-Agent` the live scripts send (kept unchanged so far).
- Replace search-engine HTML scraping (DDG/Bing/Brave/Google) with official
  APIs or drop those sources.
- Remaining fixture tests: crypto (CoinGecko) and FX JSON, `parse_producthunt`
  / `parse_taft` / `parse_skyscanner` markdown parsers.
- Split `opportunities/scrape_money_opportunities.py` (1.8k lines) into
  sources / scoring / outputs modules.

### P2
- Move the domain scripts (crypto, FX, stocks, DeFi, flights) to their
  `book-*-data` lake products as the README boundary suggests.
- `setup_cron()` in the money script writes to crontab directly; replace with
  a reviewed `setup_cron.sh plan|install` like the sibling scraper repos.

## Done in this pass (pass 1)
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

## Done in this pass (pass 2)
- Fixture-replay tests (`tests/test_source_parsers.py`, `tests/fixtures/*.json`)
  for `scrape_hackernews`, `scrape_github_trending` and the DeFiLlama pool
  filter / stablecoin / opportunity detection, including HTTP-failure paths
  (14 -> 22 tests).
- Fixed a crash: `detect_stablecoin_pools` raised `AttributeError` on a pool
  whose `symbol` is JSON `null`.
- GitHub trending note no longer claims "stars today" (it is total stars on a
  repo created in the last 7 days).
- `scrape_fb_local.py` untouched pending the owner decision (P0).
