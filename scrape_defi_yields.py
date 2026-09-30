#!/usr/bin/env python3
"""
Scrape DeFi yields from DeFiLlama API (free, no auth required).
Tracks APY across protocols and chains, alerts on high-yield opportunities.

Outputs:
    - data/book-finance/defi_yields.csv (latest snapshot)
    - data/book-finance/defi_yields_history.csv (appended)
    - Console alerts for high APY or new pools

Usage:
    python3 scrape_defi_yields.py
    python3 scrape_defi_yields.py --min-apy 10
    python3 scrape_defi_yields.py --chains ethereum,arbitrum
    python3 scrape_defi_yields.py --categories lending,staking
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

DEFILLAMA_BASE = "https://yields.llama.fi"

# Stablecoins to watch for high yields
STABLECOINS = ["USDT", "USDC", "DAI", "BUSD", "FRAX", "LUSD"]

DEFAULT_CHAINS = ["Ethereum", "Arbitrum", "Optimism", "Polygon", "Base", "BSC"]
DEFAULT_MIN_APY = 5.0  # Minimum APY to track


def fetch_pools() -> list:
    """Fetch all pools from DeFiLlama yields API."""
    try:
        resp = httpx.get(f"{DEFILLAMA_BASE}/pools", timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except Exception as e:
        print(f"  ERROR: Failed to fetch pools: {e}")
        return []


def filter_pools(pools: list, chains: list, min_apy: float, categories: list = None) -> list:
    """Filter pools by chain, APY, and category."""
    filtered = []
    for pool in pools:
        # Skip if chain not in list
        if chains and pool.get("chain", "") not in chains:
            continue
        # Skip if APY too low
        apy = pool.get("apy", 0) or 0
        if apy < min_apy:
            continue
        # Skip if TVL too low (< $100k)
        tvl = pool.get("tvlUsd", 0) or 0
        if tvl < 100000:
            continue
        # Skip if pool is suspicious (APY > 1000% is likely a bug or rug)
        if apy > 1000:
            continue
        # Category filter
        if categories:
            pool_cat = pool.get("category", "")
            if pool_cat not in categories:
                continue
        filtered.append(pool)
    return filtered


def detect_stablecoin_pools(pools: list) -> list:
    """Find high-yield stablecoin pools."""
    stable_pools = []
    for pool in pools:
        symbol = pool.get("symbol", "").upper()
        for sc in STABLECOINS:
            if sc in symbol:
                apy = pool.get("apy", 0) or 0
                if apy >= 5.0:
                    stable_pools.append(pool)
                    break
    return stable_pools


def detect_opportunities(pools: list, prev_pools: dict) -> list:
    """Detect new high-yield pools or significant APY changes."""
    opportunities = []
    for pool in pools:
        pool_id = pool.get("pool", "")
        apy = pool.get("apy", 0) or 0
        tvl = pool.get("tvlUsd", 0) or 0

        # New pool with high APY
        if pool_id not in prev_pools and apy >= 20 and tvl >= 500000:
            opportunities.append({
                "type": "NEW_HIGH_YIELD",
                "pool": pool,
                "reason": f"New pool with {apy:.1f}% APY, TVL ${tvl:,.0f}",
            })
        # APY spike
        elif pool_id in prev_pools:
            prev_apy = prev_pools[pool_id]
            if prev_apy > 0 and apy > prev_apy * 1.5 and apy >= 15:
                opportunities.append({
                    "type": "APY_SPIKE",
                    "pool": pool,
                    "reason": f"APY jumped from {prev_apy:.1f}% to {apy:.1f}%",
                })
    return opportunities


def load_previous_pools() -> dict:
    """Load previous pool APYs from history."""
    history_file = OUTPUT_DIR / "defi_yields_history.csv"
    pools = {}
    if history_file.exists():
        with open(history_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pool_id = row.get("pool_id", "")
                try:
                    pools[pool_id] = float(row.get("apy", 0))
                except (ValueError, TypeError):
                    pass
    return pools


def save_yields(pools: list):
    """Save latest yield snapshot."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / "defi_yields.csv"
    fieldnames = ["pool_id", "chain", "project", "symbol", "tvl_usd", "apy", "apy_base", "apy_reward",
                  "reward_tokens", "category", "url", "scraped_at"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pool in pools:
            writer.writerow({
                "pool_id": pool.get("pool", ""),
                "chain": pool.get("chain", ""),
                "project": pool.get("project", ""),
                "symbol": pool.get("symbol", "")[:30],
                "tvl_usd": pool.get("tvlUsd", 0),
                "apy": pool.get("apy", 0),
                "apy_base": pool.get("apyBase", 0),
                "apy_reward": pool.get("apyReward", 0),
                "reward_tokens": ",".join(pool.get("rewardTokens", []) or []),
                "category": pool.get("category", ""),
                "url": pool.get("url", ""),
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
    print(f"  Saved {len(pools)} pools to {filepath}")


def append_history(pools: list):
    """Append to history CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / "defi_yields_history.csv"
    fieldnames = ["pool_id", "chain", "project", "symbol", "tvl_usd", "apy", "apy_base", "apy_reward",
                  "category", "scraped_at"]
    file_exists = filepath.exists()
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for pool in pools:
            writer.writerow({
                "pool_id": pool.get("pool", ""),
                "chain": pool.get("chain", ""),
                "project": pool.get("project", ""),
                "symbol": pool.get("symbol", "")[:30],
                "tvl_usd": pool.get("tvlUsd", 0),
                "apy": pool.get("apy", 0),
                "apy_base": pool.get("apyBase", 0),
                "apy_reward": pool.get("apyReward", 0),
                "category": pool.get("category", ""),
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
    print(f"  Appended {len(pools)} rows to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Scrape DeFi yields from DeFiLlama")
    parser.add_argument("--chains", default=",".join(DEFAULT_CHAINS),
                        help="Comma-separated chains")
    parser.add_argument("--min-apy", type=float, default=DEFAULT_MIN_APY,
                        help="Minimum APY to track")
    parser.add_argument("--categories", default="",
                        help="Comma-separated categories (lending,staking,dex,etc)")
    parser.add_argument("--no-history", action="store_true",
                        help="Skip appending to history")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help="Output directory")
    args = parser.parse_args()

    chains = [c.strip() for c in args.chains.split(",") if c.strip()]
    categories = [c.strip() for c in args.categories.split(",") if c.strip()] or None

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DeFi Yield Scraper")
    print(f"  Chains: {chains} | Min APY: {args.min_apy}%")

    # Fetch all pools
    print("  Fetching pools from DeFiLlama...")
    all_pools = fetch_pools()
    print(f"  Total pools: {len(all_pools)}")

    if not all_pools:
        print("  ERROR: No pools fetched.")
        sys.exit(1)

    # Filter
    filtered = filter_pools(all_pools, chains, args.min_apy, categories)
    print(f"  Filtered: {len(filtered)} pools (>{args.min_apy}% APY, >$100k TVL)")

    # Detect stablecoin opportunities
    stable_pools = detect_stablecoin_pools(filtered)
    if stable_pools:
        print(f"\n  *** HIGH-YIELD STABLECOIN POOLS ({len(stable_pools)}) ***")
        # Sort by APY descending
        stable_pools.sort(key=lambda x: x.get("apy", 0), reverse=True)
        for pool in stable_pools[:10]:
            print(f"    {pool.get('project', ''):15s} | {pool.get('symbol', '')[:20]:20s} | "
                  f"{pool.get('chain', ''):10s} | APY: {pool.get('apy', 0):.1f}% | TVL: ${pool.get('tvlUsd', 0):,.0f}")

    # Detect new opportunities
    prev_pools = load_previous_pools()
    opportunities = detect_opportunities(filtered, prev_pools)
    if opportunities:
        print(f"\n  *** YIELD OPPORTUNITIES ({len(opportunities)}) ***")
        for opp in opportunities[:10]:
            pool = opp["pool"]
            print(f"    [{opp['type']}] {pool.get('project', ''):15s} | {pool.get('chain', ''):10s} | "
                  f"APY: {pool.get('apy', 0):.1f}% | {opp['reason']}")

    # Save
    save_yields(filtered)
    if not args.no_history:
        append_history(filtered)

    # Top yields by chain
    print("\n  TOP YIELDS BY CHAIN:")
    by_chain = {}
    for pool in filtered:
        chain = pool.get("chain", "Unknown")
        if chain not in by_chain:
            by_chain[chain] = []
        by_chain[chain].append(pool)

    for chain in chains:
        chain_pools = by_chain.get(chain, [])
        if chain_pools:
            chain_pools.sort(key=lambda x: x.get("apy", 0), reverse=True)
            top = chain_pools[0]
            print(f"    {chain:12s}: {top.get('project', ''):15s} | {top.get('symbol', '')[:20]:20s} | APY: {top.get('apy', 0):.1f}%")

    print(f"\n  Total: {len(filtered)} pools tracked")
    print("  Done.")


class DeFiYieldScraper:
    """Wrapper class for scheduler compatibility."""
    def __init__(self, chains=None, min_apy=5.0, categories=None, **kwargs):
        self.chains = chains or DEFAULT_CHAINS
        self.min_apy = min_apy
        self.categories = categories

    async def run(self, **kwargs):
        print(f"[DeFiYieldScraper] Chains: {self.chains} | Min APY: {self.min_apy}%")
        all_pools = fetch_pools()
        if not all_pools:
            return [{"source": "defi", "count": 0}]
        filtered = filter_pools(all_pools, self.chains, self.min_apy, self.categories)
        save_yields(filtered)
        append_history(filtered)
        return [{"source": "defi_yields", "count": len(filtered)}]


if __name__ == "__main__":
    main()
