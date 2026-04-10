import asyncio
import re
import csv
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import pandas as pd
from playwright.async_api import async_playwright

# ============================================================
#  TIMESTAMP — set once at the start of each run
# ============================================================

RUN_TIMESTAMP = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
#  ERG MEDIA  (Playwright / async)
# ============================================================

async def _erg_handle_popup(page):
    selectors = ["button[aria-label='Close']", ".newsletter__close", ".modal__close", ".mfp-close"]
    for selector in selectors:
        try:
            if await page.is_visible(selector, timeout=500):
                await page.click(selector)
        except:
            pass

async def _erg_get_isbn(context, product_url):
    page = await context.new_page()
    isbn = "N/A"
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1.5)
        await _erg_handle_popup(page)
        content = await page.content()
        match = re.search(r"ISBN\s?:?\s?([\d\s-]{10,20})", content)
        if match:
            isbn = match.group(1).replace(" ", "").replace("-", "").strip()[:13]
    except:
        isbn = "Error"
    finally:
        await page.close()
    return isbn

async def run_erg():
    """Scrapes ERGMedia, saves erg_media_prices.csv, returns list of dicts."""
    print("\n" + "="*50)
    print("STARTING: ERG Media")
    print("="*50)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={'width': 1280, 'height': 900})
        page = await context.new_page()

        currencies = ["EUR", "USD", "JPY", "GBP"]
        final_data = {}

        for curr in currencies:
            print(f"\n--- Extrahiere Preise für: {curr} ---")
            await page.goto("https://erg.media/collections/store", wait_until="networkidle")
            await asyncio.sleep(10)
            await _erg_handle_popup(page)

            try:
                await page.wait_for_selector(".nice-select", timeout=5000)
                await page.click(".nice-select")
                await asyncio.sleep(0.5)
                await page.click(f"li.option[data-value='{curr}']")
                await asyncio.sleep(2)
                await _erg_handle_popup(page)
            except Exception:
                print(f"Währung {curr} konnte nicht gewählt werden.")
                continue

            cards = await page.query_selector_all(".product-card")
            for card in cards:
                name_el = await card.query_selector(".product-card__title")
                price_el = await card.query_selector(".product-card__price")
                link_el = await card.query_selector("a.product-card__image")

                if name_el and price_el and link_el:
                    name = (await name_el.inner_text()).strip()
                    price = (await price_el.inner_text()).strip().split('\n')[0]
                    href = await link_el.get_attribute("href")
                    full_link = "https://erg.media" + href

                    if name not in final_data:
                        final_data[name] = {"Link": full_link, "Prices": {}}

                    final_data[name]["Prices"][curr] = price

        print(f"\nStarte Deep-Scrape (ISBN) für {len(final_data)} Produkte...")
        for name, info in final_data.items():
            print(f"Hole ISBN für: {name}...")
            info["ISBN"] = await _erg_get_isbn(context, info["Link"])

        # Save per-website CSV (original format + Scraped At)
        with open('erg_media_prices.csv', mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["Produktname", "ISBN", "EUR", "USD", "JPY", "GBP", "Webseite", "Scraped At"])
            for name, info in final_data.items():
                pr = info["Prices"]
                writer.writerow([
                    name,
                    info["ISBN"],
                    pr.get("EUR", "-"),
                    pr.get("USD", "-"),
                    pr.get("JPY", "-"),
                    pr.get("GBP", "-"),
                    info["Link"],
                    RUN_TIMESTAMP
                ])

        print("\nFertig! Die Daten wurden in 'erg_media_prices.csv' gespeichert.")
        await browser.close()

    # Build normalized rows for total CSV
    currency_to_market = {"EUR": "Italy", "USD": "US", "GBP": "UK", "JPY": "Japan"}
    rows = []
    for name, info in final_data.items():
        for curr, market in currency_to_market.items():
            price = info["Prices"].get(curr, "-")
            rows.append({
                "Source": "ERGMedia",
                "Market": market,
                "Title": name,
                "Price": price,
                "Subtitle/Author": "",
                "ISBN": info["ISBN"],
                "Product-ID": "",
                "Product-URL": info["Link"],
                "Scraped At": RUN_TIMESTAMP,
            })
    return rows


# ============================================================
#  TASCHEN  (Playwright / async)
# ============================================================

async def _taschen_handle_cookies(page):
    try:
        selector = "button:has-text('Accept all cookies')"
        banner_button = page.locator(selector)
        if await banner_button.is_visible(timeout=5000):
            await banner_button.click()
            print("      [OK] Cookies accepted.")
            await asyncio.sleep(1)
    except:
        pass

async def _taschen_set_country(page, country_name):
    try:
        print(f"      [Taschen] change to '{country_name}'...")
        await page.click("header button[aria-label*='Show language and currency switcher']")
        await page.click("button:has-text('Change country')")
        await page.fill("input[placeholder*='Search for country']", country_name)
        await asyncio.sleep(1)
        await page.click(f"ul.language-switcher__country-select button:has-text('{country_name}')")
        await page.wait_for_load_state("networkidle")
        print(f"      [OK] Country selected.")
    except Exception as e:
        print(f"      [Issue] Country selection: {e}")

async def _taschen_scrape_page(page, market_name):
    items = await page.locator("article.product-tile").all()
    page_data = []
    for item in items:
        try:
            link_el = item.locator("a").first
            relative_href = await link_el.get_attribute("href")
            full_url = f"https://www.taschen.com{relative_href}" if relative_href and relative_href.startswith("/") else relative_href

            match = re.search(r'/(\d{5})/', relative_href) if relative_href else None
            product_id = match.group(1) if match else "N/A"

            title = await item.locator(".product-tile__heading").inner_text()
            price_text = await item.locator(".product-tile__price").inner_text()

            page_data.append([
                market_name,
                title.replace("\n", " ").strip(),
                price_text.strip(),
                product_id,
                full_url if full_url else ""
            ])
        except:
            continue
    return page_data

async def _taschen_run_market(market_name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={'width': 1280, 'height': 900})
        page = await context.new_page()

        print(f"\n>>> Start with Market: {market_name}")
        await page.goto("https://www.taschen.com/en/books/all-titles/", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        await _taschen_handle_cookies(page)
        await _taschen_set_country(page, market_name)

        market_books = []
        page_num = 1

        while True:
            print(f"      Scrape Page {page_num} ({market_name})...")
            try:
                await page.wait_for_selector("article.product-tile", timeout=15000)
                page_items = await _taschen_scrape_page(page, market_name)

                if not page_items:
                    break

                market_books.extend(page_items)

                next_button = page.locator("button[aria-label='Nächste Seite'], button[aria-label='Next page']")
                if await next_button.is_visible() and await next_button.is_enabled():
                    await next_button.click()
                    page_num += 1
                    await asyncio.sleep(3)
                    await page.wait_for_load_state("domcontentloaded")
                else:
                    break
            except:
                break

        await browser.close()
        return market_books

async def run_taschen():
    """Scrapes Taschen, saves taschen_preise.csv, returns list of dicts."""
    print("\n" + "="*50)
    print("STARTING: Taschen")
    print("="*50)

    markets = ["United States", "Italy", "Japan", "United Kingdom"]
    all_data = []

    for market in markets:
        market_data = await _taschen_run_market(market)
        all_data.extend(market_data)
        print(f"   -> {len(market_data)} Products for {market} gesammelt.")

    if all_data:
        df = pd.DataFrame(all_data, columns=["Region", "Title", "Price", "Product-ID", "Product-URL"])
        df = df.drop_duplicates(subset=["Region", "Product-ID", "Product-URL"])
        df["Scraped At"] = RUN_TIMESTAMP
        df.to_csv("taschen_preise.csv", index=False, encoding="utf-8-sig")
        print("\nFertig! Datei 'taschen_preise.csv' wurde erstellt.")
    else:
        print("\n[!] Keine Daten gefunden.")

    # Build normalized rows for total CSV
    market_map = {
        "United States": "US",
        "Italy": "Italy",
        "Japan": "Japan",
        "United Kingdom": "UK",
    }
    rows = []
    for row in all_data:
        region_raw, title, price, product_id, url = row
        rows.append({
            "Source": "Taschen",
            "Market": market_map.get(region_raw, region_raw),
            "Title": title,
            "Price": price,
            "Subtitle/Author": "",
            "ISBN": "",
            "Product-ID": product_id,
            "Product-URL": url,
            "Scraped At": RUN_TIMESTAMP,
        })
    return rows


# ============================================================
#  ASSOULINE  (requests / sync)
# ============================================================

def _scrape_assouline(url, region):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    products = []
    page = 1

    while True:
        print(f"Scrape Assouline {region}: Seite {page}...")
        response = requests.get(url, headers=headers, params={"page": page, "country": region})
        soup = BeautifulSoup(response.text, 'html.parser')

        empty_grid = soup.select_one('.product-grid--empty')
        if empty_grid:
            print(f"Keine Produkte mehr für {region} auf Seite {page}.")
            break

        items = soup.select('hh-product-card.product-card')
        if not items:
            print(f"Keine Produkte mehr für {region} auf Seite {page}.")
            break

        for item in items:
            title = item.select_one('.card__title').get_text(strip=True) if item.select_one('.card__title') else "N/A"
            subtitle = item.select_one('.card__collection').get_text(strip=True) if item.select_one('.card__collection') else ""
            price = item.select_one('.price dd').get_text(strip=True) if item.select_one('.price dd') else "N/A"
            product_url = "https://www.assouline.com" + item.select_one('.card__title')['href'] if item.select_one('.card__title') else ""
            product_id = item.get('id', '').replace('product-card-', '')

            products.append([region, title, subtitle, price, product_id, product_url])

        if page > 15:
            break
        page += 1
        time.sleep(1)

    return products

def run_assouline():
    """Scrapes Assouline, saves assouline2_preise.csv, returns list of dicts."""
    print("\n" + "="*50)
    print("STARTING: Assouline")
    print("="*50)

    shops = [
        ("https://eu.assouline.com/collections/books", "IT"),
        ("https://eu.assouline.com/collections/books", "GB"),
        ("https://www.assouline.com/collections/books", "US"),
        ("https://ap.assouline.com/collections/books", "JP"),
    ]
    all_data = []
    for url, region in shops:
        all_data.extend(_scrape_assouline(url, region))

    df = pd.DataFrame(all_data, columns=["Region", "Titel", "Subtitle/Author", "Preis", "Product-ID", "Product-URL"])
    df = df.drop_duplicates(subset=["Region", "Product-ID", "Product-URL"])
    df["Scraped At"] = RUN_TIMESTAMP
    df.to_csv("assouline2_preise.csv", index=False, encoding="utf-8-sig")
    print("Fertig! Datei 'assouline2_preise.csv' wurde erstellt.")

    region_map = {"IT": "Italy", "GB": "UK", "US": "US", "JP": "Japan"}
    rows = []
    for row in all_data:
        region_raw, title, subtitle, price, product_id, url = row
        rows.append({
            "Source": "Assouline",
            "Market": region_map.get(region_raw, region_raw),
            "Title": title,
            "Price": price,
            "Subtitle/Author": subtitle,
            "ISBN": "",
            "Product-ID": product_id,
            "Product-URL": url,
            "Scraped At": RUN_TIMESTAMP,
        })
    return rows


# ============================================================
#  GESTALTEN  (requests / sync)
# ============================================================

def _scrape_gestalten(url, region):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    products = []
    page = 1

    while True:
        print(f"Scrape Gestalten {region}: Seite {page}...")
        response = requests.get(f"{url}?page={page}", headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')

        found_on_page = 0

        if "us.gestalten" in url:
            items = soup.select('product-card')
            for item in items:
                title = item.select_one('.product-title').get_text(strip=True) if item.select_one('.product-title') else "N/A"
                subtitle = item.select_one('.vendor').get_text(strip=True) if item.select_one('.vendor') else ""
                price = item.select_one('.price-list').get_text(strip=True) if item.select_one('.price-list') else "N/A"
                link_tag = item.select_one('a')
                product_url = "https://us.gestalten.com" + link_tag['href'] if link_tag and link_tag.get('href') else ""
                products.append([region, title, subtitle, price, product_url])
                found_on_page += 1
        else:
            items = soup.select('.product-wrap')
            for item in items:
                title = item.select_one('.title').get_text(strip=True) if item.select_one('.title') else "N/A"
                subtitle = item.select_one('.author').get_text(strip=True) if item.select_one('.author') else ""
                price = item.select_one('.money').get_text(strip=True) if item.select_one('.money') else "N/A"
                product_url = "https://www.gestalten.com" + item.select_one('.product_image a[itemprop="url"]')['href'] if item.select_one('.product_image a[itemprop="url"]') else ""
                products.append([region, title, subtitle, price, product_url])
                found_on_page += 1

        if found_on_page == 0 or page > 15:
            break
        page += 1
        time.sleep(1)

    return products

def run_gestalten():
    """Scrapes Gestalten, saves gestalten_preise.csv, returns list of dicts."""
    print("\n" + "="*50)
    print("STARTING: Gestalten")
    print("="*50)

    shops = [
        ("https://gestalten.com/collections/all", "EU"),
        ("https://uk.gestalten.com/collections/all", "UK"),
        ("https://us.gestalten.com/collections/all", "US"),
    ]
    all_data = []
    for url, region in shops:
        all_data.extend(_scrape_gestalten(url, region))

    df = pd.DataFrame(all_data, columns=["Region", "Title", "Subtitle/Author", "Price", "Product-URL"])
    df = df.drop_duplicates(subset=["Region", "Title", "Product-URL"])
    df["Scraped At"] = RUN_TIMESTAMP
    df.to_csv("gestalten_preise.csv", index=False, encoding="utf-8-sig")
    print("Fertig! Datei 'gestalten_preise.csv' wurde erstellt.")

    region_map = {"EU": "Italy", "UK": "UK", "US": "US"}
    rows = []
    for row in all_data:
        region_raw, title, subtitle, price, url = row
        rows.append({
            "Source": "Gestalten",
            "Market": region_map.get(region_raw, region_raw),
            "Title": title,
            "Price": price,
            "Subtitle/Author": subtitle,
            "ISBN": "",
            "Product-ID": "",
            "Product-URL": url,
            "Scraped At": RUN_TIMESTAMP,
        })
    return rows


# ============================================================
#  COMBINE & SAVE TOTAL FILES
# ============================================================

def save_total(erg_rows, taschen_rows, assouline_rows, gestalten_rows):
    columns = ["Source", "Market", "Title", "Price", "Subtitle/Author", "ISBN", "Product-ID", "Product-URL", "Scraped At"]
    all_rows = erg_rows + taschen_rows + assouline_rows + gestalten_rows
    df = pd.DataFrame(all_rows, columns=columns)

    df.to_csv("total_prices.csv", index=False, encoding="utf-8-sig")
    print("\nFertig! Datei 'total_prices.csv' wurde erstellt.")

    df.to_excel("total_prices.xlsx", index=False)
    print("Fertig! Datei 'total_prices.xlsx' wurde erstellt.")


# ============================================================
#  MAIN
# ============================================================

async def main():
    print(f"\nScrape-Run gestartet: {RUN_TIMESTAMP}")

    erg_rows = await run_erg()
    taschen_rows = await run_taschen()
    assouline_rows = run_assouline()
    gestalten_rows = run_gestalten()

    save_total(erg_rows, taschen_rows, assouline_rows, gestalten_rows)

    print("\n" + "="*50)
    print("ALLE SCRAPERS FERTIG")
    print(f"Timestamp: {RUN_TIMESTAMP}")
    print("Erstellte Dateien:")
    print("  - erg_media_prices.csv")
    print("  - taschen_preise.csv")
    print("  - assouline2_preise.csv")
    print("  - gestalten_preise.csv")
    print("  - total_prices.csv")
    print("  - total_prices.xlsx")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
