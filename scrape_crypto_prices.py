#!/usr/bin/env python3
"""
Scrape cryptocurrency prices via CoinGecko API (free, no auth required).
Tracks prices, 24h changes, and alerts on significant movements.

Outputs:
    - data/book-finance/crypto_prices.csv (latest snapshot)
    - data/book-finance/crypto_history.csv (appended daily)
    - Console alerts for >5% 24h moves

Usage:
    python3 scrape_crypto_prices.py
    python3 scrape_crypto_prices.py --coins bitcoin,ethereum,solana
    python3 scrape_crypto_prices.py --alert-threshold 3
    python3 scrape_crypto_prices.py --vs-currency thb,usd
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx")
    sys.exit(1)

# Project root
ROOT = Path(__file__).resolve().parent  # repository root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atomic_io import append_csv_atomic, render_csv, write_text_atomic  # noqa: E402

COIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
CURRENCY_RE = re.compile(r"^[a-z]{3,5}$")
MAX_COINS = 50
OUTPUT_DIR = ROOT / "data" / "book-finance"

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

DEFAULT_COINS = [
    "bitcoin", "ethereum", "solana", "binancecoin", "ripple",
    "cardano", "dogecoin", "polkadot", "avalanche-2", "chainlink",
    "polygon-matic", "litecoin", "uniswap", "stellar", "cosmos"
]

DEFAULT_CURRENCIES = ["usd", "thb"]


def fetch_prices(coins: list, currencies: list) -> dict:
    """Fetch current prices from CoinGecko."""
    ids_str = ",".join(coins)
    curr_str = ",".join(currencies)
    url = f"{COINGECKO_BASE}/simple/price"
    params = {
        "ids": ids_str,
        "vs_currencies": curr_str,
        "include_24hr_change": "true",
        "include_24hr_vol": "true",
        "include_market_cap": "true",
        "include_last_updated_at": "true",
    }
    resp = httpx.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_trending() -> list:
    """Fetch trending coins (top 7 by search activity).

    Entries without an ``item`` object or an ``id`` are skipped instead of
    raising ``KeyError`` on a partial payload.
    """
    url = f"{COINGECKO_BASE}/search/trending"
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    return parse_trending(resp.json())


def parse_trending(data) -> list:
    """Normalise a CoinGecko ``/search/trending`` payload."""
    coins = data.get("coins", []) if isinstance(data, dict) else []
    trending = []
    for coin in coins if isinstance(coins, list) else []:
        item = coin.get("item") if isinstance(coin, dict) else None
        if not isinstance(item, dict) or not item.get("id"):
            continue
        trending.append({
            "id": item["id"],
            "name": item.get("name", ""),
            "symbol": item.get("symbol", ""),
            "market_cap_rank": item.get("market_cap_rank", ""),
            "score": item.get("score", ""),
        })
    return trending


def save_prices(data: dict, currencies: list, output_dir: Path):
    """Save price snapshot to CSV (written atomically)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Latest snapshot
    prices_file = output_dir / "crypto_prices.csv"
    rows = []
    for coin_id, info in data.items():
        if not isinstance(info, dict):
            continue
        for curr in currencies:
            price_key = curr
            change_key = f"{curr}_24h_change"
            vol_key = f"{curr}_24h_vol"
            mcap_key = f"{curr}_market_cap"

            rows.append({
                "coin_id": coin_id,
                "currency": curr,
                "price": info.get(price_key, ""),
                "change_24h_pct": round(info.get(change_key, 0) or 0, 2),
                "volume_24h": info.get(vol_key, ""),
                "market_cap": info.get(mcap_key, ""),
                "updated_at": now,
            })

    fieldnames = ["coin_id", "currency", "price", "change_24h_pct", "volume_24h", "market_cap", "updated_at"]
    write_text_atomic(prices_file, render_csv(rows, fieldnames))

    print(f"  Saved {len(rows)} rows to {prices_file}")


def append_history(data: dict, currencies: list, output_dir: Path):
    """Append a history entry (old + new rewritten atomically)."""
    history_file = output_dir / "crypto_history.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fieldnames = ["date", "coin_id", "currency", "price", "change_24h_pct", "market_cap"]
    rows = []
    for coin_id, info in data.items():
        if not isinstance(info, dict):
            continue
        for curr in currencies:
            rows.append({
                "date": now,
                "coin_id": coin_id,
                "currency": curr,
                "price": info.get(curr, ""),
                "change_24h_pct": round(info.get(f"{curr}_24h_change", 0) or 0, 2),
                "market_cap": info.get(f"{curr}_market_cap", ""),
            })

    append_csv_atomic(history_file, rows, fieldnames)

    print(f"  Appended {len(rows)} rows to {history_file}")


def save_trending(trending: list, output_dir: Path):
    """Save trending coins (written atomically)."""
    trending_file = output_dir / "crypto_trending.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fieldnames = ["date", "id", "name", "symbol", "market_cap_rank", "score"]
    write_text_atomic(trending_file, render_csv(({"date": now, **coin} for coin in trending), fieldnames))

    print(f"  Saved {len(trending)} trending coins to {trending_file}")


def print_alerts(data: dict, threshold: float, currencies: list):
    """Print alerts for coins with significant 24h moves."""
    alerts = []
    for coin_id, info in data.items():
        if not isinstance(info, dict):
            continue
        for curr in currencies:
            change = info.get(f"{curr}_24h_change", 0) or 0
            if abs(change) >= threshold:
                direction = "UP" if change > 0 else "DOWN"
                price = info.get(curr, "N/A")
                alerts.append({
                    "coin": coin_id,
                    "currency": curr,
                    "price": price,
                    "change": round(change, 2),
                    "direction": direction,
                })

    if alerts:
        print(f"\n  ALERTS ({threshold}% threshold):")
        for a in sorted(alerts, key=lambda x: abs(x["change"]), reverse=True):
            emoji = "+" if a["direction"] == "UP" else "-"
            print(f"    {emoji} {a['coin'].upper()}: {a['price']} {a['currency'].upper()} ({a['change']:+.2f}%)")
    else:
        print(f"\n  No alerts (all moves < {threshold}%)")

    return alerts


def _csv_list(pattern, label: str, limit: int):
    """argparse type: comma-separated, lower-cased, de-duplicated, validated ids."""
    def parse(value: str) -> list:
        items = []
        for raw in value.split(","):
            item = raw.strip().lower()
            if not item or item in items:
                continue
            if not pattern.match(item):
                raise argparse.ArgumentTypeError(f"invalid {label}: {raw.strip()!r}")
            items.append(item)
        if not items:
            raise argparse.ArgumentTypeError(f"at least one {label} is required")
        if len(items) > limit:
            raise argparse.ArgumentTypeError(f"at most {limit} {label}s per run")
        return items
    return parse


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scrape crypto prices via CoinGecko API")
    parser.add_argument("--coins", type=_csv_list(COIN_ID_RE, "coin id", MAX_COINS),
                        default=list(DEFAULT_COINS),
                        help="Comma-separated coin IDs (default: top 15)")
    parser.add_argument("--vs-currencies", type=_csv_list(CURRENCY_RE, "currency", 10),
                        default=list(DEFAULT_CURRENCIES),
                        help="Comma-separated fiat currencies (default: usd,thb)")
    parser.add_argument("--alert-threshold", type=float, default=5.0,
                        help="Alert on 24h change >= this %% (default: 5)")
    parser.add_argument("--trending", action="store_true", default=True,
                        help="Also fetch trending coins")
    parser.add_argument("--no-trending", action="store_true",
                        help="Skip trending coins")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory (default: book-finance/data/)")
    args = parser.parse_args(argv)
    if not args.alert_threshold >= 0:
        parser.error("--alert-threshold must be zero or positive")

    coins = args.coins
    currencies = args.vs_currencies
    output_dir = Path(args.output_dir)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Crypto Price Scraper")
    print(f"  Coins: {len(coins)} | Currencies: {currencies}")

    # Fetch prices
    print("  Fetching prices...")
    data = fetch_prices(coins, currencies)
    print(f"  Got {len(data)} coins")

    # Save
    save_prices(data, currencies, output_dir)
    append_history(data, currencies, output_dir)

    # Trending
    if args.trending and not args.no_trending:
        print("  Fetching trending...")
        try:
            trending = fetch_trending()
            save_trending(trending, output_dir)
        except Exception as e:
            print(f"  Trending failed: {e}")

    # Alerts
    print_alerts(data, args.alert_threshold, currencies)

    print("\n  Done.")


class CryptoPriceScraper:
    """Wrapper class for scheduler compatibility."""
    def __init__(self, coins=None, vs_currencies=None, alert_threshold=5.0, **kwargs):
        self.coins = coins or DEFAULT_COINS
        self.currencies = vs_currencies or DEFAULT_CURRENCIES
        self.alert_threshold = alert_threshold

    async def run(self, **kwargs):
        print(f"[CryptoPriceScraper] Fetching {len(self.coins)} coins...")
        data = fetch_prices(self.coins, self.currencies)
        output_dir = OUTPUT_DIR
        save_prices(data, self.currencies, output_dir)
        append_history(data, self.currencies, output_dir)
        try:
            trending = fetch_trending()
            save_trending(trending, output_dir)
        except Exception:
            pass
        print_alerts(data, self.alert_threshold, self.currencies)
        return [{"source": "crypto", "count": len(data)}]


if __name__ == "__main__":
    main()
