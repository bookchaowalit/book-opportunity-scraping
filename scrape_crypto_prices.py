#!/usr/bin/env python3
"""
Scrape cryptocurrency prices via CoinGecko API (free, no auth required).
Tracks prices, 24h changes, and alerts on significant movements.

Outputs:
    - domains/money/finance/book-finance/data/crypto_prices.csv (latest snapshot)
    - domains/money/finance/book-finance/data/crypto_history.csv (appended daily)
    - Console alerts for >5% 24h moves

Usage:
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_crypto_prices.py
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_crypto_prices.py --coins bitcoin,ethereum,solana
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_crypto_prices.py --alert-threshold 3
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_crypto_prices.py --vs-currency thb,usd
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx")
    sys.exit(1)

# Project root
ROOT = Path(__file__).resolve().parents[4]  # solo-empire/
OUTPUT_DIR = ROOT / "domains" / "book-finance" / "data"

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
    """Fetch trending coins (top 7 by search activity)."""
    url = f"{COINGECKO_BASE}/search/trending"
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "id": coin["item"]["id"],
            "name": coin["item"]["name"],
            "symbol": coin["item"]["symbol"],
            "market_cap_rank": coin["item"]["market_cap_rank"],
            "score": coin["item"]["score"],
        }
        for coin in data.get("coins", [])
    ]


def save_prices(data: dict, currencies: list, output_dir: Path):
    """Save price snapshot to CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Latest snapshot
    prices_file = output_dir / "crypto_prices.csv"
    rows = []
    for coin_id, info in data.items():
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
    with open(prices_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Saved {len(rows)} rows to {prices_file}")


def append_history(data: dict, currencies: list, output_dir: Path):
    """Append daily history entry."""
    history_file = output_dir / "crypto_history.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = history_file.exists()

    fieldnames = ["date", "coin_id", "currency", "price", "change_24h_pct", "market_cap"]
    rows = []
    for coin_id, info in data.items():
        for curr in currencies:
            rows.append({
                "date": now,
                "coin_id": coin_id,
                "currency": curr,
                "price": info.get(curr, ""),
                "change_24h_pct": round(info.get(f"{curr}_24h_change", 0) or 0, 2),
                "market_cap": info.get(f"{curr}_market_cap", ""),
            })

    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    print(f"  Appended {len(rows)} rows to {history_file}")


def save_trending(trending: list, output_dir: Path):
    """Save trending coins."""
    output_dir.mkdir(parents=True, exist_ok=True)
    trending_file = output_dir / "crypto_trending.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fieldnames = ["date", "id", "name", "symbol", "market_cap_rank", "score"]
    with open(trending_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for coin in trending:
            writer.writerow({"date": now, **coin})

    print(f"  Saved {len(trending)} trending coins to {trending_file}")


def print_alerts(data: dict, threshold: float, currencies: list):
    """Print alerts for coins with significant 24h moves."""
    alerts = []
    for coin_id, info in data.items():
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


def main():
    parser = argparse.ArgumentParser(description="Scrape crypto prices via CoinGecko API")
    parser.add_argument("--coins", default=",".join(DEFAULT_COINS),
                        help="Comma-separated coin IDs (default: top 15)")
    parser.add_argument("--vs-currencies", default=",".join(DEFAULT_CURRENCIES),
                        help="Comma-separated fiat currencies (default: usd,thb)")
    parser.add_argument("--alert-threshold", type=float, default=5.0,
                        help="Alert on 24h change >= this %% (default: 5)")
    parser.add_argument("--trending", action="store_true", default=True,
                        help="Also fetch trending coins")
    parser.add_argument("--no-trending", action="store_true",
                        help="Skip trending coins")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory (default: book-finance/data/)")
    args = parser.parse_args()

    coins = [c.strip() for c in args.coins.split(",")]
    currencies = [c.strip() for c in args.vs_currencies.split(",")]
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
