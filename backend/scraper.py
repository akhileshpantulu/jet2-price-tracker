"""
Jet2holidays Price Scraper v3 — GitHub Actions version
========================================================
Key changes from v2:
- Saves debug screenshots (uploaded as GitHub Actions artifacts)
- Waits for actual price elements instead of relying on networkidle
- Strict validation: only records prices found on the actual page
- Never fabricates or duplicates prices across months/hotels
"""

import json
import re
import os
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

AIRPORTS = {
    "LBA": "4", "MAN": "8", "EMA": "3", "BHX": "1",
    "EDI": "9", "GLA": "69", "NCL": "5", "STN": "7",
    "BFS": "63", "BRS": "77", "LGW": "99", "LTN": "127",
    "LPL": "98", "BOH": "118",
}

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

# ----------------------------------------------------------------
# EDIT THIS — add/remove hotels you want to track
# url_path = everything after jet2holidays.com/ in the hotel URL
# ----------------------------------------------------------------
TRACKED_HOTELS = [
    {
        "name": "Gaia Palace",
        "url_path": "greece/kos/mastichari/gaia-palace",
        "destination_label": "Kos, Greece",
        "stars": 5,
        "rating": 4.5,
        "airports": ["MAN"],
        "nights": [7],
    },
    {
        "name": "Sunwing Alcudia Beach",
        "url_path": "balearics/majorca/alcudia/sunwing-alcudia-beach",
        "destination_label": "Majorca, Spain",
        "stars": 4,
        "rating": 4.3,
        "airports": ["MAN"],
        "nights": [7],
    },
    {
        "name": "Hotel Flamingo Oasis",
        "url_path": "spain/costa-blanca/benidorm/hotel-flamingo-oasis",
        "destination_label": "Benidorm, Spain",
        "stars": 4,
        "rating": 4.1,
        "airports": ["MAN"],
        "nights": [7],
    },
]

OUTPUT_DIR = Path(__file__).parent.parent / "frontend" / "public"
OUTPUT_PATH = OUTPUT_DIR / "pricing_data.json"
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


async def scrape_hotel(page, hotel, airport_code, nights):
    """
    Load the hotel page for each target month and extract ONLY
    prices that actually appear on the page.
    """
    airport_id = AIRPORTS.get(airport_code, "8")
    base_url = f"https://www.jet2holidays.com/{hotel['url_path']}"
    all_month_data = {}
    now = datetime.now()

    for month_offset in range(12):
        target = now + timedelta(days=30 * month_offset + 15)
        month_key = target.strftime("%Y-%m")
        month_label = f"{MONTH_NAMES[target.month]} {target.year}"
        date_param = target.strftime("%d-%m-%Y")

        url = (
            f"{base_url}"
            f"?airport={airport_id}"
            f"&nights={nights}"
            f"&adults=2&children=0&infants=0"
            f"&date={date_param}"
        )

        print(f"    {month_label}: ", end="", flush=True)

        # Collect API responses
        api_prices = []

        async def capture_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                url_lower = response.url.lower()
                keywords = ["price", "avail", "package", "room", "search",
                           "holiday", "calendar", "basket", "quote"]
                if not any(k in url_lower for k in keywords):
                    return
                body = await response.json()
                found = _extract_prices(body)
                if found:
                    api_prices.extend(found)
                    print(f"[API:{len(found)}] ", end="", flush=True)
            except Exception:
                pass

        page.on("response", capture_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"✗ load failed: {e}")
            page.remove_listener("response", capture_response)
            continue

        # Dismiss cookie banner on first load
        if month_offset == 0:
            for sel in ["#onetrust-accept-btn-handler",
                       "button:has-text('Accept All')",
                       "button:has-text('Accept')"]:
                try:
                    btn = page.locator(sel)
                    if await btn.count() > 0:
                        await btn.first.click(timeout=3000)
                        await asyncio.sleep(1)
                        break
                except Exception:
                    pass

        # Wait for price content to appear (try multiple selectors)
        price_appeared = False
        price_selectors = [
            "text=£",
            "[class*='price']",
            "[data-testid*='price']",
            "[class*='Price']",
            "[class*='cost']",
        ]
        for sel in price_selectors:
            try:
                await page.wait_for_selector(sel, timeout=8000, state="visible")
                price_appeared = True
                break
            except Exception:
                continue

        if not price_appeared:
            # Extra wait in case content is still loading
            await asyncio.sleep(5)

        # Scroll to trigger lazy content
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        await asyncio.sleep(2)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 2 / 3)")
        await asyncio.sleep(2)

        # Save screenshot for debugging
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        slug = hotel["url_path"].split("/")[-1]
        ss_path = SCREENSHOT_DIR / f"{slug}_{airport_code}_{month_key}.png"
        try:
            await page.screenshot(path=str(ss_path), full_page=True)
        except Exception:
            pass

        # Now extract prices from DOM
        dom_prices = await _extract_dom_prices(page)

        page.remove_listener("response", capture_response)

        # Combine API + DOM prices, deduplicate
        all_prices = api_prices + dom_prices

        # STRICT: Filter out prices that look like they're from the
        # promotional banner ("SAVE £100pp") or navigation
        valid_prices = []
        seen = set()
        for p in all_prices:
            price = p["price"]
            # Skip common banner/promo values
            if price in (100, 50, 25, 200):
                continue
            # Skip unrealistic prices
            if price < 100 or price > 15000:
                continue
            # Deduplicate
            key = (p.get("room", ""), round(price))
            if key in seen:
                continue
            seen.add(key)
            valid_prices.append(p)

        if valid_prices:
            # Check for "not available" indicators on page
            content = await page.text_content("body") or ""
            no_avail_phrases = [
                "no availability", "no holidays found",
                "currently unavailable", "no results",
                "sorry, there are no", "no packages available"
            ]
            is_unavailable = any(p in content.lower() for p in no_avail_phrases)

            if is_unavailable:
                print(f"— unavailable (page says no availability)")
            else:
                all_month_data[month_key] = {
                    "month_label": month_label,
                    "rooms": {}
                }
                for p in valid_prices:
                    room = p.get("room", "Standard")
                    existing = all_month_data[month_key]["rooms"].get(room)
                    # Keep cheapest per room per month
                    if not existing or p["price"] < existing["price_pp"]:
                        all_month_data[month_key]["rooms"][room] = {
                            "price_pp": round(p["price"]),
                            "board_basis": p.get("board", "Unknown"),
                            "departure_date": p.get("date", ""),
                            "available": True,
                            "airport": airport_code,
                            "nights": nights,
                        }
                print(f"✓ {len(valid_prices)} prices, {len(all_month_data[month_key]['rooms'])} rooms")
        else:
            # Check if genuinely unavailable vs scraper failure
            content = await page.text_content("body") or ""
            if any(p in content.lower() for p in ["no availability", "no holidays", "sorry"]):
                print(f"— not available this month")
            else:
                print(f"— no prices found (check screenshot)")

        await asyncio.sleep(3)  # Respectful delay

    return all_month_data


def _extract_prices(obj, depth=0):
    """Recursively extract prices from API JSON."""
    if depth > 8 or not obj:
        return []
    found = []
    if isinstance(obj, dict):
        price = None
        for k in ["pricePerPerson", "price", "leadInPrice",
                   "pricePP", "fromPrice", "totalPricePerPerson",
                   "adultPrice", "leadPrice"]:
            if k in obj:
                try:
                    price = float(obj[k])
                except (ValueError, TypeError):
                    pass
                if price and price > 50:
                    break

        if price and price > 50:
            date_val = ""
            for k in ["departureDate", "date", "outboundDate",
                       "departDate", "checkInDate"]:
                if k in obj and obj[k]:
                    date_val = str(obj[k])[:10]
                    break
            room = "Standard"
            for k in ["roomType", "roomDescription", "roomName",
                       "name", "description", "type"]:
                if k in obj and isinstance(obj[k], str) and 3 < len(obj[k]) < 80:
                    room = obj[k].strip()
                    break
            board = "Unknown"
            for k in ["boardBasis", "mealPlan", "board",
                       "boardType", "boardDescription"]:
                if k in obj and isinstance(obj[k], str):
                    board = obj[k].strip()
                    break
            found.append({
                "price": price,
                "date": date_val,
                "room": room,
                "board": board,
            })
        else:
            for v in obj.values():
                found.extend(_extract_prices(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_extract_prices(item, depth + 1))
    return found


async def _extract_dom_prices(page):
    """Extract prices from the visible DOM with context."""
    results = []
    try:
        # Strategy 1: Find elements containing £ prices
        price_els = await page.query_selector_all(
            ":is([class*='price'], [class*='Price'], [class*='cost'], "
            "[class*='amount'], [data-testid*='price']):not(nav *):not(header *):not(footer *)"
        )

        for el in price_els:
            try:
                text = await el.inner_text()
                matches = re.findall(r'£\s*([\d,]+(?:\.\d{2})?)', text)
                if not matches:
                    continue

                for m in matches:
                    price = float(m.replace(",", ""))
                    if price < 100 or price > 15000:
                        continue

                    # Get context from parent
                    room = "Standard"
                    board = "Unknown"
                    date_str = ""
                    try:
                        parent = await el.evaluate_handle(
                            """el => {
                                let p = el.parentElement;
                                for (let i = 0; i < 5 && p; i++) {
                                    if (p.className && (
                                        p.className.includes('room') ||
                                        p.className.includes('card') ||
                                        p.className.includes('option') ||
                                        p.className.includes('package') ||
                                        p.className.includes('result')
                                    )) return p;
                                    p = p.parentElement;
                                }
                                return el.parentElement;
                            }"""
                        )
                        if parent:
                            ctx = await parent.inner_text()
                            rm = re.search(
                                r'(Standard|Superior|Family|Suite|Sea View|'
                                r'Deluxe|Premium|Junior Suite|Classic|Studio|'
                                r'Double|Twin|Single|Economy)',
                                ctx, re.I
                            )
                            if rm:
                                room = rm.group(1).strip().title()
                            bm = re.search(
                                r'(Self Catering|B&B|Bed (?:&|and) Breakfast|'
                                r'Half Board|Full Board|All Inclusive)',
                                ctx, re.I
                            )
                            if bm:
                                board = bm.group(1)
                            dm = re.search(
                                r'(\d{1,2})\s*(Jan|Feb|Mar|Apr|May|Jun|'
                                r'Jul|Aug|Sep|Oct|Nov|Dec)\w*\s*(\d{4})',
                                ctx, re.I
                            )
                            if dm:
                                date_str = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
                    except Exception:
                        pass

                    results.append({
                        "price": price,
                        "room": room,
                        "board": board,
                        "date": date_str,
                    })
            except Exception:
                continue

        # Strategy 2: If no elements found, try broader text search
        # but ONLY on the main content area
        if not results:
            main_content = ""
            for sel in ["main", "#main", "[role='main']", ".hotel-content",
                        ".page-content", "[class*='content']"]:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        main_content = await el.inner_text()
                        break
                except Exception:
                    continue

            if main_content:
                price_matches = re.findall(
                    r'£\s*([\d,]+(?:\.\d{2})?)\s*(?:pp|per\s*person)',
                    main_content, re.I
                )
                for m in price_matches:
                    price = float(m.replace(",", ""))
                    if 100 < price < 15000:
                        results.append({
                            "price": price,
                            "room": "Standard",
                            "board": "Unknown",
                            "date": "",
                        })

    except Exception as e:
        print(f"[DOM error: {e}] ", end="")

    return results


async def main():
    from playwright.async_api import async_playwright

    print(f"\n{'='*60}")
    print(f"JET2 SCRAPER v3 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Hotels: {len(TRACKED_HOTELS)}")
    print(f"{'='*60}")

    all_hotels = {}
    total_prices = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-GB",
            timezone_id="Europe/London",
        )
        # Don't block images this time — they might be needed for
        # the page to render correctly
        page = await context.new_page()

        for hotel in TRACKED_HOTELS:
            for airport in hotel["airports"]:
                for nights in hotel["nights"]:
                    print(f"\n▶ {hotel['name']} | {airport} | {nights}N")
                    try:
                        month_data = await scrape_hotel(
                            page, hotel, airport, nights
                        )
                        if month_data:
                            key = hotel["name"]
                            if key not in all_hotels:
                                all_hotels[key] = {
                                    "name": hotel["name"],
                                    "destination": hotel.get("destination_label", ""),
                                    "stars": hotel.get("stars"),
                                    "rating": hotel.get("rating"),
                                    "months": [],
                                    "room_types": set(),
                                }
                            for mk in sorted(month_data.keys()):
                                md = month_data[mk]
                                all_hotels[key]["months"].append({
                                    "month_key": mk,
                                    "month_label": md["month_label"],
                                    "rooms": md["rooms"],
                                })
                                for room_name in md["rooms"]:
                                    all_hotels[key]["room_types"].add(room_name)
                                    total_prices += 1
                    except Exception as e:
                        print(f"  ✗ Error: {e}")
                    await asyncio.sleep(2)

        await browser.close()

    # Build output
    hotel_list = []
    for h in all_hotels.values():
        h["room_types"] = sorted(h["room_types"])
        hotel_list.append(h)

    output = {
        "hotels": hotel_list,
        "scraped_at": datetime.now().isoformat(),
        "total_prices": total_prices,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"RESULTS:")
    for h in hotel_list:
        avail = len(h["months"])
        print(f"  {h['name']}: {avail} months with prices, "
              f"rooms: {', '.join(h['room_types']) or 'none'}")
    print(f"\nTotal: {total_prices} price points across {len(hotel_list)} hotels")
    print(f"Output: {OUTPUT_PATH}")
    if SCREENSHOT_DIR.exists():
        ss_count = len(list(SCREENSHOT_DIR.glob("*.png")))
        print(f"Screenshots: {ss_count} saved in {SCREENSHOT_DIR}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
