# Amazon Seller Domain Enrichment Script

Finds official website domains for Amazon sellers based on their company/brand names + basic data. Uses Google search + Claude AI to identify the correct domain with high accuracy.

## What it does

- Takes a CSV of Amazon sellers (e.g., SmartScout export)
- Searches Google for each seller's website
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

You need two API keys:

- **SerpAPI** (Google search): https://serpapi.com/manage-api-key
  - Free tier: 100 searches/month
  - Paid: $75 for 5,000 searches/month

- **Anthropic** (Claude AI): https://console.anthropic.com/
  - Pay-as-you-go, ~$0.01-0.02 per 5 companies (batched)

### 4. Add your API keys to the script

Open `enrich_sellers.py` and replace the placeholder keys at the top:

```python
SERPAPI_KEY = "YOUR_SERPAPI_KEY_HERE"
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY_HERE"
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

For 100 companies:
- SerpAPI: ~200 searches (out of 5000 in paid plan)
- Claude API: ~$1-2

## Resuming

If the script stops mid-run (rate limit, crash, etc.):
- Progress is saved after each batch
- Just run the same command again
- It will skip rows that already have a domain and continue from where it left off

## Tips

- Test with `--limit 5` first to make sure everything works
- The script processes 5 companies per Claude call (batched for efficiency)
- Each company uses ~2 Google searches
