# ERG-CPI

# Competitive Pricing Intelligence — Combined Scraper

Scrapes book prices from four publisher websites across four markets (Italy, US, UK, Japan), saves per-source CSVs, and combines everything into a single normalized CSV and Excel file with EUR-converted prices.

---

## Prerequisites

Python 3.9+ and the following packages:

```bash
pip install playwright requests beautifulsoup4 pandas openpyxl
playwright install chromium
```

---

## How to Run

```bash
git clone https://github.com/pasmec/ERG-CPI.git
cd ERG-CPI
python combined_scraper.py
```

The browser window will open visibly for each Playwright-based scraper. Do not close it manually — it closes automatically when each scraper finishes.

---

## Output

Every run creates a **timestamped folder** in the working directory:

```
Working Scripts/
└── 2026-04-10_14-30-00/
    ├── 2026-04-10_14-30-00_erg_media_prices.csv
    ├── 2026-04-10_14-30-00_taschen_preise.csv
    ├── 2026-04-10_14-30-00_assouline2_preise.csv
    ├── 2026-04-10_14-30-00_gestalten_preise.csv
    ├── 2026-04-10_14-30-00_total_prices.csv
    └── 2026-04-10_14-30-00_total_prices.xlsx
```

The timestamp in both the folder name and filenames lets you compare runs over time without overwriting previous data.

---

## Sources & Market Coverage

| Source | Scraping Method | Italy | US | UK | Japan |
|--------|----------------|-------|----|----|-------|
| ERG Media | Playwright (async) | EUR | USD | GBP | JPY |
| Taschen | Playwright (async) | EUR | USD* | GBP | USD* |
| Assouline | requests + BeautifulSoup | EUR (IT) | USD | GBP (GB) | JPY (JP) |
| Gestalten | requests + BeautifulSoup | EUR (EU) | USD | GBP | — |

*Taschen uses USD for both the US and Japan markets. Japan is not available in Gestalten.

---

## Per-Source CSV Columns

Each source saves its own CSV in its original format:

**ERG Media** (`erg_media_prices.csv`): `Produktname, ISBN, EUR, USD, JPY, GBP, Webseite, Scraped At`
All four currency prices are in one row per product (wide format).

**Taschen** (`taschen_preise.csv`): `Region, Title, Price, Product-ID, Product-URL, Scraped At`

**Assouline** (`assouline2_preise.csv`): `Region, Titel, Subtitle/Author, Preis, Product-ID, Product-URL, Scraped At`

**Gestalten** (`gestalten_preise.csv`): `Region, Title, Subtitle/Author, Price, Product-URL, Scraped At`

---

## Total File Columns

`total_prices.csv` and `total_prices.xlsx` stack all sources into a single normalized table:

| Column | Description |
|--------|-------------|
| Source | ERGMedia / Taschen / Assouline / Gestalten |
| Market | Italy / US / UK / Japan |
| Title | Product name |
| Subtitle/Author | Available from Assouline and Gestalten; empty for others |
| ISBN | Available from ERGMedia only; empty for others |
| Product-ID | Available from Taschen and Assouline; empty for others |
| Product-URL | Link to the product page |
| Price EUR | Numeric price in EUR, filled only when the scraped currency is EUR |
| Price USD | Numeric price in USD, filled only when the scraped currency is USD |
| Price GBP | Numeric price in GBP, filled only when the scraped currency is GBP |
| Price JPY | Numeric price in JPY, filled only when the scraped currency is JPY |
| Price EUR (converted) | All prices converted to EUR using that day's ECB exchange rate |
| Scraped At | Timestamp of when the run started (`YYYY-MM-DD HH:MM:SS`) |

Each row has exactly two price columns filled: the scraped currency column and `Price EUR (converted)`.

---

## Design Decisions & Things to Be Aware Of

### Why Playwright for ERG Media and Taschen?
Both sites render prices and handle market/currency switching via JavaScript. Static HTTP requests would return either no prices or wrong prices. Playwright controls a real Chromium browser to interact with dropdowns, country selectors, and cookie banners exactly as a user would.

### ERG Media: one product → four rows in the total file
ERG Media shows all currencies on a single page via a dropdown. The scraper collects all four prices in one pass and then splits each product into four rows (one per market) when building the total file. This is why ERG Media Italy, US, UK, and Japan all link to the same product URL.

### Taschen Japan uses USD
Taschen's Japanese store displays prices in USD, not JPY. The script detects the currency from the price string itself (by reading the `$`, `€`, `£`, `¥` symbol), rather than assuming a fixed currency per market. This means if Taschen ever changes their Japan pricing currency, the script will adapt automatically.

### Gestalten US: "Sale price" strings
The Gestalten US shop (Shopify) includes label text in the price element, resulting in strings like `Sale price$45.00Regular price$60.00`. The `parse_price()` function extracts only the **first** price found (the sale/current price) and ignores the regular/crossed-out price.

### Gestalten EU mapped to Italy
Gestalten does not have a dedicated Italy store — their EU store ships to Italy in EUR. It is mapped to the Italy market in the total file as the closest equivalent.

### ECB Exchange Rates
Exchange rates are fetched once per run from the European Central Bank's free daily XML feed:
`https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`

Rates are given as "units of foreign currency per 1 EUR" (e.g. USD 1.09 = 1 EUR buys 1.09 USD). If the ECB feed is unreachable, the script falls back to hardcoded approximate values and prints a warning. Always check the `[OK] ECB rates:` line in the terminal output to confirm live rates were used.

### Page limit
All scrapers stop after 50 pages per region as a safety limit to prevent infinite loops if a pagination signal is missing. Most publisher catalogues fit within this. If a source grows beyond ~50 pages of products, this limit can be raised in the `while True` loops inside each `_scrape_*` function.

### Headless mode
Browsers open visibly (`headless=False`). This is intentional — it makes it easier to see if a site has changed its layout, shown a CAPTCHA, or blocked the scraper. Do not switch to `headless=True` without testing first, as some sites detect and block headless browsers.

