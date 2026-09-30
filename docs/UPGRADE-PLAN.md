# Upgrade plan — book-opportunity-scraping

## Current state

Score: **5/10** (pass 1: 1 -> 4; pass 2: 4 -> 4.5; pass 3: 4.5 -> 5) — every script runs
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
- Fixture tests still missing: `scrape_stock_prices.py`,
  `scrape_seo_rankings.py`, `scrape_defi_yields.py` output writers.
- `scrape_flight_prices.main` drops Skyscanner fares >= 9,999 THB
  (`priced` filter) so long-haul routes never record a price; confirm the
  intent and replace with a per-route sanity band.
- Route the remaining `open(..., "w"/"a")` writers (stocks, SEO, DeFi, money
  script) through `atomic_io.py`.
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

## Done in this pass (pass 3)
- `atomic_io.py`: crypto, FX, flight and AI-tool snapshots/histories written
  atomically (history = atomic rewrite of old + new, no torn rows).
- Fixed alerts that could never fire: `scrape_flight_prices.main` read the
  "previous" price after appending this run, and `scrape_ai_tools.main` read
  "seen" URLs after appending (new `persist_tools()`); both now read first.
- Fixed `parse_skyscanner` crash on a bare `฿,` (`int("")`); ProductHunt/TAAFT
  parsers dedupe repeated links. CoinGecko trending tolerates partial entries
  (`parse_trending`); Frankfurter payloads normalised (`parse_latest`,
  `parse_history`, non-numeric rates dropped); FX history skips duplicate
  `(date, base, currency)` rows.
- CLI validation before any request: crypto ids/currencies (dedupe, max 50),
  FX ISO codes (base excluded from symbols), non-negative thresholds, flight
  `--days-ahead` 1-180 and `--alert-drop-pct` (0, 100].
- 7 new fixtures + `tests/test_market_sources.py` (22 -> 47 tests incl.
  parametrised). User-Agent and `scrape_fb_local.py` untouched (owner P0/P1).
- Bug-pattern sweep (`tests/test_bug_pattern_sweep.py`, 4 tests): DeFi
  `filter_pools` rejects NaN/inf/non-numeric APY and TVL (NaN passed every
  bound); Kiwi departure/return and Yahoo market times rendered in UTC, not
  host-local time; flight `airline` keeps route order (was set order, so
  the column changed between identical runs); `scrape_fb_local` email
  extraction keeps first-seen order (`emails[0]` depended on set order).
- Shared `scraper_dashboard.json`: an unreadable file is left untouched (it
  was replaced by a dict holding only the opportunities section, wiping the
  other scrapers' sections) and the update is written atomically
  (`tests/test_dashboard_merge.py`).
- Host matching: SEO `check_ranking` counts a result only when its host is
  the target domain or a subdomain (a substring of the URL counted spoofed
  and query-string mentions), and the Google/YouTube exclusion, the
  Reddit/Etsy/eBay/ProductHunt/TAAFT result filters and the Facebook
  filter (which also decided which URLs get fetched) use `host_matches`.
