#!/usr/bin/env python3
"""
Local Facebook group job scraper using requests + BeautifulSoup.

No API limits — scrapes Google search results for FB group posts.
Can run indefinitely without external service dependencies.

Usage:
    python3 scripts/scrape_fb_local.py                    # Dry run
    python3 scripts/scrape_fb_local.py --apply            # Write to pipeline
    python3 scripts/scrape_fb_local.py --pages 5          # Search 5 pages of results
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
# Keep contact data inside this repository's git-ignored data/ directory
# (the old monorepo layout pointed one level above the repository).
DATA_DIR = SCRIPT_DIR / "data"

CONTACT_FILE = DATA_DIR / "contact_emails.json"
TRACKER_FILE = DATA_DIR / "apply_tracker.csv"

# Headers to mimic browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Thai FB job groups to search
FB_GROUPS = [
    ("Jobs for Thai Programmers", "647718825333067"),
    ("JobThai Programmer WFH", "jobthaiwfh"),
    ("Job Thai Developer/Programmer", "581252398692342"),
]

# Email regex
EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Known generic emails to skip
GENERIC_EMAILS = {
    'info@', 'support@', 'hello@', 'contact@', 'careers@',
    'admin@', 'sales@', 'hr@', 'jobs@', 'recruitment@',
}


def mask_email(email: str) -> str:
    """Mask an address for console/cron logs: ``jane.doe@x.com`` -> ``j***@x.com``."""
    local, sep, domain = str(email).partition('@')
    if not sep:
        return '***'
    return f"{local[:1]}***@{domain}"


def search_bing(query: str, max_results: int = 10) -> list:
    """Search Bing and return list of (title, url, snippet) tuples."""
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={max_results}"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [WARN] Request failed: {e}")
        return []
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    results = []
    
    # Find result items
    for result in soup.find_all('li', class_='b_algo'):
        title_el = result.find('h2')
        link_el = result.find('a')
        snippet_el = result.find('p') or result.find('div', class_='b_caption')
        
        if title_el and link_el:
            title = title_el.get_text(strip=True)
            link = link_el.get('href', '')
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''
            
            # Only keep Facebook results
            if 'facebook.com' in link:
                results.append((title, link, snippet))
                
                if len(results) >= max_results:
                    break
    
    return results


def search_duckduckgo(query: str, max_results: int = 10) -> list:
    """Search DuckDuckGo and return list of (title, url, snippet) tuples."""
    # DuckDuckGo HTML endpoint
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [WARN] Request failed: {e}")
        return []
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    results = []
    
    # Find result links and snippets
    for result in soup.find_all('div', class_='result'):
        title_el = result.find('a', class_='result__a')
        snippet_el = result.find('a', class_='result__snippet')
        
        if title_el:
            title = title_el.get_text(strip=True)
            link = title_el.get('href', '')
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''
            
            # Only keep Facebook results
            if 'facebook.com' in link:
                results.append((title, link, snippet))
                
                if len(results) >= max_results:
                    break
    
    return results


def search_google(query: str, page: int = 0) -> list:
    """Search Google and return list of (title, url, snippet) tuples."""
    url = f"https://www.google.com/search?q={quote_plus(query)}&start={page * 10}"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [WARN] Request failed: {e}")
        return []
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    results = []
    
    # Find search result divs
    for g in soup.find_all('div', class_='g'):
        title_el = g.find('h3')
        link_el = g.find('a')
        snippet_el = g.find('div', class_='VwiC3b') or g.find('span', class_='aCOpRe')
        
        if title_el and link_el:
            title = title_el.get_text(strip=True)
            link = link_el.get('href', '')
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''
            
            # Only keep Facebook results
            if 'facebook.com' in link:
                results.append((title, link, snippet))
    
    return results


def extract_emails_from_text(text: str) -> list:
    """Extract email addresses from text, filtering out generic ones."""
    emails = EMAIL_RE.findall(text)
    filtered = []
    for email in emails:
        email_lower = email.lower()
        # Skip generic prefixes
        prefix = email_lower.split('@')[0]
        if any(prefix.startswith(g.rstrip('@')) for g in GENERIC_EMAILS):
            continue
        # Skip common false positives
        if any(x in email_lower for x in ['example.com', 'domain.com', 'email.com', 'sentry.io']):
            continue
        filtered.append(email)
    # Keep first-seen order: ``best = emails[0]`` must not depend on set order.
    return list(dict.fromkeys(filtered))


def extract_company_from_title(title: str) -> str:
    """Extract company name from post title."""
    # Common patterns: "Company is hiring", "Hiring at Company", etc.
    patterns = [
        r'([A-Za-z0-9\s\.\-]+)\s+(?:is hiring|hiring|recruiting)',
        r'(?:hiring|jobs?|positions?)\s+(?:at|for|from)\s+([A-Za-z0-9\s\.\-]+)',
        r'^([A-Za-z0-9\s\.\-]+)\s*[-–—]',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            company = match.group(1).strip()
            # Clean up
            company = re.sub(r'\s+', ' ', company)
            if len(company) > 3 and len(company) < 50:
                return company
    
    return ''


def fetch_fb_post_content(url: str) -> str:
    """Try to fetch FB post content (may be blocked by FB)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Try to find post content
            content_divs = soup.find_all('div', class_=['userContentWrapper', '_5pb8', '_5rgt'])
            if content_divs:
                return ' '.join(div.get_text(strip=True) for div in content_divs)
            # Fallback: get all text
            return soup.get_text(' ', strip=True)[:2000]
    except Exception:
        pass
    return ''


def scrape_fb_groups(max_results_per_query: int = 10) -> dict:
    """Scrape all configured FB groups and return company data."""
    companies = {}
    
    for group_name, group_id in FB_GROUPS:
        print(f"\n{'='*60}")
        print(f"Scraping: {group_name}")
        print(f"{'='*60}")
        
        # Search queries - broader to find more results
        queries = [
            f'site:facebook.com/groups/{group_id} hiring',
            f'site:facebook.com/groups/{group_id} developer',
            f'site:facebook.com/groups/{group_id} programmer',
            f'site:facebook.com/groups/{group_id} jobs',
        ]
        
        for query in queries:
            print(f"  Query: {query[:50]}...")
            results = search_bing(query, max_results=max_results_per_query)
            print(f"    → {len(results)} results")
            
            for title, url, snippet in results:
                # Extract company name
                company = extract_company_from_title(title)
                if not company:
                    continue
                
                # Extract emails from snippet
                emails = extract_emails_from_text(snippet)
                
                # If no email in snippet, try to fetch post content
                if not emails and 'facebook.com' in url:
                    print(f"      Fetching post content for {company}...")
                    content = fetch_fb_post_content(url)
                    if content:
                        emails = extract_emails_from_text(content)
                        if emails:
                            print(f"      Found email: {mask_email(emails[0])}")
                
                if company not in companies:
                    companies[company] = {
                        'name': company,
                        'emails': emails,
                        'source': f'FB {group_name} group',
                        'fb_url': url,
                        'snippet': snippet[:200],
                    }
                elif emails and not companies[company]['emails']:
                    companies[company]['emails'] = emails
            
            # Rate limit to avoid blocking
            time.sleep(3)
    
    return companies


def add_to_pipeline(companies: dict, dry_run: bool = True):
    """Add discovered companies to contact_emails.json and apply_tracker.csv."""
    # Load existing contacts
    if os.path.exists(CONTACT_FILE):
        with open(CONTACT_FILE) as f:
            contacts = json.load(f)
    else:
        contacts = {}
    
    new_count = 0
    updated_count = 0
    
    for company, data in companies.items():
        if company in contacts:
            # Update if we found new emails
            if data['emails'] and not contacts[company].get('emails'):
                contacts[company]['emails'] = data['emails']
                contacts[company]['best'] = data['emails'][0]
                updated_count += 1
                print(f"  Updated: {company} → {mask_email(data['emails'][0])}")
            continue
        
        # New company
        emails = data['emails']
        best = emails[0] if emails else None
        
        contacts[company] = {
            'domain': None,
            'emails': emails,
            'best': best,
            'source': data['source'],
        }
        new_count += 1
        
        email_info = mask_email(best) if best else 'no email'
        print(f"  New: {company} ({email_info})")
    
    print(f"\n{'='*60}")
    print("Summary:")
    print(f"  New contacts: {new_count}")
    print(f"  Updated contacts: {updated_count}")
    print(f"  Total in DB: {len(contacts)}")
    
    if dry_run:
        print("\n[DRY RUN] No changes written. Use --apply to save.")
        return
    
    # Save contacts
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONTACT_FILE, 'w') as f:
        json.dump(contacts, f, indent=2, ensure_ascii=False)
    print(f"Saved to {CONTACT_FILE}")
    
    # TODO: Add to tracker CSV
    print("(Tracker CSV update not yet implemented)")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Local FB group scraper')
    parser.add_argument('--apply', action='store_true', help='Write changes to pipeline')
    parser.add_argument('--results', type=int, default=10, help='Max results per query (default: 10)')
    
    args = parser.parse_args()
    
    print("="*60)
    print("Local Facebook Group Job Scraper (Bing)")
    print("="*60)
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Max results per query: {args.results}")
    
    companies = scrape_fb_groups(max_results_per_query=args.results)
    
    print(f"\n{'='*60}")
    print(f"Discovered {len(companies)} companies")
    print(f"{'='*60}")
    
    for company, data in sorted(companies.items()):
        emails = ', '.join(mask_email(e) for e in data['emails'][:2]) if data['emails'] else 'no email'
        print(f"  {company:40s} | {emails}")
    
    add_to_pipeline(companies, dry_run=not args.apply)


if __name__ == '__main__':
    main()
