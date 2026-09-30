#!/usr/bin/env python3
"""
Scrape stock/crypto portfolio prices via Yahoo Finance API (free, no auth).
Tracks prices, daily changes, and alerts on significant movements.

Outputs:
    - data/book-finance/stock_prices.csv (latest snapshot)
    - data/book-finance/stock_history.csv (appended)
    - Console alerts for >3% daily moves

Usage:
    python3 scrape_stock_prices.py
    python3 scrape_stock_prices.py --symbols AAPL,MSFT,GOOGL
    python3 scrape_stock_prices.py --alert-threshold 2
    python3 scrape_stock_prices.py --no-history
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "data" / "book-finance"

# Yahoo Finance v8 API (free, no auth)
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

# Default portfolio: major tech + Thai ETFs + index proxies
DEFAULT_SYMBOLS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",   # US Big Tech
    "META", "TSLA", "AMD", "CRM", "PLTR",       # Growth
    "SPY", "QQQ",                                # ETFs
    "BTC-USD", "ETH-USD",                        # Crypto via Yahoo
    "^SET50",                                     # Thai market proxy
]


def fetch_quote(symbol: str) -> dict:
    """Fetch current price data from Yahoo Finance."""
    url = f"{YAHOO_BASE}/{symbol}"
    params = {"interval": "1d", "range": "5d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return {}
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("chartPreviousClose", meta.get("previousClose", 0))
        change = price - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0
        return {
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "change": round(change, 4),
            "change_pct": round(change_pct, 2),
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("exchangeName", ""),
            "timestamp": datetime.fromtimestamp(meta.get("regularMarketTime", 0)).strftime("%Y-%m-%d %H:%M:%S") if meta.get("regularMarketTime") else "",
        }
    except Exception as e:
        print(f"  Warning: Failed to fetch {symbol}: {e}")
        return {}


def fetch_quotes(symbols: list) -> list:
    """Fetch prices for all symbols."""
    quotes = []
    for sym in symbols:
        q = fetch_quote(sym)
        if q:
            quotes.append(q)
    return quotes


def load_previous_prices() -> dict:
    """Load previous prices from history for trend detection."""
    history_file = OUTPUT_DIR / "stock_history.csv"
    prices = {}
    if history_file.exists():
        with open(history_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                prices[row["symbol"]] = float(row.get("price", 0))
    return prices


def save_prices(quotes: list):
    """Save latest price snapshot."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / "stock_prices.csv"
    fieldnames = ["symbol", "price", "prev_close", "change", "change_pct", "currency", "exchange", "timestamp", "scraped_at"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for q in quotes:
            writer.writerow({**q, "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    print(f"  Saved {len(quotes)} quotes to {filepath}")


def append_history(quotes: list):
    """Append to history CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / "stock_history.csv"
    fieldnames = ["symbol", "price", "prev_close", "change", "change_pct", "currency", "exchange", "timestamp", "scraped_at"]
    file_exists = filepath.exists()
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for q in quotes:
            writer.writerow({**q, "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    print(f"  Appended {len(quotes)} rows to {filepath}")


def print_alerts(quotes: list, threshold: float, prev_prices: dict):
    """Print alerts for significant moves."""
    print("\n  Alerts:")
    alerted = False
    for q in quotes:
        sym = q["symbol"]
        pct = q["change_pct"]
        if abs(pct) >= threshold:
            direction = "UP" if pct > 0 else "DOWN"
            print(f"    *** {sym}: {direction} {pct:+.2f}% (${q['price']:.2f}) ***")
            alerted = True
        # Multi-day trend
        if sym in prev_prices and prev_prices[sym] > 0:
            multi_change = (q["price"] - prev_prices[sym]) / prev_prices[sym] * 100
            if abs(multi_change) >= threshold * 2:
                direction = "RISING" if multi_change > 0 else "FALLING"
                print(f"    *** {sym}: {direction} {multi_change:+.2f}% since last check ***")
                alerted = True
    if not alerted:
        print(f"    No alerts (all moves < {threshold}%)")


def main():
    parser = argparse.ArgumentParser(description="Scrape stock/portfolio prices")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                        help="Comma-separated stock symbols")
    parser.add_argument("--alert-threshold", type=float, default=3.0,
                        help="Alert threshold %% for daily moves")
    parser.add_argument("--no-history", action="store_true",
                        help="Skip appending to history")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Stock Price Scraper")
    print(f"  Symbols: {len(symbols)} | Alert: >{args.alert_threshold}%")

    quotes = fetch_quotes(symbols)
    print(f"  Got {len(quotes)} quotes")

    if not quotes:
        print("  ERROR: No quotes fetched. Check network/symbols.")
        sys.exit(1)

    save_prices(quotes)
    if not args.no_history:
        append_history(quotes)

    prev_prices = load_previous_prices()
    print_alerts(quotes, args.alert_threshold, prev_prices)

    # Summary table
    print(f"\n  {'Symbol':12s} {'Price':>12s} {'Change':>10s} {'Currency':>8s}")
    print(f"  {'-'*12} {'-'*12} {'-'*10} {'-'*8}")
    for q in quotes:
        arrow = "+" if q["change_pct"] >= 0 else ""
        print(f"  {q['symbol']:12s} {q['price']:>12.2f} {arrow}{q['change_pct']:>8.2f}% {q['currency']:>8s}")

    print("\n  Done.")


class StockPriceScraper:
    """Wrapper class for scheduler compatibility."""
    def __init__(self, symbols=None, alert_threshold=3.0, **kwargs):
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.alert_threshold = alert_threshold

    async def run(self, **kwargs):
        print(f"[StockPriceScraper] Fetching {len(self.symbols)} symbols...")
        quotes = fetch_quotes(self.symbols)
        if quotes:
            save_prices(quotes)
            append_history(quotes)
            prev_prices = load_previous_prices()
            print_alerts(quotes, self.alert_threshold, prev_prices)
        return [{"source": "stocks", "count": len(quotes)}]


if __name__ == "__main__":
    main()
