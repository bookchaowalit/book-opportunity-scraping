#!/usr/bin/env python3
"""
Scrape AI tools and products from ProductHunt and AI directories.
Detects new AI tools, trending products, and build opportunities.

Outputs:
    - domains/product/rnd/book-ai/data/ai_tools.csv (latest snapshot)
    - domains/product/rnd/book-ai/data/ai_tools_history.csv (appended)
    - Console alerts for new opportunities

Usage:
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_ai_tools.py
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_ai_tools.py --sources producthunt,theresanaiforthat
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_ai_tools.py --categories "chatbot,coding,image"
    python3 domains/product/engineering/book-dev/book-scraping/scripts/scrape_ai_tools.py --min-upvotes 50
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parents[4]
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
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4", "-q"])
    from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "domains" / "book-ai" / "data"

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}

# URLs that indicate garbage/CAPTCHA/consent pages
_GARBAGE_URL_PATTERNS = [
    'google.com', 'youtube.com', 'consent.google', 'policies.google',
    '/httpservice/retry/', '/search?q=', 'accounts.google',
    'duckduckgo.com', 'wikipedia.org',
]

# Opportunity keywords — tools matching these are flagged as build opportunities
OPPORTUNITY_KEYWORDS = [
    "api", "sdk", "saas", "automation", "agent", "workflow",
    "scraping", "monitoring", "analytics", "dashboard",
    "chatbot", "code", "developer", "integration", "plugin",
]

DEFAULT_CATEGORIES = ["ai", "developer-tools", "productivity", "automation"]


def _is_valid_url(url: str) -> bool:
    """Reject garbage/CAPTCHA/consent/internal URLs."""
    if not url or url.startswith('/'):
        return False
    return not any(pat in url for pat in _GARBAGE_URL_PATTERNS)


def _clean_search_name(raw_name: str, url: str = "") -> str:
    """Clean breadcrumb garbage from search result titles.
    
    Examples of garbage: 'Product Huntproducthunt.com› home › deals › toolname'
    or 'Site | Category › Tool Name - Description'
    """
    import re
    if not raw_name:
        return ""
    # If name contains breadcrumb separators, extract the meaningful part
    # Common patterns: › » | — → ←
    if any(sep in raw_name for sep in ['›', '»', '→', '←']):
        # Take the last segment after the last breadcrumb separator
        for sep in ['›', '»', '→', '←']:
            if sep in raw_name:
                parts = raw_name.split(sep)
                raw_name = parts[-1].strip()
                break
    # Remove leading/trailing domain-like text (e.g. 'producthunt.com - ')
    raw_name = re.sub(r'^[a-z0-9.-]+\.com\s*[-–—|]\s*', '', raw_name, flags=re.IGNORECASE)
    # Clean up
    name = raw_name.strip()
    # If still too long or looks like garbage, try URL slug
    if (len(name) > 60 or not name) and url:
        # Extract slug from URL as fallback
        slug = url.rstrip('/').split('/')[-1]
        # Convert slug to title case: 'ai-chatbot-tool' -> 'AI Chatbot Tool'
        if slug and not slug.startswith('?') and not slug.startswith('#'):
            name = slug.replace('-', ' ').replace('_', ' ').title()
            # Restore common acronyms
            for acr in ['AI', 'API', 'SDK', 'URL', 'SEO', 'UI', 'UX']:
                name = re.sub(rf'\b{acr.title()}\b', acr, name, flags=re.IGNORECASE)
    return name[:80] if name else ""


def _brave_search(query: str, limit: int = 10) -> list:
    """Search via Brave Search (no API key needed, works from VPS IPs).
    Falls back to Bing if Brave is rate-limited."""
    import urllib.parse
    import time
    try:
        url = f"https://search.brave.com/search?q={query.replace(' ', '+')}"
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}, timeout=15, follow_redirects=True)
        if resp.status_code == 429:
            # Rate limited, try Bing
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
            if title and href and href.startswith('http') and _is_valid_url(href):
                results.append({"name": title[:100], "url": href, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Brave search: {len(results)} results for '{query[:50]}'")
            return results
        # If no results, try Bing
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
    except:
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
            if title and href and href.startswith('http') and _is_valid_url(href):
                results.append({"name": title[:100], "url": href, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Bing search: {len(results)} results for '{query[:50]}'")
        return results
    except Exception as e:
        print(f"  Bing search failed: {e}")
        return []


def fetch_producthunt_free() -> list:
    """Fetch today's ProductHunt launches via free httpx+BS4.
    Falls back to Brave search, then Firecrawl API if ProductHunt fails."""
    import re
    try:
        resp = httpx.get(
            "https://www.producthunt.com/topics/artificial-intelligence",
            headers=HEADERS, timeout=15, follow_redirects=True,
        )
        if resp.status_code != 200:
            return _brave_producthunt()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'aside']):
            tag.decompose()
        main = soup.find('main') or soup.find('article') or soup.body
        text = main.get_text(separator='\n', strip=True) if main else resp.text
        results = parse_producthunt(text)
        if results:
            return results
        return _brave_producthunt()
    except Exception as e:
        print(f"  Warning: ProductHunt scrape failed: {e}")
        return _brave_producthunt()


def parse_producthunt(markdown: str) -> list:
    """Parse ProductHunt markdown into product listings.
    
    Handles two URL patterns:
      - /posts/slug  (daily launches)
      - /products/slug  (product pages on topic/category pages)
    Product link text may contain \\\\n or \\\\ to separate name from description.
    """
    import re
    products = []
    # Match both /posts/ and /products/ URLs; link text may span multiple lines
    # Use re.DOTALL-aware approach: join short lines first
    lines = markdown.split("\n")
    # Rejoin lines that are continuations (e.g. "[Name\\\\\nDesc](url)")
    joined = []
    buf = ""
    for line in lines:
        # If buffer has an unclosed '[', keep accumulating
        if buf:
            buf += "\n" + line
            if ")" in line:
                joined.append(buf)
                buf = ""
        elif line.strip().startswith("[") and ")" not in line:
            buf = line
        else:
            joined.append(line)
    if buf:
        joined.append(buf)

    for raw_line in joined:
        raw_line = raw_line.strip()
        # Match [text](url) where url is producthunt.com/posts/ or /products/
        match = re.match(
            r'\[([^\]]+)\]\((https://www\.producthunt\.com/(?:posts|products)/[^\)]+)\)',
            raw_line,
        )
        if match:
            raw_name = match.group(1)
            url = match.group(2)
            # Split on \\\\ or \\\\n to get name + description
            parts = re.split(r'\\+n?\\*', raw_name)
            name = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            # Skip non-product links (e.g. category pages, reviews)
            if not name or len(name) > 100:
                continue
            # Look for rating / upvotes in surrounding text
            upvotes = ""
            rating_match = re.search(r'(\d+\.?\d*)\s*\(', raw_line)
            if rating_match:
                upvotes = rating_match.group(1)
            products.append({
                "name": name,
                "description": desc,
                "url": url,
                "source": "ProductHunt",
                "upvotes": upvotes,
                "category": "",
                "pricing": "",
                "tags": "",
            })
    return products


def fetch_theresanaiforthat() -> list:
    """Fetch AI tools from There's An AI For That via free httpx+BS4.
    Falls back to Brave search, then Firecrawl API if TAAFT fails."""
    import re
    try:
        resp = httpx.get(
            "https://theresanaiforthat.com/most-saved/",
            headers=HEADERS, timeout=15, follow_redirects=True,
        )
        if resp.status_code != 200:
            return _brave_taft()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'aside']):
            tag.decompose()
        main = soup.find('main') or soup.find('article') or soup.body
        text = main.get_text(separator='\n', strip=True) if main else resp.text
        results = parse_taft(text)
        if results:
            return results
        return _brave_taft()
    except Exception as e:
        print(f"  Warning: TAAFT scrape failed: {e}")
        return _brave_taft()


def parse_taft(markdown: str) -> list:
    """Parse TAAFT markdown into tool listings."""
    import re
    tools = []
    lines = markdown.split("\n")
    for line in lines:
        line = line.strip()
        # Look for tool links
        match = re.match(r'\[([^\]]+)\]\((https://theresanaiforthat\.com/ai/[^\)]+)\)', line)
        if match:
            name = match.group(1)
            url = match.group(2)
            tools.append({
                "name": name,
                "description": "",
                "url": url,
                "source": "TheresAnAIForThat",
                "upvotes": "",
                "category": "",
                "pricing": "",
                "tags": "",
            })
    return tools


def _firecrawl_search(query: str, limit: int = 10) -> list:
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
                results.append({"name": title[:100], "url": url, "description": desc})
            if len(results) >= limit:
                break
        if results:
            print(f"  Firecrawl fallback: {len(results)} results for '{query[:50]}'")
        return results
    except Exception as e:
        print(f"  Firecrawl fallback failed: {e}")
        return []


def _brave_producthunt() -> list:
    """Fetch AI tools from ProductHunt via Brave search."""
    results = _brave_search('"producthunt.com" AI tools new 2026', limit=15)
    if not results:
        results = _firecrawl_producthunt()
    tools = []
    for r in results:
        url = r.get("url", "")
        if "producthunt.com" in url and _is_valid_url(url):
            # Extract clean name from URL slug (most reliable)
            name = _name_from_ph_url(url)
            if not name:
                name = _clean_search_name(r.get("name", ""), url)
            if not name:
                continue
            tools.append({
                "name": name,
                "description": r.get("description", ""),
                "url": url,
                "source": "BraveProductHunt",
                "upvotes": "",
                "category": "",
                "pricing": "",
                "tags": "",
            })
    if tools:
        print(f"  Brave ProductHunt: {len(tools)} tools")
    return tools


def _name_from_ph_url(url: str) -> str:
    """Extract tool name from a ProductHunt URL like /posts/slug or /products/slug."""
    import re
    m = re.search(r'producthunt\.com/(?:posts|products)/([a-z0-9][a-z0-9-]+)', url)
    if m:
        slug = m.group(1)
        # Remove trailing numbers/dates (e.g. 'tool-name-12345')
        slug = re.sub(r'-\d+$', '', slug)
        name = slug.replace('-', ' ').title()
        for acr in ['AI', 'API', 'SDK', 'URL', 'SEO', 'UI', 'UX']:
            name = re.sub(rf'\b{acr.title()}\b', acr, name, flags=re.IGNORECASE)
        return name
    return ""


def _brave_taft() -> list:
    """Fetch AI tools from There's An AI For That via Brave search."""
    results = _brave_search('"theresanaiforthat.com" popular AI tools 2026', limit=15)
    if not results:
        results = _firecrawl_taft()
    tools = []
    for r in results:
        url = r.get("url", "")
        if "theresanaiforthat.com" in url and _is_valid_url(url):
            # Extract clean name from URL slug
            name = _name_from_taft_url(url)
            if not name:
                name = _clean_search_name(r.get("name", ""), url)
            if not name:
                continue
            tools.append({
                "name": name,
                "description": r.get("description", ""),
                "url": url,
                "source": "BraveTAAFT",
                "upvotes": "",
                "category": "",
                "pricing": "",
                "tags": "",
            })
    if tools:
        print(f"  Brave TAAFT: {len(tools)} tools")
    return tools


def _name_from_taft_url(url: str) -> str:
    """Extract tool name from TAAFT URL like /ai/slug/."""
    import re
    m = re.search(r'theresanaiforthat\.com/ai/([a-z0-9][a-z0-9-]+)', url)
    if m:
        slug = m.group(1)
        name = slug.replace('-', ' ').title()
        for acr in ['AI', 'API', 'SDK', 'URL', 'SEO', 'UI', 'UX']:
            name = re.sub(rf'\b{acr.title()}\b', acr, name, flags=re.IGNORECASE)
        return name
    return ""


def _firecrawl_producthunt() -> list:
    """Fetch AI tools from ProductHunt via Firecrawl search."""
    results = _firecrawl_search("site:producthunt.com AI tools 2026", limit=15)
    tools = []
    for r in results:
        url = r.get("url", "")
        if ("producthunt.com/posts/" in url or "producthunt.com/products/" in url) and _is_valid_url(url):
            name = _name_from_ph_url(url) or _clean_search_name(r.get("name", ""), url)
            if not name:
                continue
            tools.append({
                "name": name,
                "description": r.get("description", ""),
                "url": url,
                "source": "FirecrawlProductHunt",
                "upvotes": "",
                "category": "",
                "pricing": "",
                "tags": "",
            })
    if tools:
        print(f"  Firecrawl ProductHunt: {len(tools)} tools")
    return tools


def _firecrawl_taft() -> list:
    """Fetch AI tools from There's An AI For That via Firecrawl search."""
    results = _firecrawl_search("site:theresanaiforthat.com AI tools most saved 2026", limit=15)
    tools = []
    for r in results:
        url = r.get("url", "")
        if "theresanaiforthat.com/ai/" in url and _is_valid_url(url):
            name = _name_from_taft_url(url) or _clean_search_name(r.get("name", ""), url)
            if not name:
                continue
            tools.append({
                "name": name,
                "description": r.get("description", ""),
                "url": url,
                "source": "FirecrawlTAAFT",
                "upvotes": "",
                "category": "",
                "pricing": "",
                "tags": "",
            })
    if tools:
        print(f"  Firecrawl TAAFT: {len(tools)} tools")
    return tools


def fetch_ai_tool_directories() -> list:
    """Fetch from AI tool directories via Brave search.
    Falls back to Firecrawl API if Brave fails."""
    import re
    tools = []
    categories = ["chatbot", "code-generation", "image-generation", "writing"]
    for cat in categories:
        cat_tools = []
        # Try Brave first (reliable, no API key)
        cat_tools_raw = _brave_search(f"top {cat} AI tools list review", limit=10)
        if not cat_tools_raw:
            cat_tools_raw = _firecrawl_search(f"top {cat} AI tools list review", limit=10)
            source_tag = "FirecrawlSearch"
        else:
            source_tag = "BraveSearch"
        for r in cat_tools_raw:
            url = r.get("url", "")
            if _is_valid_url(url):
                name = _clean_search_name(r.get("name", ""), url)
                if not name:
                    continue
                cat_tools.append({
                    "name": name,
                    "description": r.get("description", ""),
                    "url": url,
                    "source": source_tag,
                    "upvotes": "",
                    "category": cat,
                    "pricing": "",
                    "tags": cat,
                })
        tools.extend(cat_tools)
    return tools


def detect_opportunities(tools: list) -> list:
    """Detect tools that match build opportunity keywords."""
    opportunities = []
    for tool in tools:
        text = f"{tool['name']} {tool['description']} {tool.get('tags', '')}".lower()
        matched = [kw for kw in OPPORTUNITY_KEYWORDS if kw in text]
        if matched:
            tool["opportunity_tags"] = ",".join(matched)
            opportunities.append(tool)
    return opportunities


def load_previous_urls() -> set:
    """Load previously seen tool URLs."""
    history_file = OUTPUT_DIR / "ai_tools_history.csv"
    urls = set()
    if history_file.exists():
        with open(history_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("url"):
                    urls.add(row["url"])
    return urls


def save_tools(tools: list):
    """Save latest tool snapshot."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / "ai_tools.csv"
    fieldnames = ["name", "description", "url", "source", "upvotes", "category", "pricing", "tags", "opportunity_tags", "scraped_at"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for tool in tools:
            row = {**tool, "opportunity_tags": tool.get("opportunity_tags", ""), "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            writer.writerow(row)
    print(f"  Saved {len(tools)} tools to {filepath}")


def append_history(tools: list):
    """Append to history CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / "ai_tools_history.csv"
    fieldnames = ["name", "description", "url", "source", "upvotes", "category", "pricing", "tags", "opportunity_tags", "scraped_at"]
    file_exists = filepath.exists()
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for tool in tools:
            row = {**tool, "opportunity_tags": tool.get("opportunity_tags", ""), "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            writer.writerow(row)
    print(f"  Appended {len(tools)} rows to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Scrape AI tools and detect opportunities")
    parser.add_argument("--sources", default="producthunt,taaft,search",
                        help="Sources: producthunt, taft, search")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES),
                        help="Comma-separated categories")
    parser.add_argument("--min-upvotes", type=int, default=0,
                        help="Minimum upvotes filter")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",")]

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] AI Tool Scraper")
    print(f"  Sources: {sources}")

    all_tools = []
    seen_urls = set()

    for source in sources:
        if source == "producthunt":
            print("\n  Fetching ProductHunt...")
            tools = fetch_producthunt_free()
            print(f"    Found {len(tools)} products")
            all_tools.extend(tools)
        elif source == "taaft":
            print("\n  Fetching There's An AI For That...")
            tools = fetch_theresanaiforthat()
            print(f"    Found {len(tools)} tools")
            all_tools.extend(tools)
        elif source == "search":
            print("\n  Fetching AI directories...")
            tools = fetch_ai_tool_directories()
            print(f"    Found {len(tools)} tools")
            all_tools.extend(tools)

    # Deduplicate
    unique_tools = []
    for tool in all_tools:
        if tool["url"] and tool["url"] not in seen_urls:
            seen_urls.add(tool["url"])
            unique_tools.append(tool)
        elif not tool["url"]:
            unique_tools.append(tool)

    # Filter by upvotes
    if args.min_upvotes > 0:
        unique_tools = [t for t in unique_tools
                        if (t.get("upvotes") or "0").isdigit() and int(t.get("upvotes", 0)) >= args.min_upvotes]

    # Detect opportunities
    opportunities = detect_opportunities(unique_tools)

    save_tools(unique_tools)
    append_history(unique_tools)

    # New tools detection
    previous_urls = load_previous_urls()
    new_tools = [t for t in unique_tools if t["url"] not in previous_urls]

    if new_tools:
        print(f"\n  *** {len(new_tools)} NEW AI TOOLS detected ***")
        for tool in new_tools[:10]:
            print(f"    {tool['name'][:40]:40s} | {tool['source']:15s} | {tool['url'][:50]}")

    if opportunities:
        print(f"\n  OPPORTUNITIES ({len(opportunities)}):")
        for tool in opportunities[:10]:
            print(f"    {tool['name'][:35]:35s} | {tool.get('opportunity_tags', ''):20s} | {tool['url'][:40]}")

    print(f"\n  Total: {len(unique_tools)} tools, {len(opportunities)} opportunities")
    print("  Done.")


class AIToolScraper:
    """Wrapper class for scheduler compatibility."""
    def __init__(self, sources=None, categories=None, **kwargs):
        self.sources = sources or ['producthunt', 'taaft', 'search']
        self.categories = categories or DEFAULT_CATEGORIES

    async def run(self, **kwargs):
        print(f"[AIToolScraper] Sources: {self.sources}")
        all_tools = []
        seen_urls = set()
        for source in self.sources:
            if source == 'producthunt':
                tools = fetch_producthunt_free()
                all_tools.extend(tools)
            elif source == 'taaft':
                tools = fetch_theresanaiforthat()
                all_tools.extend(tools)
            elif source == 'search':
                tools = fetch_ai_tool_directories()
                all_tools.extend(tools)
        # Deduplicate
        unique_tools = []
        for tool in all_tools:
            if tool['url'] and tool['url'] not in seen_urls:
                seen_urls.add(tool['url'])
                unique_tools.append(tool)
            elif not tool['url']:
                unique_tools.append(tool)
        opportunities = detect_opportunities(unique_tools)
        save_tools(unique_tools)
        append_history(unique_tools)
        return [{"source": "ai_tools", "count": len(unique_tools), "opportunities": len(opportunities)}]


if __name__ == "__main__":
    main()
