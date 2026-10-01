#!/usr/bin/env python3
"""
Scrape exchange rates via Frankfurter API (free, ECB rates, no auth).
Tracks THB against major currencies and detects significant moves.

Outputs:
    - data/book-finance/exchange_rates.csv (latest snapshot)
    - data/book-finance/exchange_history.csv (appended daily)

Usage:
    python3 scrape_exchange_rates.py
    python3 scrape_exchange_rates.py --base THB
    python3 scrape_exchange_rates.py --symbols USD,EUR,JPY,GBP,CNY
    python3 scrape_exchange_rates.py --alert-threshold 0.5
"""

import argparse
import csv
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent  # repository root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atomic_io import render_csv, write_text_atomic  # noqa: E402

CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")
OUTPUT_DIR = ROOT / "data" / "book-finance"

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
    return parse_latest(resp.json(), base)


def parse_latest(data, base: str) -> dict:
    """Normalise a Frankfurter ``/latest`` payload; non-numeric rates are dropped."""
    data = data if isinstance(data, dict) else {}
    rates = data.get("rates") if isinstance(data.get("rates"), dict) else {}
    return {
        "base": data.get("base", base),
        "date": data.get("date", ""),
        "rates": {
            code: float(rate)
            for code, rate in rates.items()
            if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0
        },
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
    return parse_history(resp.json())


def parse_history(data) -> list:
    """Normalise a Frankfurter time-series payload into date-sorted rows."""
    rates = data.get("rates") if isinstance(data, dict) else None
    if not isinstance(rates, dict):
        return []
    return [
        {"date": date, "rates": day}
        for date, day in sorted(rates.items())
        if isinstance(day, dict)
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
    """Save latest rates to CSV (written atomically)."""
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

    write_text_atomic(rates_file, render_csv(rows, fieldnames))

    print(f"  Saved {len(rows)} rates to {rates_file}")


def append_history(data: dict, output_dir: Path) -> int:
    """Append one row per currency for the rate date, skipping duplicates.

    ECB reference rates are fixed per date, so re-running on the same day (or
    over a weekend, when ``date`` stays on Friday) must not add duplicate
    ``(date, base, currency)`` rows. Old + new rows are rewritten atomically.
    Returns the number of rows added.
    """
    history_file = output_dir / "exchange_history.csv"
    fieldnames = ["date", "base", "currency", "rate"]
    existing_text = history_file.read_text(encoding="utf-8") if history_file.exists() else ""
    seen = {
        (row.get("date"), row.get("base"), row.get("currency"))
        for row in csv.DictReader(existing_text.splitlines())
    } if existing_text else set()

    rows = []
    for currency, rate in data["rates"].items():
        key = (data["date"], data["base"], currency)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "date": data["date"],
            "base": data["base"],
            "currency": currency,
            "rate": rate,
        })

    if rows or not existing_text:
        if existing_text and not existing_text.endswith("\n"):
            existing_text += "\r\n"
        write_text_atomic(history_file, existing_text + render_csv(rows, fieldnames, header=not existing_text))

    print(f"  Appended {len(rows)} rows to {history_file}")
    return len(rows)


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


def _currency_code(value: str) -> str:
    code = value.strip().upper()
    if not CURRENCY_CODE_RE.match(code):
        raise argparse.ArgumentTypeError(f"expected a 3-letter ISO currency code, got {value!r}")
    return code


def _currency_codes(value: str) -> list:
    codes = []
    for raw in value.split(","):
        if raw.strip():
            code = _currency_code(raw)
            if code not in codes:
                codes.append(code)
    if not codes:
        raise argparse.ArgumentTypeError("at least one currency code is required")
    return codes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scrape exchange rates via Frankfurter API")
    parser.add_argument("--base", type=_currency_code, default=DEFAULT_BASE,
                        help=f"Base currency (default: {DEFAULT_BASE})")
    parser.add_argument("--symbols", type=_currency_codes, default=list(DEFAULT_SYMBOLS),
                        help="Comma-separated target currencies")
    parser.add_argument("--alert-threshold", type=float, default=0.5,
                        help="Alert on 7-day change >= this %% (default: 0.5)")
    parser.add_argument("--no-history", action="store_true",
                        help="Skip historical data fetch")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory")
    args = parser.parse_args(argv)
    if not args.alert_threshold >= 0:
        parser.error("--alert-threshold must be zero or positive")

    symbols = [code for code in args.symbols if code != args.base]
    if not symbols:
        parser.error("--symbols must include at least one currency other than --base")
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
