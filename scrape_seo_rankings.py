#!/usr/bin/env python3
"""
Check SEO keyword rankings via free Google search + BS4.
Tracks where your domains appear in search results for target keywords.

Outputs:
    - data/book-marketing/seo_rankings.csv (latest snapshot)
    - data/book-marketing/seo_rankings_history.csv (appended)
    - Console alerts for ranking changes

Usage:
    python3 scrape_seo_rankings.py
    python3 scrape_seo_rankings.py --domain bookchaowalit.com
    python3 scrape_seo_rankings.py --keywords "next.js developer" "python AI"
    python3 scrape_seo_rankings.py --alert-improve 5
"""

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

try:
    from dotenv import load_dotenv
    # Load .env from project root (5 levels up from this script)
    _root = Path(__file__).resolve().parent
    load_dotenv(_root / ".env")
except ImportError:
    pass  # dotenv not required, but .env won't be auto-loaded

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

ROOT = Path(__file__).resolve().parent  # repository root
OUTPUT_DIR = ROOT / "data" / "book-marketing"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# Default keywords to track (customize per your sites)
DEFAULT_KEYWORDS = [
    "next.js developer bangkok",
    "python developer thailand",
    "full-stack developer bangkok",
    "AI developer thailand",
    "web scraping service",
    "chatbot developer bangkok",
    "freelance developer thailand",
    "react developer bangkok",
    "data analyst thailand",
    "AI integration service",
]

# Default domains to track
DEFAULT_DOMAINS = [
    "bookchaowalit.com",
    "chaowalit.com",
]


def host_matches(url: str, domain: str) -> bool:
    """True when ``url``'s host is ``domain`` or a subdomain of it.

    A substring test (``domain in url``) also accepted lookalike hosts and
    any URL that merely mentions the domain in its path or query string.
    """
    domain = str(domain).strip().lower().rstrip(".").removeprefix("www.")
    try:
        host = (urlsplit(str(url)).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    # ``--domains www.example.com`` must still match a bare ``example.com`` result.
    host = host.removeprefix("www.")
    return bool(domain) and (host == domain or host.endswith("." + domain))


def _firecrawl_search(query: str, limit: int = 20) -> list:
    """Fallback search via Firecrawl API when Google fails."""
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


def google_search(query: str, limit: int = 20) -> list:
    """Search via Google and return results as list of dicts with url, title, description.
    Falls back to Firecrawl API if Google fails."""
    import re
    results = []
    try:
        google_url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num={limit}&hl=en"
        resp = httpx.get(google_url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return _firecrawl_search(query, limit)
        soup = BeautifulSoup(resp.text, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Google wraps URLs as /url?q=ACTUAL_URL&...
            m = re.search(r'/url\?q=(https?://[^&]+)', href)
            if m:
                url = m.group(1)
            else:
                url = href
            # Skip Google's own links
            if host_matches(url, 'google.com') or host_matches(url, 'youtube.com'):
                continue
            title = a_tag.get_text(strip=True)
            if title and len(title) > 3:
                results.append({
                    "url": url,
                    "title": title[:200],
                    "description": "",
                })
            if len(results) >= limit:
                break
        if not results:
            return _firecrawl_search(query, limit)
    except Exception as e:
        err_str = str(e).lower()
        if any(kw in err_str for kw in ['name resolution', 'dns', 'network is unreachable', 'no route']):
            return _firecrawl_search(query, limit)
        print(f"  Warning: Google search failed for '{query}': {e}")
        return _firecrawl_search(query, limit)
    return results


def check_ranking(keyword: str, target_domains: list, limit: int = 20) -> dict:
    """Check ranking position for a keyword across target domains."""
    results = google_search(keyword, limit=limit)

    rankings = {
        "keyword": keyword,
        "total_results": len(results),
        "found": False,
        "best_rank": None,
        "best_url": None,
        "best_domain": None,
        "best_title": None,
        "all_positions": [],
    }

    for i, result in enumerate(results, 1):
        url = result.get("url", "")
        title = result.get("title", "")

        for domain in target_domains:
            if host_matches(url, domain):
                rankings["found"] = True
                rankings["all_positions"].append({
                    "rank": i,
                    "url": url,
                    "domain": domain,
                    "title": title,
                })

                if rankings["best_rank"] is None or i < rankings["best_rank"]:
                    rankings["best_rank"] = i
                    rankings["best_url"] = url
                    rankings["best_domain"] = domain
                    rankings["best_title"] = title

    return rankings


def load_previous_rankings(history_file: Path) -> dict:
    """Load previous rankings for comparison."""
    previous = {}
    if not history_file.exists():
        return previous

    with open(history_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keyword = row.get("keyword", "")
            rank = row.get("best_rank")
            if keyword and rank and rank != "":
                try:
                    previous[keyword] = int(rank)
                except (ValueError, TypeError):
                    pass

    return previous


def save_rankings(rankings: list, output_dir: Path):
    """Save rankings snapshot."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rankings_file = output_dir / "seo_rankings.csv"
    fieldnames = [
        "scraped_at", "keyword", "found", "best_rank", "best_domain",
        "best_url", "best_title", "total_results"
    ]

    with open(rankings_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rankings:
            writer.writerow({
                "scraped_at": now,
                "keyword": r["keyword"],
                "found": r["found"],
                "best_rank": r["best_rank"] or "",
                "best_domain": r["best_domain"] or "",
                "best_url": r["best_url"] or "",
                "best_title": (r["best_title"] or "")[:100],
                "total_results": r["total_results"],
            })

    print(f"  Saved {len(rankings)} keyword rankings to {rankings_file}")


def append_history(rankings: list, output_dir: Path):
    """Append rankings history."""
    history_file = output_dir / "seo_rankings_history.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = history_file.exists()

    fieldnames = ["date", "keyword", "best_rank", "best_domain", "found"]
    rows = []
    for r in rankings:
        rows.append({
            "date": now,
            "keyword": r["keyword"],
            "best_rank": r["best_rank"] or "",
            "best_domain": r["best_domain"] or "",
            "found": r["found"],
        })

    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    print(f"  Appended {len(rows)} rows to {history_file}")


def print_summary(rankings: list, previous: dict, alert_improve: int = None):
    """Print ranking summary with change detection."""
    found_count = sum(1 for r in rankings if r["found"])
    print(f"\n  Rankings: {found_count}/{len(rankings)} keywords found")

    print("\n  Keyword Rankings:")
    for r in rankings:
        keyword = r["keyword"]
        if r["found"]:
            rank = r["best_rank"]
            prev_rank = previous.get(keyword)
            change = ""
            if prev_rank:
                diff = prev_rank - rank
                if diff > 0:
                    change = f" (+{diff} up)"
                elif diff < 0:
                    change = f" ({diff} down)"
                else:
                    change = " (=)"

            print(f"    #{rank:>3} | {keyword:<40} | {r['best_domain']}{change}")

            if alert_improve and prev_rank and (prev_rank - rank) >= alert_improve:
                print(f"          *** IMPROVED {prev_rank - rank} positions!")
        else:
            print(f"    --- | {keyword:<40} | Not in top 20")


def main():
    parser = argparse.ArgumentParser(description="Check SEO keyword rankings via free Google search")
    parser.add_argument("--keywords", default=None,
                        help="Comma-separated keywords (default: built-in list)")
    parser.add_argument("--domain", default=None,
                        help="Single domain to track (overrides --domains)")
    parser.add_argument("--domains", default=",".join(DEFAULT_DOMAINS),
                        help="Comma-separated domains to track")
    parser.add_argument("--alert-improve", type=int, default=None,
                        help="Alert when ranking improves by N+ positions")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory")
    args = parser.parse_args()

    keywords = args.keywords.split(",") if args.keywords else DEFAULT_KEYWORDS
    keywords = [k.strip() for k in keywords]
    target_domains = [args.domain] if args.domain else [d.strip() for d in args.domains.split(",")]
    output_dir = Path(args.output_dir)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] SEO Ranking Checker")
    print(f"  Keywords: {len(keywords)} | Domains: {target_domains}")

    # Load previous rankings
    history_file = output_dir / "seo_rankings_history.csv"
    previous = load_previous_rankings(history_file)

    # Check each keyword
    rankings = []
    for keyword in keywords:
        print(f"  Checking: {keyword}...")
        try:
            ranking = check_ranking(keyword, target_domains)
            rankings.append(ranking)
        except Exception as e:
            print(f"    Error: {e}")
            rankings.append({
                "keyword": keyword,
                "found": False,
                "best_rank": None,
                "best_domain": None,
                "best_url": None,
                "best_title": None,
                "total_results": 0,
            })

    # Save
    if rankings:
        save_rankings(rankings, output_dir)
        append_history(rankings, output_dir)
        print_summary(rankings, previous, args.alert_improve)

    print("\n  Done.")


class SEORankingScraper:
    """Wrapper class for scheduler compatibility."""
    def __init__(self, keywords=None, domains=None, alert_improve=None, **kwargs):
        self.keywords = keywords or DEFAULT_KEYWORDS
        self.domains = domains or DEFAULT_DOMAINS
        self.alert_improve = alert_improve

    async def run(self, **kwargs):
        print(f"[SEORankingScraper] Keywords: {len(self.keywords)} | Domains: {self.domains}")
        output_dir = OUTPUT_DIR
        history_file = output_dir / "seo_rankings_history.csv"
        previous = load_previous_rankings(history_file)
        rankings = []
        for keyword in self.keywords:
            try:
                ranking = check_ranking(keyword, self.domains)
                rankings.append(ranking)
            except Exception as e:
                print(f"  Error checking {keyword}: {e}")
                rankings.append({"keyword": keyword, "found": False, "best_rank": None,
                                 "best_domain": None, "best_url": None, "best_title": None, "total_results": 0})
        if rankings:
            save_rankings(rankings, output_dir)
            append_history(rankings, output_dir)
            print_summary(rankings, previous, self.alert_improve)
        return [{"source": "seo_rankings", "count": len(rankings)}]


if __name__ == "__main__":
    main()
