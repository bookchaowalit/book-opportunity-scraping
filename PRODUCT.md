# Opportunity listing scraper — successor mapping

Canonical repository: `bookchaowalit/opportunity-listing-scraper` (formerly
`book-opportunity-scraping`). GitHub alias metadata on 2026-10-15 resolves to
this public, unarchived repository. The mapping below covers all eight root
`scrape_*.py` scripts and the aggregator at source commit
`7d135c1bf44e57f99c38f8e54f1f6e79920ab138`.

## Successors

| Legacy entry point | Successor or explicit drop | Contract / boundary |
|---|---|---|
| `scrape_crypto_prices.py` | [`market-data/sources/crypto`](https://github.com/bookchaowalit/market-data/tree/main/sources/crypto) (formerly `book-crypto-data`) | `book_crypto`, `crypto.v1`; source-owned landing/Bronze and read-only API |
| `scrape_stock_prices.py` | [`market-data/sources/stock`](https://github.com/bookchaowalit/market-data/tree/main/sources/stock) (formerly `book-stock-data`) | `book_stock`, `stock.v1` |
| `scrape_exchange_rates.py` | [`market-data/sources/fx`](https://github.com/bookchaowalit/market-data/tree/main/sources/fx) (formerly `book-fx-data`) | `book_fx`, `fx.v1` |
| `scrape_defi_yields.py` | [`market-data/sources/defi`](https://github.com/bookchaowalit/market-data/tree/main/sources/defi) (formerly `book-defi-data`) | `book_defi`, `defi.v1` |
| `scrape_flight_prices.py` | [`travel-flight-price-data`](https://github.com/bookchaowalit/travel-flight-price-data) (formerly `book-flight-data`) | `book_flight`, `flight.v1`; provider policy belongs to the source product |
| `scrape_seo_rankings.py` | [`marketing-seo-ranking-data`](https://github.com/bookchaowalit/marketing-seo-ranking-data) (formerly `book-seo-data`) | `book_seo`, `seo.v1` |
| `scrape_ai_tools.py` | [`tech-ai-tools-data`](https://github.com/bookchaowalit/tech-ai-tools-data) (formerly `book-ai-tools-data`) | `book_ai_tools`, `ai_tools.v1` |
| `scrape_fb_local.py` | **Drop from the successor plan**; no approved domain contract replaces personal-contact harvesting | Existing code remains pending its separate owner disposition in `docs/UPGRADE-PLAN.md`; this mapping does not approve collection, outreach or scheduling |
| `opportunities/scrape_money_opportunities.py` | **Drop cross-domain synthesis**; no replacement mega-aggregator | Architecture retires synthesis. Technology signals belong to [`tech-discovery-data`](https://github.com/bookchaowalit/tech-discovery-data) / `discovery.v1`; other opportunities use their owning domain contracts |

## Migration sequence and limits

This follows the canonical architecture's
[Data Product Portfolio migration order](https://github.com/bookchaowalit/architecture-docs/blob/a550ade4c40592e6f8416b5ee52d603357733629/systems/architecture/data-product-portfolio.md):

1. Retain the coverage registry as inventory; source adapters belong to their
   domain product. Establish its schema and fixtures before moving code.
2. Use the seven independently runnable source products above; keep
   `opportunities/` as human-facing inventory/research, with executable
   discovery in domain products and the shared portfolio CLI.
3. Migrate consumers through APIs, CLIs, exports or versioned packages, then
   verify no direct reads of legacy paths remain.
4. Register the resulting repository and source path before removing or
   deprecating an old implementation.

This is a successor plan, not evidence of completed consumer migration or an
archive decision. The legacy scripts, aggregator's optional Todoist side effect
and cron installer still exist; none was run, removed or enabled by this work.
The existing tests remain offline and do not approve live providers. See
`README.md` for their checks and `docs/UPGRADE-PLAN.md` for remaining work.
