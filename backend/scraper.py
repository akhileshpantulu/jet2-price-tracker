"""
Jet2holidays Price Scraper (GitHub Actions version)
=====================================================
Runs in CI — no terminal needed. Scrapes jet2holidays.com
and writes frontend/public/pricing_data.json for the dashboard.
"""

import json
import re
import os
import sys
import asyncio
from datetime import datetime
from pathlib import Path

AIRPORTS = {
    "LBA": "4", "MAN": "8", "EMA": "3", "BHX": "1",
    "EDI": "9", "GLA": "69", "NCL": "5", "STN": "7",
    "BFS": "63", "BRS": "77", "LGW": "99", "LTN": "127",
    "LPL": "98", "BOH": "118",
}

# ----------------------------------------------------------------
# EDIT THIS — add/remove hotels you want to track
# Find the slug and destination_path from the hotel URL on jet2holidays.com
# e.g. jet2holidays.com/destinations/balearics/majorca/alcudia/sunwing-alcudia-beach
#      → destination_path = "balearics/majorca/alcudia"
#      → slug = "sunwing-alcudia-beach"
# ----------------------------------------------------------------
TRACKED_HOTELS = [
    {
        "name": "Sunwing Alcudia Beach",
        "slug": "alcudia-beach",
        "destination_path": "balearics/majorca/alcudia",
        "destination_label": "Majorca, Spain",
        "stars": 4,
        "rating": 4.3,
        "airports": ["MAN", "LBA"],
        "nights": [7],
    },
    {
        "name": "Hotel Flamingo Oasis",
        "slug": "flamingo-beach-resort",
        "destination_path": "spain/costa-blanca/benidorm",
        "destination_label": "Benidorm, Spain",
        "stars": 4,
        "rating": 4.1,
        "airports": ["MAN"],
        "nights": [7],
    },
    {
        "name": "Zafiro Palace Alcudia",
        "slug": "zafiro-palace-alcudia",
        "destination_path": "balearics/majorca/alcudia",
        "destination_label": "Majorca, Spain",
        "stars": 5,
        "rating": 4.7,
        "airports": ["MAN", "LBA"],
        "nights": [7, 10],
    },
]

OUTPUT_PATH = Path(__file__).parent.parent / "frontend" / "public" / "pricing_data.json"


async def scrape_hotel(page, hotel, airport_code, nights):
    """Scrape a single hotel/airport/duration combination."""
    airport_id = AIRPORTS.get(airport_code, "8")
    url = (
        f"https://www.jet2holidays.com/"
        f"{hotel['destination_path']}/{hotel['slug']}"
        f"?airport={airport_id}&nights={nights}&adults=2&children=0&infants=0"
    )
    results = []
    captured_api = []

    async def on_response(response):
        ct = response.headers.get("content-type", "")
        if "json" in ct:
            lo = response.url.lower()
            if any(k in lo for k in ["search", "price", "avail", "package", "room", "calendar", "holiday"]):
                try:
                    captured_api.append(await response.json())
                except Exception:
                    pass

    page.on("response", on_response)
    print(f"  → {url[:90]}...")

    try:
        await page.goto(url, wait_until="networkidle", timeout=45000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  ✗ Load failed: {e}")
            page.remove_listener("response", on_response)
            return results

    # Cookie banner
    for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept All')", "button:has-text('Accept')"]:
        try:
            btn = page.locator(sel)
            if await btn.count() > 0:
                await btn.first.click(timeout=2000)
                break
        except Exception:
            pass

    await asyncio.sleep(4)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(2)

    # Strategy 1: API interception
    for data in captured_api:
        parsed = extract_prices_recursive(data)
        for p in parsed:
            results.append({
                "hotel_name": hotel["name"],
                "airport": airport_code,
                "nights": nights,
                "departure_date": p.get("date", ""),
                "room_type": p.get("room", "Standard"),
                "board_basis": p.get("board", "Unknown"),
                "price_pp": p["price"],
                "available": True,
                "scraped_at": datetime.now().isoformat(),
            })
        if results:
            print(f"  ✓ API: {len(results)} prices")

    # Strategy 2: DOM scraping
    if not results:
        html = await page.content()
        prices_found = re.findall(r'£\s*([\d,]+(?:\.\d{2})?)', html)
        rooms_found = re.findall(
            r'(Standard|Superior|Family Room|Suite|Sea View|Deluxe|Premium|Classic|Studio|Junior Suite)',
            html, re.I
        )
        boards_found = re.findall(
            r'(Self Catering|Bed (?:&|and) Breakfast|Half Board|Full Board|All Inclusive)', html, re.I
        )
        dates_found = re.findall(
            r'(\d{1,2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s*(\d{4})', html, re.I
        )
        rooms_list = list(dict.fromkeys([r.strip().title() for r in rooms_found])) or ["Standard"]
        board = boards_found[0] if boards_found else "Unknown"

        for i, pm in enumerate(prices_found[:20]):
            try:
                price = float(pm.replace(",", ""))
                if 80 < price < 10000:
                    date_str = ""
                    if i < len(dates_found):
                        d = dates_found[i]
                        date_str = f"{d[2]}-{d[1]}-{d[0]}"
                    results.append({
                        "hotel_name": hotel["name"],
                        "airport": airport_code,
                        "nights": nights,
                        "departure_date": date_str,
                        "room_type": rooms_list[i % len(rooms_list)],
                        "board_basis": board,
                        "price_pp": price,
                        "available": True,
                        "scraped_at": datetime.now().isoformat(),
                    })
            except ValueError:
                pass
        if results:
            print(f"  ✓ DOM: {len(results)} prices")

    if not results:
        print(f"  ✗ No prices found")

    page.remove_listener("response", on_response)
    return results


def extract_prices_recursive(obj, depth=0):
    """Recursively find price entries in nested JSON."""
    if depth > 8 or not obj:
        return []
    found = []
    if isinstance(obj, dict):
        price = None
        for k in ["pricePerPerson", "price", "leadInPrice", "pricePP", "fromPrice"]:
            if k in obj:
                try:
                    price = float(obj[k])
                except (ValueError, TypeError):
                    pass
                if price and price > 50:
                    break
        if price and price > 50:
            date_val = ""
            for k in ["departureDate", "date", "outboundDate"]:
                if k in obj and obj[k]:
                    date_val = str(obj[k])[:10]
                    break
            room = "Standard"
            for k in ["roomType", "roomDescription", "name"]:
                if k in obj and isinstance(obj[k], str) and len(obj[k]) > 2:
                    room = obj[k]
                    break
            board = "Unknown"
            for k in ["boardBasis", "mealPlan", "board"]:
                if k in obj and isinstance(obj[k], str):
                    board = obj[k]
                    break
            found.append({"price": price, "date": date_val, "room": room, "board": board})
        else:
            for v in obj.values():
                found.extend(extract_prices_recursive(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(extract_prices_recursive(item, depth + 1))
    return found


async def main():
    from playwright.async_api import async_playwright

    all_results = []
    print(f"\n{'='*60}")
    print(f"JET2 SCRAPER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Hotels: {len(TRACKED_HOTELS)}")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-GB",
            timezone_id="Europe/London",
        )
        await context.route(re.compile(r"\.(png|jpg|jpeg|gif|svg|woff2?|ttf|eot|ico)$"), lambda r: r.abort())
        page = await context.new_page()

        for hotel in TRACKED_HOTELS:
            for airport in hotel["airports"]:
                for nights in hotel["nights"]:
                    print(f"\n▶ {hotel['name']} | {airport} | {nights}N")
                    try:
                        prices = await scrape_hotel(page, hotel, airport, nights)
                        all_results.extend(prices)
                    except Exception as e:
                        print(f"  ✗ Error: {e}")
                    await asyncio.sleep(3)

        await browser.close()

    # Build output
    hotels = {}
    for r in all_results:
        name = r["hotel_name"]
        if name not in hotels:
            cfg = next((h for h in TRACKED_HOTELS if h["name"] == name), {})
            hotels[name] = {
                "name": name,
                "destination": cfg.get("destination_label", ""),
                "stars": cfg.get("stars"),
                "rating": cfg.get("rating"),
                "prices": [],
            }
        hotels[name]["prices"].append({
            "airport": r["airport"],
            "nights": r["nights"],
            "departure_date": r["departure_date"],
            "room_type": r["room_type"],
            "board_basis": r["board_basis"],
            "price_pp": r["price_pp"],
            "available": r["available"],
        })

    output = {
        "hotels": list(hotels.values()),
        "scraped_at": datetime.now().isoformat(),
        "total_prices": len(all_results),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"DONE — {len(all_results)} prices → {OUTPUT_PATH}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
