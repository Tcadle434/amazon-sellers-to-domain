#!/usr/bin/env python3
"""
Amazon Seller Domain Enrichment Script

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

SERPAPI_KEY = "YOUR_SERPAPI_KEY_HERE"
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"

# Rate limiting
SEARCH_DELAY_SECONDS = 1.0
LLM_DELAY_SECONDS = 0.5

CLAUDE_MODEL = "claude-opus-4-5-20251101"

# ============================================================================
# Blacklists - domains that are NEVER valid matches
# ============================================================================

# Major companies that get false-matched constantly
BLACKLIST_DOMAINS = {
    # Big tech / major sites
    "amazon.com", "walmart.com", "ebay.com", "etsy.com", "alibaba.com",
    "aliexpress.com", "target.com", "costco.com", "bestbuy.com",
    "homedepot.com", "lowes.com", "wayfair.com",

    # Generic placeholder sites
    "about.me", "linktree.com", "linktr.ee", "carrd.co", "bio.link",

    # Huge corporations that aren't Amazon sellers
    "aa.com", "yeti.com", "zones.com", "apple.com", "google.com",
    "microsoft.com", "facebook.com", "meta.com",

    # Business registries / directories
    "dnb.com", "bloomberg.com", "crunchbase.com", "zoominfo.com",
    "linkedin.com", "yellowpages.com", "yelp.com", "bbb.org",

    # News / press release sites
    "abnewswire.com", "prnewswire.com", "businesswire.com", "globenewswire.com",

    # Generic ecommerce platforms (root domains)
    "shopify.com", "bigcommerce.com", "wix.com", "squarespace.com",
    "wordpress.com", "weebly.com",
}

# Patterns that indicate garbage domains
BLACKLIST_PATTERNS = [
    r"\.myshopify\.com$",           # Shopify subdomains
    r"\.wordpress\.com$",            # WordPress subdomains
    r"\.wixsite\.com$",              # Wix subdomains
    r"\.blogspot\.com$",             # Blogspot
    r"\.tumblr\.com$",               # Tumblr
    r"^[a-f0-9]{6,}\.myshopify\.com$",  # Random hex shopify stores
    r"\.godaddysites\.com$",         # GoDaddy sites
]


def is_blacklisted_domain(domain: str) -> bool:
    """Check if a domain is blacklisted."""
    if not domain:
        return True

    domain = domain.lower().strip()

    # Check exact matches
    if domain in BLACKLIST_DOMAINS:
        return True

    # Check patterns
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, domain):
            return True

    return False


# ============================================================================
# Google Search via SerpAPI
# ============================================================================

def google_search(query: str, num_results: int = 10) -> list[dict]:
    """Search Google using SerpAPI."""
    if not SERPAPI_KEY:
        raise ValueError("SERPAPI_KEY environment variable not set")

    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": num_results,
    }

    response = requests.get("https://serpapi.com/search", params=params)
    response.raise_for_status()

    data = response.json()
    return data.get("organic_results", [])


def search_for_domain(seller_name: str, business_name: str, category: str, state: str) -> list[dict]:
    """
    Search for company domain using multiple signals.
    """
    results = []

    # Strategy 1: Business name + state + "official website"
    if business_name:
        query = f'"{business_name}" {state} official website'
        results.extend(google_search(query, 5))
        time.sleep(SEARCH_DELAY_SECONDS)

    # Strategy 2: Seller name + category (if different from business name)
    if seller_name and seller_name.lower() != business_name.lower():
        query = f'"{seller_name}" {category} website'
        results.extend(google_search(query, 5))
        time.sleep(SEARCH_DELAY_SECONDS)

    return results


def search_for_linkedin(seller_name: str, business_name: str) -> list[dict]:
    """Search for LinkedIn company page."""
    results = []

    # Try business name first
    if business_name:
        query = f'"{business_name}" site:linkedin.com/company'
        results.extend(google_search(query, 5))
        time.sleep(SEARCH_DELAY_SECONDS)

    # Try seller name if different
    if seller_name and seller_name.lower() != business_name.lower():
        query = f'"{seller_name}" site:linkedin.com/company'
        results.extend(google_search(query, 5))
        time.sleep(SEARCH_DELAY_SECONDS)

    return results


# ============================================================================
# Domain Validation
# ============================================================================

def extract_domain(url: str) -> str | None:
    """Extract clean domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return None


# ============================================================================
# Claude Analysis
# ============================================================================

def analyze_with_validation(
    client: anthropic.Anthropic,
    seller_name: str,
    business_name: str,
    category: str,
    subcategory: str,
    state: str,
    domain_results: list[dict],
    linkedin_results: list[dict],
) -> dict:
    """
    Use Claude to analyze search results with strict validation.
    """

    # Pre-filter blacklisted domains from results
    filtered_domain_results = []
    for r in domain_results:
        domain = extract_domain(r.get("link", ""))
        if domain and not is_blacklisted_domain(domain):
            r["extracted_domain"] = domain
            filtered_domain_results.append(r)

    domain_results_text = json.dumps(
        [{"title": r.get("title"), "link": r.get("link"), "domain": r.get("extracted_domain"), "snippet": r.get("snippet")}
         for r in filtered_domain_results[:10]],
        indent=2
    )

    linkedin_results_text = json.dumps(
        [{"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet")}
         for r in linkedin_results[:10]],
        indent=2
    )

    prompt = f"""You are helping find the official website domain and LinkedIn page for an Amazon seller.

SELLER INFORMATION:
- Amazon Seller/Store Name: {seller_name}
- Legal Business Name: {business_name}
- Product Category: {category}
- Product Subcategory: {subcategory}
- State: {state}, USA

YOUR TASK: Find their ACTUAL company website and LinkedIn page.

CRITICAL RULES - READ CAREFULLY:
1. The domain MUST belong to this specific company, not a similarly-named larger company
2. If "{business_name}" is a generic name like "AA Group" or "XY Textiles", be VERY skeptical of matching to big companies
3. The website content should relate to their product category ({category} / {subcategory})
4. If you're not confident (>80%) it's the right company, return null - a wrong match is worse than no match
5. Never return marketplace sites (Amazon, eBay, Walmart, Etsy, Alibaba)
6. Never return generic placeholder sites (about.me, linktr.ee, etc.)
7. A small company selling "{subcategory}" probably doesn't own a Fortune 500 domain

SEARCH RESULTS FOR WEBSITE (pre-filtered):
{domain_results_text}

SEARCH RESULTS FOR LINKEDIN:
{linkedin_results_text}

Think step by step:
1. What kind of company is this based on their products?
2. Do any of these domains logically belong to a {category} seller?
3. Is the domain size/type appropriate for the business?

Respond with ONLY valid JSON:
{{
    "domain": "example.com" or null,
    "domain_confidence": "high" | "medium" | "low" | "none",
    "domain_reasoning": "Brief explanation of why this matches or why no match",
    "linkedin_url": "https://www.linkedin.com/company/example" or null,
    "linkedin_confidence": "high" | "medium" | "low" | "none",
    "rejection_reasons": ["List of domains you rejected and why"]
}}"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = response.content[0].text.strip()

    try:
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        result = json.loads(response_text)

        # Additional validation: reject low confidence matches
        if result.get("domain_confidence") == "low":
            result["domain"] = None
            result["domain_reasoning"] = f"Low confidence - rejected. Original reasoning: {result.get('domain_reasoning', '')}"

        return result

    except json.JSONDecodeError:
        return {
            "domain": None,
            "domain_confidence": "none",
            "domain_reasoning": f"Failed to parse response",
            "linkedin_url": None,
            "linkedin_confidence": "none",
            "rejection_reasons": []
        }


# ============================================================================
# Main Processing
# ============================================================================

def process_seller(
    client: anthropic.Anthropic,
    seller_name: str,
    business_name: str,
    category: str,
    subcategory: str,
    state: str,
) -> dict:
    """Process a single seller with enhanced matching."""

    print(f"    Searching for website...")
    domain_results = search_for_domain(seller_name, business_name, category, state)

    print(f"    Searching for LinkedIn...")
    linkedin_results = search_for_linkedin(seller_name, business_name)

    print(f"    Analyzing results...")
    result = analyze_with_validation(
        client, seller_name, business_name, category, subcategory, state,
        domain_results, linkedin_results
    )
    time.sleep(LLM_DELAY_SECONDS)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Enrich Amazon seller data with domains (v2 - improved accuracy)"
    )
    parser.add_argument("input_csv", help="Path to SmartScout CSV export")
    parser.add_argument("-o", "--output", help="Output CSV path")
    parser.add_argument("--limit", type=int, help="Limit rows to process")

    # Column name overrides (defaults match SmartScout export)
    parser.add_argument("--seller-col", default="Seller", help="Seller name column")
    parser.add_argument("--business-col", default="Business Name", help="Business name column")
    parser.add_argument("--category-col", default="Category", help="Category column")
    parser.add_argument("--subcategory-col", default="Primary Subcategory", help="Subcategory column")
    parser.add_argument("--state-col", default="State", help="State column")

    args = parser.parse_args()

    # Paths
    input_path = Path(args.input_csv)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        return 1

    # Output to same file (or custom path if specified)
    output_path = Path(args.output) if args.output else input_path

    # Initialize client
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Read input
    with open(input_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        input_rows = list(reader)
        fieldnames = reader.fieldnames

    # Validate columns exist
    required_cols = [args.seller_col, args.business_col, args.category_col]
    for col in required_cols:
        if col not in fieldnames:
            print(f"ERROR: Column '{col}' not found. Available: {fieldnames}")
            return 1

    # Output columns - just add the domain column
    output_fieldnames = list(fieldnames) + ["domain from custom script (lite)"]

    # Process
    output_rows = []
    count = 0
    stats = {"found": 0, "not_found": 0, "skipped": 0}

    for i, row in enumerate(input_rows):
        seller_name = row.get(args.seller_col, "")
        business_name = row.get(args.business_col, "")

        if not business_name and not seller_name:
            print(f"[{i+1}/{len(input_rows)}] Skipping - no name")
            stats["skipped"] += 1
            output_rows.append(row)
            continue

        # Skip if domain already exists in our column (including NOT FOUND)
        existing_domain = row.get("domain from custom script (lite)", "").strip()
        if existing_domain:
            print(f"[{i+1}/{len(input_rows)}] Skipping (already processed: {existing_domain})")
            stats["skipped"] += 1
            output_rows.append(row)
            continue

        if args.limit and count >= args.limit:
            print(f"Reached limit of {args.limit}")
            # Add remaining unprocessed rows to output
            for remaining_row in input_rows[i:]:
                output_rows.append(remaining_row)
            break

        display_name = business_name or seller_name
        print(f"[{i+1}/{len(input_rows)}] Processing: {display_name}")

        try:
            result = process_seller(
                client,
                seller_name=seller_name,
                business_name=business_name,
                category=row.get(args.category_col, ""),
                subcategory=row.get(args.subcategory_col, ""),
                state=row.get(args.state_col, ""),
            )

            # Add result - just the domain
            domain = result.get("domain")
            if domain:
                row["domain from custom script (lite)"] = domain
                print(f"    ✓ Domain: {domain}")
                stats["found"] += 1
            else:
                row["domain from custom script (lite)"] = "NOT FOUND"
                print(f"    ✗ No domain found")
                stats["not_found"] += 1

        except Exception as e:
            print(f"    ERROR: {e}")
            row["domain from custom script (lite)"] = "NOT FOUND"
            stats["not_found"] += 1

        output_rows.append(row)

        # Write output incrementally
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(output_rows)

        count += 1

    # Final write to ensure all rows are saved
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)

    # Summary
    print(f"\n{'='*50}")
    print(f"COMPLETE: Processed {count} sellers")
    print(f"  Found domains: {stats['found']}")
    print(f"  No match: {stats['not_found']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"Output: {output_path}")

    return 0


if __name__ == "__main__":
    exit(main())
