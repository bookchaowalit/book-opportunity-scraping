#!/usr/bin/env python3
"""
Scrape exchange rates via Frankfurter API (free, ECB rates, no auth).
Tracks THB against major currencies and detects significant moves.

Outputs:
    - domains/money/finance/book-finance/data/exchange_rates.csv (latest snapshot)
    - domains/money/finance/book-finance/data/exchange_history.csv (appended daily)

Usage:
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_exchange_rates.py
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_exchange_rates.py --base THB
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_exchange_rates.py --symbols USD,EUR,JPY,GBP,CNY
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_exchange_rates.py --alert-threshold 0.5
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[4]  # solo-empire/
OUTPUT_DIR = ROOT / "domains" / "book-finance" / "data"

FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"

DEFAULT_BASE = "THB"
DEFAULT_SYMBOLS = ["USD", "EUR", "JPY", "GBP", "CNY", "SGD", "HKD", "AUD", "KRW", "MYR"]


def fetch_latest(base: str, symbols: list) -> dict:
    """Fetch latest exchange rates."""
    symbols_str = ",".join(symbols)
    url = f"{FRANKFURTER_BASE}/latest"
    params = {"from": base, "to": symbols_str}
    resp = httpx.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {
        "base": data.get("base", base),
        "date": data.get("date", ""),
        "rates": data.get("rates", {}),
    }


def fetch_history(base: str, symbols: list, days: int = 30) -> list:
    """Fetch historical rates for trend detection."""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    symbols_str = ",".join(symbols)
    url = f"{FRANKFURTER_BASE}/{start_date}..{end_date}"
    params = {"from": base, "to": symbols_str}
    resp = httpx.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return [
        {"date": date, "rates": rates}
        for date, rates in sorted(data.get("rates", {}).items())
    ]


def detect_trend(history: list, symbol: str, lookback: int = 7) -> dict:
    """Detect trend direction over last N days."""
    if len(history) < lookback:
        return {"direction": "unknown", "change_pct": 0}

    recent = history[-lookback:]
    first_rate = recent[0]["rates"].get(symbol)
    last_rate = recent[-1]["rates"].get(symbol)

    if not first_rate or not last_rate:
        return {"direction": "unknown", "change_pct": 0}

    change_pct = ((last_rate - first_rate) / first_rate) * 100

    if change_pct > 0.5:
        direction = "strengthening"  # base currency getting stronger
    elif change_pct < -0.5:
        direction = "weakening"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "change_pct": round(change_pct, 3),
        "from_rate": first_rate,
        "to_rate": last_rate,
    }


def save_rates(data: dict, output_dir: Path, trends: dict = None):
    """Save latest rates to CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rates_file = output_dir / "exchange_rates.csv"
    fieldnames = ["date", "base", "currency", "rate", "inverse", "trend_7d", "trend_change_pct", "updated_at"]

    rows = []
    for currency, rate in data["rates"].items():
        trend = trends.get(currency, {}) if trends else {}
        rows.append({
            "date": data["date"],
            "base": data["base"],
            "currency": currency,
            "rate": rate,
            "inverse": round(1 / rate, 6) if rate else "",
            "trend_7d": trend.get("direction", ""),
            "trend_change_pct": trend.get("change_pct", ""),
            "updated_at": now,
        })

    with open(rates_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Saved {len(rows)} rates to {rates_file}")


def append_history(data: dict, output_dir: Path):
    """Append daily history."""
    history_file = output_dir / "exchange_history.csv"
    file_exists = history_file.exists()

    fieldnames = ["date", "base", "currency", "rate"]
    rows = []
    for currency, rate in data["rates"].items():
        rows.append({
            "date": data["date"],
            "base": data["base"],
            "currency": currency,
            "rate": rate,
        })

    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    print(f"  Appended {len(rows)} rows to {history_file}")


def print_summary(data: dict, trends: dict, threshold: float):
    """Print rate summary and alerts."""
    print(f"\n  Rates ({data['date']}, base: {data['base']}):")
    for currency, rate in sorted(data["rates"].items()):
        trend = trends.get(currency, {})
        direction = trend.get("direction", "")
        change = trend.get("change_pct", 0)
        arrow = "+" if change > 0 else "-" if change < 0 else "="

        alert = ""
        if abs(change) >= threshold:
            alert = f" *** ALERT: {abs(change):.2f}% move in 7 days"

        print(f"    1 {data['base']} = {rate:.4f} {currency}  [{arrow} {change:+.3f}% 7d {direction}]{alert}")


def main():
    parser = argparse.ArgumentParser(description="Scrape exchange rates via Frankfurter API")
    parser.add_argument("--base", default=DEFAULT_BASE,
                        help=f"Base currency (default: {DEFAULT_BASE})")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                        help="Comma-separated target currencies")
    parser.add_argument("--alert-threshold", type=float, default=0.5,
                        help="Alert on 7-day change >= this %% (default: 0.5)")
    parser.add_argument("--no-history", action="store_true",
                        help="Skip historical data fetch")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    output_dir = Path(args.output_dir)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exchange Rate Scraper")
    print(f"  Base: {args.base} | Symbols: {symbols}")

    # Fetch latest
    print("  Fetching latest rates...")
    data = fetch_latest(args.base, symbols)
    print(f"  Got {len(data['rates'])} rates (date: {data['date']})")

    # Fetch history for trends
    trends = {}
    if not args.no_history:
        print("  Fetching 30-day history for trend analysis...")
        try:
            history = fetch_history(args.base, symbols, days=30)
            for symbol in symbols:
                trends[symbol] = detect_trend(history, symbol, lookback=7)
        except Exception as e:
            print(f"  History fetch failed: {e}")

    # Save
    save_rates(data, output_dir, trends)
    append_history(data, output_dir)

    # Summary
    print_summary(data, trends, args.alert_threshold)

    print("\n  Done.")


class ExchangeRateScraper:
    """Wrapper class for scheduler compatibility."""
    def __init__(self, base=None, symbols=None, alert_threshold=0.5, **kwargs):
        self.base = base or DEFAULT_BASE
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.alert_threshold = alert_threshold

    async def run(self, **kwargs):
        print(f"[ExchangeRateScraper] Fetching rates (base={self.base})...")
        data = fetch_latest(self.base, self.symbols)
        trends = {}
        try:
            history = fetch_history(self.base, self.symbols, days=30)
            for s in self.symbols:
                trends[s] = detect_trend(history, s, lookback=7)
        except Exception:
            pass
        output_dir = OUTPUT_DIR
        save_rates(data, output_dir, trends)
        append_history(data, output_dir)
        print_summary(data, trends, self.alert_threshold)
        return [{"source": "exchange_rates", "count": len(data.get('rates', {}))}]


if __name__ == "__main__":
    main()
