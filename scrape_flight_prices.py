#!/usr/bin/env python3
"""
Scrape flight prices from Skyscanner via free httpx+BS4 or Kiwi Tequila API.
Tracks prices for routes you care about, alerts on price drops.

Outputs:
    - data/book-travel/flight_prices.csv (latest snapshot)
    - data/book-travel/flight_prices_history.csv (appended)
    - Console alerts for price drops >15%

Usage:
    python3 scrape_flight_prices.py
    python3 scrape_flight_prices.py --routes BKK-SIN,BKK-TYO
    python3 scrape_flight_prices.py --origin BKK --destinations SIN,TYO,HKG
    python3 scrape_flight_prices.py --alert-drop-pct 15
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parent
    load_dotenv(_root / ".env")
except ImportError:
    pass

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    # Never pip-install at runtime; install requirements.txt into a venv.
    print("ERROR: beautifulsoup4 required. Install: pip install -r requirements.txt")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "data" / "book-travel"

TEQUILA_API_KEY = os.environ.get("TEQUILA_API_KEY", "")
TEQUILA_BASE = "https://api.tequila.kiwi.com"

# Default routes from Bangkok (BKK)
DEFAULT_ROUTES = [
    ("BKK", "SIN"),  # Singapore
    ("BKK", "TYO"),  # Tokyo
    ("BKK", "HKG"),  # Hong Kong
    ("BKK", "ICN"),  # Seoul
    ("BKK", "KUL"),  # Kuala Lumpur
    ("BKK", "SGN"),  # Ho Chi Minh
    ("BKK", "TPE"),  # Taipei
    ("BKK", "MNL"),  # Manila
]


def _brave_search(query: str, limit: int = 10) -> list:
    """Search via Brave Search (no API key needed, works from VPS IPs).
    Falls back to Bing if Brave is rate-limited."""
    import urllib.parse
    try:
        url = f"https://search.brave.com/search?q={query.replace(' ', '+')}"
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}, timeout=15, follow_redirects=True)
        if resp.status_code == 429:
            return _bing_search(query, limit)
        if resp.status_code != 200:
            return _bing_search(query, limit)
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for el in soup.find_all(attrs={'data-pos': True}):
            a_tag = el.find('a', class_='result-header') or el.find('a')
            if not a_tag:
                continue
            href = a_tag.get('href', '')
            if 'click_url=' in href:
                href = urllib.parse.unquote(href.split('click_url=')[1].split('&')[0])
            title = a_tag.get_text(strip=True)
            desc_el = el.find(class_='snippet-description') or el.find('p', class_='')
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
            if title and href and href.startswith('http') and not any(x in href for x in ['duckduckgo.com', 'wikipedia.org']):
                results.append({"title": title[:200], "url": href, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Brave search: {len(results)} results for '{query[:50]}'")
            return results
        return _bing_search(query, limit)
    except Exception as e:
        print(f"  Brave search failed: {e}")
        return _bing_search(query, limit)


def _decode_bing_redirect(href: str) -> str:
    """Decode Bing redirect URL to get actual destination URL."""
    import urllib.parse
    import base64
    if 'bing.com/ck/' not in href or 'u=' not in href:
        return href
    try:
        parsed = urllib.parse.urlparse(href)
        params = urllib.parse.parse_qs(parsed.query)
        if 'u' in params:
            u_val = params['u'][0]
            # Remove 'a1' prefix and decode base64
            if u_val.startswith('a1'):
                b64_part = u_val[2:]
                # Add padding if needed
                padded = b64_part + '=' * (4 - len(b64_part) % 4) if len(b64_part) % 4 else b64_part
                return base64.b64decode(padded).decode('utf-8', errors='ignore')
            return urllib.parse.unquote(u_val)
    except (ValueError, UnicodeDecodeError):
        pass
    return href


def _bing_search(query: str, limit: int = 10) -> list:
    """Fallback search via Bing when Brave is rate-limited."""
    try:
        url = f"https://www.bing.com/search?q={query.replace(' ', '+')}"
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for li in soup.find_all('li', class_='b_algo'):
            a_tag = li.find('h2')
            if not a_tag:
                continue
            a_link = a_tag.find('a', href=True)
            if not a_link:
                continue
            href = _decode_bing_redirect(a_link['href'])
            title = a_link.get_text(strip=True)
            desc_el = li.find('p')
            desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
            if title and href and href.startswith('http') and not any(x in href for x in ['duckduckgo.com', 'wikipedia.org']):
                results.append({"title": title[:200], "url": href, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Bing search: {len(results)} results for '{query[:50]}'")
        return results
    except Exception as e:
        print(f"  Bing search failed: {e}")
        return []


def _firecrawl_search(query: str, limit: int = 10) -> list:
    """Fallback search via Firecrawl API when direct sources fail."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key:
        return []
    try:
        resp = httpx.post(
            "https://api.firecrawl.dev/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"query": query, "limit": limit},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  Firecrawl fallback returned {resp.status_code}")
            return []
        data = resp.json()
        results = []
        for item in data.get("data", []):
            title = item.get("title", "") or item.get("metadata", {}).get("title", "")
            url = item.get("url", "") or item.get("metadata", {}).get("sourceURL", "")
            desc = item.get("description", "") or item.get("markdown", "")[:200]
            if title and url:
                results.append({"title": title[:200], "url": url, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Firecrawl fallback: {len(results)} results for '{query[:50]}'")
        return results
    except Exception as e:
        print(f"  Firecrawl fallback failed: {e}")
        return []


def fetch_kiwi_tequila(origin: str, destination: str, date_from: str, date_to: str) -> list:
    """Fetch flights from Kiwi.com Tequila API (requires API key)."""
    if not TEQUILA_API_KEY:
        return []
    try:
        resp = httpx.get(
            f"{TEQUILA_BASE}/v2/search",
            headers={"apikey": TEQUILA_API_KEY},
            params={
                "fly_from": origin,
                "fly_to": destination,
                "date_from": date_from,
                "date_to": date_to,
                "curr": "THB",
                "locale": "en",
                "sort": "price",
                "limit": 10,
                "one_for_city": 1,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        flights = []
        for flight in data.get("data", []):
            flights.append({
                "origin": origin,
                "destination": destination,
                "price_thb": flight.get("price", 0),
                "airline": ",".join(set(r.get("airline", "") for r in flight.get("route", []))),
                "departure": datetime.fromtimestamp(flight.get("dTime", 0)).strftime("%Y-%m-%d %H:%M") if flight.get("dTime") else "",
                "return": datetime.fromtimestamp(flight.get("aTime", 0)).strftime("%Y-%m-%d %H:%M") if flight.get("aTime") else "",
                "duration_hours": round(flight.get("fly_duration", 0) / 3600, 1) if flight.get("fly_duration") else 0,
                "stops": flight.get("route", [{}]).__len__() - 1 if flight.get("route") else 0,
                "url": flight.get("deep_link", ""),
                "source": "Kiwi.com",
            })
        return flights
    except Exception as e:
        print(f"  Warning: Tequila API failed for {origin}-{destination}: {e}")
        return []


def fetch_skyscanner_free(origin: str, destination: str) -> list:
    """Fetch flight prices from Skyscanner via free httpx+BS4.
    Falls back to Firecrawl API if Skyscanner fails."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    url = f"https://www.skyscanner.com/transport/flights/{origin.lower()}/{destination.lower()}/"
    try:
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return _firecrawl_flight_search(origin, destination)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Remove noise
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'aside']):
            tag.decompose()
        main = soup.find('main') or soup.find('article') or soup.body
        text = main.get_text(separator=' ', strip=True) if main else resp.text
        results = parse_skyscanner(text, origin, destination)
        if results:
            return results
        return _firecrawl_flight_search(origin, destination)
    except Exception as e:
        err_str = str(e).lower()
        if any(kw in err_str for kw in ['name resolution', 'dns', 'network is unreachable', 'no route']):
            return _firecrawl_flight_search(origin, destination)
        print(f"  Warning: Skyscanner scrape failed for {origin}-{destination}: {e}")
        return _firecrawl_flight_search(origin, destination)


def _firecrawl_scrape_url(url: str) -> str:
    """Scrape a URL via Firecrawl's scrape API (renders JS). Returns markdown text."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key:
        return ""
    try:
        resp = httpx.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"url": url, "formats": ["markdown"]},
            timeout=45,
        )
        if resp.status_code != 200:
            print(f"  Firecrawl scrape returned {resp.status_code}")
            return ""
        data = resp.json()
        md = data.get("data", {}).get("markdown", "")
        if md:
            print(f"  Firecrawl scrape: got {len(md)} chars")
        return md
    except Exception as e:
        print(f"  Firecrawl scrape failed: {e}")
        return ""


def _firecrawl_flight_search(origin: str, destination: str) -> list:
    """Use Firecrawl scrape + search to find flight prices when direct scraping fails."""
    import re
    flights = []

    # Strategy 1: Firecrawl scrape of Skyscanner URL (renders JS)
    skyscanner_url = f"https://www.skyscanner.com/transport/flights/{origin.lower()}/{destination.lower()}/"
    md = _firecrawl_scrape_url(skyscanner_url)
    if md:
        prices = parse_skyscanner(md, origin, destination)
        if prices:
            print(f"  Firecrawl scrape: found price ฿{prices[0]['price_thb']:,.0f} for {origin}-{destination}")
            return prices

    # Strategy 2: Search for flight prices, only keep results with actual prices
    query = f"cheap flights {origin} to {destination} price THB 2026"
    results = _brave_search(query, limit=5)
    if not results:
        results = _firecrawl_search(query, limit=5)
    for r in results:
        desc = r.get("description", "")
        title = r.get("title", "")
        # Search both title and description for prices
        price_matches = re.findall(r'(?:฿|THB\s*|USD\s*\$|\$)([\d,]+)', f"{title} {desc}")
        price = 0
        for pm in price_matches:
            p = int(pm.replace(",", ""))
            if 500 < p < 100000:  # Reasonable flight price range
                price = p
                break
        if price:
            flights.append({
                "origin": origin,
                "destination": destination,
                "price_thb": price,
                "airline": "",
                "departure": "",
                "return": "",
                "duration_hours": 0,
                "stops": 0,
                "url": r.get("url", ""),
                "source": "WebSearch",
            })

    if flights:
        print(f"  Search: {len(flights)} results with prices for {origin}-{destination}")
    else:
        print(f"  No price data available for {origin}-{destination}")
    return flights


def parse_skyscanner(markdown: str, origin: str, destination: str) -> list:
    """Parse Skyscanner markdown for price info."""
    import re
    flights = []
    # Look for price patterns like ฿5,990 or $199 or THB 5,990
    price_matches = re.findall(r'(?:฿|THB\s*|฿)([\d,]+)', markdown)
    if price_matches:
        prices = [int(p.replace(",", "")) for p in price_matches if int(p.replace(",", "")) > 500]
        if prices:
            flights.append({
                "origin": origin,
                "destination": destination,
                "price_thb": min(prices),
                "airline": "",
                "departure": "",
                "return": "",
                "duration_hours": 0,
                "stops": 0,
                "url": f"https://www.skyscanner.com/transport/flights/{origin.lower()}/{destination.lower()}/",
                "source": "Skyscanner",
            })
    return flights


def load_previous_prices() -> dict:
    """Load previous lowest prices by route."""
    history_file = OUTPUT_DIR / "flight_prices_history.csv"
    prices = {}
    if history_file.exists():
        with open(history_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"{row.get('origin', '')}-{row.get('destination', '')}"
                try:
                    prices[key] = float(row.get("price_thb", 0))
                except (ValueError, TypeError):
                    pass
    return prices


def save_prices(flights: list):
    """Save latest price snapshot."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / "flight_prices.csv"
    fieldnames = ["origin", "destination", "price_thb", "airline", "departure", "return",
                  "duration_hours", "stops", "url", "source", "scraped_at"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for flight in flights:
            writer.writerow({**flight, "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    print(f"  Saved {len(flights)} flights to {filepath}")


def append_history(flights: list):
    """Append to history CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / "flight_prices_history.csv"
    fieldnames = ["origin", "destination", "price_thb", "airline", "departure", "return",
                  "duration_hours", "stops", "url", "source", "scraped_at"]
    file_exists = filepath.exists()
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for flight in flights:
            writer.writerow({**flight, "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    print(f"  Appended {len(flights)} rows to {filepath}")


def print_alerts(flights: list, prev_prices: dict, drop_pct: float):
    """Print alerts for price drops."""
    print("\n  Alerts:")
    alerted = False
    for flight in flights:
        key = f"{flight['origin']}-{flight['destination']}"
        if key in prev_prices and prev_prices[key] > 0:
            change = (flight["price_thb"] - prev_prices[key]) / prev_prices[key] * 100
            if change <= -drop_pct:
                print(f"    *** {key}: PRICE DROP {change:+.1f}% (฿{prev_prices[key]:,.0f} → ฿{flight['price_thb']:,.0f}) ***")
                alerted = True
            elif change >= drop_pct:
                print(f"    *** {key}: PRICE INCREASE {change:+.1f}% (฿{prev_prices[key]:,.0f} → ฿{flight['price_thb']:,.0f}) ***")
                alerted = True
    if not alerted:
        print(f"    No significant price changes (alert threshold: {drop_pct}%)")


class FlightPriceScraper:
    """Wrapper class for scheduler compatibility."""
    def __init__(self, routes=None, origin="BKK", days_ahead=30, alert_drop_pct=15.0, **kwargs):
        raw = routes or DEFAULT_ROUTES
        # Normalize: YAML sends list of strings like ["BKK-SIN"], convert to tuples
        if isinstance(raw, list):
            self.routes = []
            for r in raw:
                if isinstance(r, str) and "-" in r:
                    parts = r.split("-")
                    self.routes.append((parts[0], parts[1]))
                elif isinstance(r, (list, tuple)) and len(r) == 2:
                    self.routes.append(tuple(r))
        else:
            self.routes = raw
        self.origin = origin
        self.days_ahead = days_ahead
        self.alert_drop_pct = alert_drop_pct

    async def run(self, **kwargs):
        main(routes=self.routes, origin=self.origin, days_ahead=self.days_ahead, alert_drop_pct=self.alert_drop_pct)
        return [{"source": "flights", "count": len(self.routes)}]


def parse_routes(routes=None, origin="BKK", destinations=None):
    """Normalize --routes / --origin + --destinations into (orig, dest) tuples."""
    if isinstance(routes, str) and routes.strip():
        parsed = []
        for item in routes.split(","):
            parts = [part.strip().upper() for part in item.split("-")]
            if len(parts) == 2 and all(parts):
                parsed.append((parts[0], parts[1]))
        return parsed
    if isinstance(destinations, str) and destinations.strip():
        orig = (origin or "BKK").strip().upper()
        return [(orig, dest.strip().upper()) for dest in destinations.split(",") if dest.strip()]
    return routes if routes else list(DEFAULT_ROUTES)


def main(routes=None, origin="BKK", days_ahead=30, alert_drop_pct=15.0, no_history=False, output_dir=None):
    global OUTPUT_DIR
    if output_dir:
        OUTPUT_DIR = Path(output_dir)
    routes = parse_routes(routes, origin)

    # Build date range
    date_from = datetime.now().strftime("%d/%m/%Y")
    date_to = (datetime.now() + timedelta(days=days_ahead)).strftime("%d/%m/%Y")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Flight Price Scraper")
    print(f"  Routes: {len(routes)} | Days ahead: {days_ahead}")

    all_flights = []

    for orig, dest in routes:
        route_key = f"{orig}-{dest}"
        print(f"\n  {route_key}...", end=" ")

        flights = fetch_kiwi_tequila(orig, dest, date_from, date_to)
        if flights:
            print(f"Kiwi: {len(flights)} flights (cheapest: ฿{min(f['price_thb'] for f in flights):,.0f})")
            cheapest = min(flights, key=lambda x: x["price_thb"])
            all_flights.append(cheapest)
            continue

        flights = fetch_skyscanner_free(orig, dest)
        if flights:
            priced = [f for f in flights if f['price_thb'] < 9999]
            if priced:
                print(f"Skyscanner: ฿{priced[0]['price_thb']:,.0f}")
                all_flights.extend(priced)
            else:
                print("No valid prices")
        else:
            print("No data")

    if not all_flights:
        print("\n  WARNING: No flight data fetched.")
        return

    save_prices(all_flights)
    if not no_history:
        append_history(all_flights)

    prev_prices = load_previous_prices()
    print_alerts(all_flights, prev_prices, alert_drop_pct)

    print(f"\n  Total: {len(all_flights)} routes tracked")
    print("  Done.")


def cli(argv=None):
    parser = argparse.ArgumentParser(description="Track flight prices for a bounded set of routes")
    parser.add_argument("--routes", help="Comma-separated ORIG-DEST pairs, e.g. BKK-SIN,BKK-TYO")
    parser.add_argument("--origin", default="BKK", help="Origin used with --destinations (default: BKK)")
    parser.add_argument("--destinations", help="Comma-separated destinations for --origin")
    parser.add_argument("--days-ahead", type=int, default=30)
    parser.add_argument("--alert-drop-pct", type=float, default=15.0)
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--output-dir", default=None, help=f"Output directory (default: {OUTPUT_DIR})")
    args = parser.parse_args(argv)
    routes = parse_routes(args.routes, args.origin, args.destinations)
    if not routes:
        parser.error("no valid routes; use ORIG-DEST pairs")
    main(
        routes=routes,
        origin=args.origin,
        days_ahead=args.days_ahead,
        alert_drop_pct=args.alert_drop_pct,
        no_history=args.no_history,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    cli()
