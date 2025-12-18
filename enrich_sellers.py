#!/usr/bin/env python3
"""
Amazon Seller Domain Enrichment Script

Features:
- Dual search engine support (SerpAPI + Google Custom Search)
- Batched Claude calls (5 companies per call)
- Automatic resume on interruptions
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import requests

# ============================================================================
# Configuration
# ============================================================================

SERPAPI_KEY = "YOUR_SERPAPI_KEY_HERE"  # Get from https://serpapi.com/manage-api-key
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"  # Get from https://console.anthropic.com/

# Google Custom Search (100 free/day, then $5/1000 searches)
GOOGLE_CSE_API_KEY = "YOUR_GOOGLE_CSE_API_KEY_HERE"  # Get from https://console.cloud.google.com/apis/credentials
GOOGLE_CSE_CX = "YOUR_SEARCH_ENGINE_ID_HERE"  # Get from https://programmablesearchengine.google.com/

SEARCH_DELAY_SECONDS = 1.0
CLAUDE_MODEL = "claude-opus-4-5-20251101"
BATCH_SIZE = 5  # Number of companies to process per Claude call

# ============================================================================
# Blacklists
# ============================================================================

BLACKLIST_DOMAINS = {
    "amazon.com", "walmart.com", "ebay.com", "etsy.com", "alibaba.com",
    "aliexpress.com", "target.com", "costco.com", "bestbuy.com",
    "homedepot.com", "lowes.com", "wayfair.com",
    "about.me", "linktree.com", "linktr.ee", "carrd.co", "bio.link",
    "aa.com", "yeti.com", "zones.com", "apple.com", "google.com",
    "microsoft.com", "facebook.com", "meta.com",
    "dnb.com", "bloomberg.com", "crunchbase.com", "zoominfo.com",
    "linkedin.com", "yellowpages.com", "yelp.com", "bbb.org",
    "abnewswire.com", "prnewswire.com", "businesswire.com", "globenewswire.com",
    "shopify.com", "bigcommerce.com", "wix.com", "squarespace.com",
    "wordpress.com", "weebly.com",
}

BLACKLIST_PATTERNS = [
    r"\.myshopify\.com$",
    r"\.wordpress\.com$",
    r"\.wixsite\.com$",
    r"\.blogspot\.com$",
    r"\.tumblr\.com$",
    r"^[a-f0-9]{6,}\.myshopify\.com$",
    r"\.godaddysites\.com$",
    r"(^|\.)amazon\.com$",      # catches us.amazon.com, amazon.com
    r"(^|\.)amazon\.[a-z]{2,3}$",  # catches amazon.co.uk, amazon.de, etc.
    r"(^|\.)ubuy\.",            # ubuy.co.in, ubuy.com, etc.
    r"(^|\.)archive\.",         # archive.org, archive.is, etc.
    r"(^|\.)alibaba\.com$",     # catches comfier.en.alibaba.com, etc.
    r"(^|\.)aliexpress\.",      # aliexpress subdomains
]


def is_blacklisted_domain(domain: str) -> bool:
    if not domain:
        return True
    domain = domain.lower().strip()
    if domain in BLACKLIST_DOMAINS:
        return True
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, domain):
            return True
    return False


# ============================================================================
# Search Engines
# ============================================================================

def serpapi_search(query: str, num_results: int = 10, max_retries: int = 3) -> list[dict]:
    """Search Google using SerpAPI with retry logic for rate limits."""
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": num_results,
    }

    for attempt in range(max_retries):
        try:
            response = requests.get("https://serpapi.com/search", params=params)

            if response.status_code == 429:
                wait_time = (attempt + 1) * 10  # 10s, 20s, 30s
                print(f"      [SerpAPI] Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            results = response.json().get("organic_results", [])
            # Tag results with source
            for r in results:
                r["_source"] = "serp"
            return results
        except Exception as e:
            print(f"      [SerpAPI] Error: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return []

    print(f"      [SerpAPI] Search failed after {max_retries} retries")
    return []


def google_cse_search(query: str, num_results: int = 10) -> list[dict]:
    """Search using Google Custom Search API (100 free/day)."""
    params = {
        "key": GOOGLE_CSE_API_KEY,
        "cx": GOOGLE_CSE_CX,
        "q": query,
        "num": min(num_results, 10),  # CSE max is 10 per request
    }

    try:
        response = requests.get("https://www.googleapis.com/customsearch/v1", params=params)
        response.raise_for_status()
        data = response.json()

        # Convert to same format as SerpAPI
        results = []
        for item in data.get("items", []):
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "_source": "google_cse",
            })
        return results
    except Exception as e:
        print(f"      [Google CSE] Error: {e}")
        return []


def search_for_company(seller_name: str, business_name: str, category: str, subcategory: str, engine: str = "both") -> list[dict]:
    """
    Search for company using specified engine(s).

    engine: "serp", "google", or "both" (default)
    """
    results = []

    # Build search queries
    queries = []

    # Query 1: Simple seller/brand name (catches brand sites with different domain names)
    if seller_name:
        queries.append(f'"{seller_name}"')

    # Query 2: Seller/brand name + category (broader context)
    if seller_name and category:
        queries.append(f'"{seller_name}" {category}')

    # Query 3: Business name (fallback)
    if business_name and business_name.lower() != (seller_name or "").lower():
        queries.append(f'"{business_name}"')

    # Run searches through selected engine(s)
    for query in queries:
        if engine in ("serp", "both"):
            results.extend(serpapi_search(query, 8))
            time.sleep(SEARCH_DELAY_SECONDS)

        if engine in ("google", "both"):
            results.extend(google_cse_search(query, 8))
            time.sleep(SEARCH_DELAY_SECONDS)

    return results


def extract_domain(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return None


def filter_results(results: list[dict]) -> list[dict]:
    """Pre-filter blacklisted domains and dedupe."""
    seen_domains = set()
    filtered = []
    for r in results:
        domain = extract_domain(r.get("link", ""))
        if domain and not is_blacklisted_domain(domain) and domain not in seen_domains:
            r["extracted_domain"] = domain
            filtered.append(r)
            seen_domains.add(domain)
    return filtered


# ============================================================================
# Batched Claude Analysis
# ============================================================================

def analyze_batch(client: anthropic.Anthropic, batch: list[dict]) -> list[dict]:
    """
    Analyze multiple companies in a single Claude call.

    batch: list of dicts with keys: seller_name, business_name, category, subcategory, state, search_results
    returns: list of dicts with keys: domain (or None)
    """

    # Build the prompt with all companies
    companies_text = ""
    for i, company in enumerate(batch):
        results_text = json.dumps(
            [{"title": r.get("title"), "domain": r.get("extracted_domain"), "snippet": r.get("snippet")}
             for r in company["search_results"][:12]],
            indent=2
        )
        companies_text += f"""
--- COMPANY {i+1} ---
Seller Name: {company['seller_name']}
Business Name: {company['business_name']}
Category: {company['category']}
Subcategory: {company['subcategory']}
State: {company['state']}

Search Results:
{results_text}

"""

    prompt = f"""You are finding official website domains for Amazon sellers. I'll give you {len(batch)} companies with their search results.

RULES:
1. PRIORITIZE domains that match the Seller/Brand Name over the legal Business Name (e.g., seller "Comfier" -> comfier.com)
2. The brand name may appear ON the website even if the domain is different (e.g., "Swanoo Store" brand on thestrollerorganizer.com)
3. Look for the brand name mentioned in page titles or snippets - this often reveals the official site
4. Be skeptical of generic business names matching Fortune 500 domains
5. The website should relate to their product category
6. Never return: marketplace sites (amazon, ebay), placeholder sites (about.me, linktr.ee), news sites
7. When in doubt, prefer returning a likely match over returning null - we want to find domains

{companies_text}

Respond with ONLY a JSON array of {len(batch)} objects, one per company in order:
[
    {{"company": 1, "domain": "example.com" or null}},
    {{"company": 2, "domain": "example2.com" or null}},
    ...
]"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = response.content[0].text.strip()

    try:
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        results = json.loads(response_text)
        return results

    except (json.JSONDecodeError, Exception) as e:
        print(f"      Claude parse error: {e}")
        # Return empty results for all companies in batch
        return [{"domain": None} for _ in batch]


# ============================================================================
# Main Processing
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Enrich Amazon seller data with domains")
    parser.add_argument("input_csv", help="Path to CSV file")
    parser.add_argument("-o", "--output", help="Output CSV path")
    parser.add_argument("--limit", type=int, help="Limit rows to process")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Companies per Claude call")
    parser.add_argument("--search-engine", choices=["serp", "google", "both"], default="both",
                        help="Search engine to use: serp, google, or both (default)")

    parser.add_argument("--seller-col", default="Seller", help="Seller name column")
    parser.add_argument("--business-col", default="Business Name", help="Business name column")
    parser.add_argument("--category-col", default="Category", help="Category column")
    parser.add_argument("--subcategory-col", default="Primary Subcategory", help="Subcategory column")
    parser.add_argument("--state-col", default="State", help="State column")

    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        return 1

    output_path = Path(args.output) if args.output else input_path
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Read input
    with open(input_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        input_rows = list(reader)
        fieldnames = reader.fieldnames

    # Validate columns
    required_cols = [args.seller_col, args.business_col, args.category_col]
    for col in required_cols:
        if col not in fieldnames:
            print(f"ERROR: Column '{col}' not found. Available: {fieldnames}")
            return 1

    output_fieldnames = list(fieldnames)
    if "domain from custom script" not in output_fieldnames:
        output_fieldnames.append("domain from custom script")

    # Collect rows to process
    to_process = []
    output_rows = []
    stats = {"found": 0, "not_found": 0, "skipped": 0}

    for i, row in enumerate(input_rows):
        seller_name = row.get(args.seller_col, "")
        business_name = row.get(args.business_col, "")

        if not business_name and not seller_name:
            print(f"[{i+1}/{len(input_rows)}] Skipping - no name")
            stats["skipped"] += 1
            output_rows.append(row)
            continue

        existing_domain = row.get("domain from custom script", "").strip()
        if existing_domain:
            print(f"[{i+1}/{len(input_rows)}] Skipping (already processed: {existing_domain})")
            stats["skipped"] += 1
            output_rows.append(row)
            continue

        if args.limit and len(to_process) >= args.limit:
            output_rows.append(row)
            continue

        to_process.append({
            "index": i,
            "row": row,
            "seller_name": seller_name,
            "business_name": business_name,
            "category": row.get(args.category_col, ""),
            "subcategory": row.get(args.subcategory_col, ""),
            "state": row.get(args.state_col, ""),
        })

    # Calculate search estimates
    queries_per_company = 2  # seller name, seller + category (roughly)
    serp_searches = len(to_process) * queries_per_company if args.search_engine in ("serp", "both") else 0
    google_searches = len(to_process) * queries_per_company if args.search_engine in ("google", "both") else 0

    print(f"\nProcessing {len(to_process)} companies in batches of {args.batch_size}...")
    print(f"Search engine: {args.search_engine}")
    print(f"Estimated searches: ~{serp_searches + google_searches} (SerpAPI: {serp_searches}, Google CSE: {google_searches})")
    print(f"Estimated Claude calls: {(len(to_process) + args.batch_size - 1) // args.batch_size}\n")

    # Process in batches
    processed_rows = {}

    for batch_start in range(0, len(to_process), args.batch_size):
        batch = to_process[batch_start:batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1
        total_batches = (len(to_process) + args.batch_size - 1) // args.batch_size

        print(f"[Batch {batch_num}/{total_batches}] Processing {len(batch)} companies...")

        # Search for each company in batch
        for company in batch:
            display_name = company['seller_name'] or company['business_name']
            print(f"    Searching: {display_name[:40]}...")
            results = search_for_company(
                company['seller_name'],
                company['business_name'],
                company['category'],
                company['subcategory'],
                engine=args.search_engine
            )
            company['search_results'] = filter_results(results)

            # Debug: show results by source
            serp_count = len([r for r in company['search_results'] if r.get('_source') == 'serp'])
            cse_count = len([r for r in company['search_results'] if r.get('_source') == 'google_cse'])
            print(f"      Found {len(company['search_results'])} results (SerpAPI: {serp_count}, Google CSE: {cse_count})")

        # Analyze batch with Claude
        print(f"    Analyzing batch with Claude...")
        try:
            results = analyze_batch(client, batch)

            for company, result in zip(batch, results):
                domain = result.get("domain")
                row = company["row"]
                display_name = company['seller_name'] or company['business_name']

                if domain:
                    row["domain from custom script"] = domain
                    print(f"    ✓ {display_name[:30]}: {domain}")
                    stats["found"] += 1
                else:
                    row["domain from custom script"] = "NOT FOUND"
                    print(f"    ✗ {display_name[:30]}: NOT FOUND")
                    stats["not_found"] += 1

                processed_rows[company["index"]] = row

        except Exception as e:
            print(f"    ERROR: {e}")
            for company in batch:
                company["row"]["domain from custom script"] = "NOT FOUND"
                processed_rows[company["index"]] = company["row"]
                stats["not_found"] += 1

        # Save progress after each batch
        temp_output = []
        for idx, row in enumerate(input_rows):
            if idx in processed_rows:
                temp_output.append(processed_rows[idx])
            else:
                temp_output.append(row)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(temp_output)
        print(f"    [Saved progress to {output_path}]")

    # Rebuild output_rows in correct order
    final_output = []

    for i, row in enumerate(input_rows):
        if i in processed_rows:
            final_output.append(processed_rows[i])
        else:
            final_output.append(row)

    # Write output
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(final_output)

    print(f"\n{'='*50}")
    print(f"COMPLETE: Processed {len(to_process)} sellers")
    print(f"  Found domains: {stats['found']}")
    print(f"  No match: {stats['not_found']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"Output: {output_path}")

    return 0


if __name__ == "__main__":
    exit(main())
