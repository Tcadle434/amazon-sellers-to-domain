# Amazon Seller Domain Enrichment Script

Finds official website domains for Amazon sellers based on their company/brand names + basic data. Uses Google search + Claude AI to identify the correct domain with high accuracy.

## What it does

- Takes a CSV of Amazon sellers (e.g., SmartScout export)
- Searches Google using two search APIs (SerpAPI + Google Custom Search) for better coverage
- Uses Claude AI to analyze results and pick the correct domain
- Outputs results back to the CSV with a new "domain from custom script" column

## Setup

### 1. Install Python

If you don't have Python installed:

- **Mac**: Download from https://www.python.org/downloads/ or run `brew install python3`
- **Windows**: Download from https://www.python.org/downloads/ (check "Add to PATH" during install)

Verify it's installed:
```bash
python3 --version
```

### 2. Install Python dependencies

```bash
pip3 install anthropic requests
```

### 3. Get API keys

You need these API keys:

#### SerpAPI (Google search)
1. Go to https://serpapi.com/ and create an account
2. Get your API key from https://serpapi.com/manage-api-key
3. Pricing: 100 free searches/month, then $75 for 5,000 searches/month

#### Google Custom Search API (for better coverage)
1. Go to https://console.cloud.google.com/ and create a project (or use existing)
2. Enable the Custom Search API: https://console.cloud.google.com/apis/library/customsearch.googleapis.com
3. Create an API key: https://console.cloud.google.com/apis/credentials → "Create Credentials" → "API Key"
4. Create a Search Engine:
   - Go to https://programmablesearchengine.google.com/
   - Click "Add" to create a new search engine
   - For "Sites to search" select "Search the entire web"
   - Give it a name and click "Create"
   - Copy the "Search engine ID" (this is your `GOOGLE_CSE_CX`)
5. Pricing: 100 free searches/day, then $5 per 1,000 searches (requires billing account)

#### Anthropic (Claude AI)
1. Go to https://console.anthropic.com/ and create an account
2. Add a payment method and get your API key
3. Pricing: Pay-as-you-go, ~$0.01-0.02 per 5 companies (batched)

### 4. Add your API keys to the script

Open `enrich_sellers.py` and replace the placeholder keys at the top:

```python
SERPAPI_KEY = "YOUR_SERPAPI_KEY_HERE"
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"
GOOGLE_CSE_API_KEY = "YOUR_GOOGLE_CSE_API_KEY_HERE"
GOOGLE_CSE_CX = "YOUR_SEARCH_ENGINE_ID_HERE"
```

## Usage

### Basic usage

```bash
python3 enrich_sellers.py your_file.csv
```

This will:
- Process all rows in the CSV
- Add domains to a new column "domain from custom script"
- Save results back to the same file

### Limit rows (for testing)

```bash
python3 enrich_sellers.py your_file.csv --limit 10
```

### Output to different file

```bash
python3 enrich_sellers.py input.csv -o output.csv
```

### Choose search engine

By default, the script uses both SerpAPI and Google Custom Search for better coverage. You can use only one:

```bash
# Use only SerpAPI
python3 enrich_sellers.py your_file.csv --search-engine serp

# Use only Google Custom Search
python3 enrich_sellers.py your_file.csv --search-engine google

# Use both (default)
python3 enrich_sellers.py your_file.csv --search-engine both
```

## CSV Format

The script expects these columns (matches SmartScout export):
- `Seller` - Amazon seller/brand name
- `Business Name` - Legal business name
- `Category` - Product category
- `Primary Subcategory` - Product subcategory
- `State` - Business location

If your columns have different names, use the override flags:
```bash
python3 enrich_sellers.py file.csv --seller-col "Brand" --business-col "Company"
```

## Output

The script adds a column `domain from custom script` with either:
- The found domain (e.g., `comfier.com`)
- `NOT FOUND` if no confident match

## Cost Estimate

For 100 companies (using both search engines):
- SerpAPI: ~200 searches
- Google CSE: ~200 searches (out of 100 free/day)
- Claude API: ~$1-2

For 100 companies (using single search engine):
- SerpAPI or Google CSE: ~200 searches
- Claude API: ~$1-2

## Resuming

If the script stops mid-run (rate limit, crash, etc.):
- Progress is saved after each batch
- Just run the same command again
- It will skip rows that already have a domain and continue from where it left off

## Tips

- Test with `--limit 5` first to make sure everything works
- The script processes 5 companies per Claude call (batched for efficiency)
- Each company uses ~2 searches per engine (~4 total with both engines)
- Use `--search-engine serp` or `--search-engine google` to reduce search costs
