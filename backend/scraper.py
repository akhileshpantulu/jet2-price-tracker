"""
Jet2holidays Price Scraper v4
==============================
Now using the CORRECT Jet2 URL format discovered from real site URLs:

  jet2holidays.com/beach/greece/kos/mastichari/gaia-palace
    ?duration=7
    &occupancy=r2c
    &airport=3
    &date=02-05-2026

Outputs: frontend/public/pricing_data.json
"""

import json
import re
import os
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# Jet2 airport IDs — these are Jet2's internal numeric IDs, NOT IATA codes
# Determined by inspecting real Jet2 URLs
AIRPORTS = {
    "STN": 99,   # London Stansted
    "LGW": 7,  # London Gatwick
    "LTN": 127,  # London Luton
}

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Nov", 11: "Nov", 12: "Dec",
}

# ----------------------------------------------------------------
# EDIT THIS — add/remove hotels you want to track
#
# To find the url_path for any hotel:
#   1. Go to jet2holidays.com
#   2. Search for the hotel and click through to its page
#   3. Copy everything after "jet2holidays.com/" from the URL
#      e.g. "beach/greece/kos/mastichari/gaia-palace"
#
# airport_ids: use the numbers from the AIRPORTS dict above
# ----------------------------------------------------------------
TRACKED_HOTELS = [
    {
        "name": "Gaia Palace",
        "url_path": "beach/greece/kos/mastichari/gaia-palace",
        "destination_label": "Kos, Greece",
        "stars": 5,
        "rating": 4.5,
        "airport_ids": [3],       # Manchester
        "durations": [7],
    },
    {
        "name": "Sunwing Alcudia Beach",
        "url_path": "beach/balearics/majorca/alcudia/sunwing-alcudia-beach",
        "destination_label": "Majorca, Spain",
        "stars": 4,
        "rating": 4.3,
        "airport_ids": [3],
        "durations": [7],
    },
    {
        "name": "Hotel Flamingo Oasis",
        "url_path": "beach/spain/costa-blanca/benidorm/hotel-flamingo-oasis",
        "destination_label": "Benidorm, Spain",
        "stars": 4,
        "rating": 4.1,
        "airport_ids": [3],
        "durations": [7],
    },
]

OUTPUT_DIR = Path(__file__).parent.parent / "frontend" / "public"
OUTPUT_PATH = OUTPUT_DIR / "pricing_data.json"
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


def build_url(hotel, airport_id, duration, date_obj):
    """
    Build the exact Jet2 URL format:
    /beach/greece/kos/mastichari/gaia-palace?duration=7&occupancy=r2c&airport=3&date=02-05-2026
    """
    date_str = date_obj.strftime("%d-%m-%Y")
    return (
        f"https://www.jet2holidays.com/{hotel['url_path']}"
        f"?duration={duration}"
        f"&occupancy=r2c"
        f"&airport={airport_id}"
        f"&date={date_str}"
    )


async def scrape_hotel(page, hotel, airport_id, duration):
    """Scrape one hotel across all months."""
    now = datetime.now()
    all_month_data = {}

    # Get airport name for logging
    apt_name = next((k for k, v in AIRPORTS.items() if v == airport_id), str(airport_id))

    for month_offset in range(12):
        # Target the 1st of each month
        target = datetime(now.year, now.month, 1) + timedelta(days=32 * month_offset)
        target = target.replace(day=1)
        month_key = target.strftime("%Y-%m")
        month_label = f"{MONTH_NAMES[target.month]} {target.year}"

        url = build_url(hotel, airport_id, duration, target)
        print(f"    {month_label}: {url[:100]}...")

        # Collect intercepted API data
        api_prices = []

        async def capture_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                lo = response.url.lower()
                if any(k in lo for k in ["price", "avail", "package", "room",
                                          "search", "holiday", "calendar",
                                          "basket", "quote", "result"]):
                    body = await response.json()
                    found = _extract_prices(body)
                    api_prices.extend(found)
            except Exception:
                pass

        page.on("response", capture_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        except Exception as e:
            print(f"      ✗ Load failed: {e}")
            page.remove_listener("response", capture_response)
            continue

        # Cookie banner (first load only)
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

        # Wait for price content — try several selectors
        for sel in ["text=£", "[class*='price']", "[class*='Price']"]:
            try:
                await page.wait_for_selector(sel, timeout=10000, state="visible")
                break
            except Exception:
                continue

        # Extra wait for JS to finish rendering
        await asyncio.sleep(4)

        # Scroll to load lazy content
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        await asyncio.sleep(2)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

        # Screenshot for debugging
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        slug = hotel["url_path"].split("/")[-1]
        ss_path = SCREENSHOT_DIR / f"{slug}_{apt_name}_{month_key}.png"
        try:
            await page.screenshot(path=str(ss_path), full_page=True)
        except Exception:
            pass

        # DOM price extraction
        dom_prices = await _extract_dom_prices(page)

        page.remove_listener("response", capture_response)

        # Combine and validate
        all_prices = api_prices + dom_prices

        # Filter out promotional banner prices and duplicates
        valid = []
        seen = set()
        for p in all_prices:
            price = p["price"]
            if price in (100, 50, 25, 200, 150):  # Common promo values
                continue
            if price < 100 or price > 20000:
                continue
            key = (p.get("room", ""), round(price))
            if key not in seen:
                seen.add(key)
                valid.append(p)

        # Check for "not available" on page
        body_text = await page.text_content("body") or ""
        body_lower = body_text.lower()
        unavail_phrases = [
            "no availability", "no holidays found", "currently unavailable",
            "no results", "sorry, there are no", "no packages available",
            "not available for this date"
        ]
        is_unavailable = any(phrase in body_lower for phrase in unavail_phrases)

        if valid and not is_unavailable:
            all_month_data[month_key] = {
                "month_label": month_label,
                "rooms": {}
            }
            for p in valid:
                room = p.get("room", "Standard")
                existing = all_month_data[month_key]["rooms"].get(room)
                if not existing or p["price"] < existing["price_pp"]:
                    all_month_data[month_key]["rooms"][room] = {
                        "price_pp": round(p["price"]),
                        "board_basis": p.get("board", "Unknown"),
                        "departure_date": p.get("date", ""),
                        "available": True,
                        "airport": apt_name,
                        "nights": duration,
                    }
            room_count = len(all_month_data[month_key]["rooms"])
            print(f"      ✓ {len(valid)} prices, {room_count} room types")
        elif is_unavailable:
            print(f"      — not available")
        else:
            print(f"      — no prices found (check screenshot)")

        await asyncio.sleep(3)

    return all_month_data


def _extract_prices(obj, depth=0):
    """Recursively find prices in API JSON responses."""
    if depth > 8 or not obj:
        return []
    found = []
    if isinstance(obj, dict):
        price = None
        for k in ["pricePerPerson", "price", "leadInPrice", "pricePP",
                   "fromPrice", "totalPricePerPerson", "adultPrice",
                   "leadPrice", "pp", "perPerson"]:
            if k in obj:
                try:
                    price = float(obj[k])
                except (ValueError, TypeError):
                    pass
                if price and price > 50:
                    break
        if price and price > 50:
            entry = {"price": price, "date": "", "room": "Standard", "board": "Unknown"}
            for k in ["departureDate", "date", "outboundDate", "departDate"]:
                if k in obj and obj[k]:
                    entry["date"] = str(obj[k])[:10]
                    break
            for k in ["roomType", "roomDescription", "roomName", "name"]:
                if k in obj and isinstance(obj[k], str) and 3 < len(obj[k]) < 80:
                    entry["room"] = obj[k].strip()
                    break
            for k in ["boardBasis", "mealPlan", "board", "boardType"]:
                if k in obj and isinstance(obj[k], str):
                    entry["board"] = obj[k].strip()
                    break
            found.append(entry)
        else:
            for v in obj.values():
                found.extend(_extract_prices(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_extract_prices(item, depth + 1))
    return found


async def _extract_dom_prices(page):
    """Extract prices from visible page, excluding nav/header/footer."""
    results = []
    try:
        # Target only main content area price elements
        price_els = await page.query_selector_all(
            ":is([class*='price'], [class*='Price'], [class*='cost'], "
            "[class*='amount'], [data-testid*='price'])"
            ":not(nav *):not(header *):not(footer *):not([class*='banner'] *)"
            ":not([class*='promo'] *):not([class*='save'] *)"
        )

        for el in price_els:
            try:
                text = await el.inner_text()
                # Skip promotional text
                if any(w in text.lower() for w in ["save", "off", "discount", "was "]):
                    continue

                for m in re.findall(r'£\s*([\d,]+(?:\.\d{2})?)', text):
                    price = float(m.replace(",", ""))
                    if price < 100 or price > 20000:
                        continue

                    room = "Standard"
                    board = "Unknown"
                    date_str = ""

                    # Get context from parent container
                    try:
                        ctx = await el.evaluate(
                            """el => {
                                let p = el;
                                for (let i = 0; i < 6 && p; i++) {
                                    p = p.parentElement;
                                    if (p && p.className && (
                                        /room|card|option|package|result|item/i.test(p.className)
                                    )) return p.innerText;
                                }
                                return el.parentElement?.innerText || '';
                            }"""
                        )
                        if ctx:
                            rm = re.search(
                                r'(Standard|Superior|Family|Suite|Sea View|'
                                r'Deluxe|Premium|Junior Suite|Classic|Studio|'
                                r'Double|Twin|Single|Economy|Garden View|Pool View)',
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

        # Fallback: broader search in main content
        if not results:
            for sel in ["main", "#main", "[role='main']", "[class*='content']"]:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        text = await el.inner_text()
                        for m in re.findall(r'£\s*([\d,]+(?:\.\d{2})?)\s*(?:pp|per\s*person)', text, re.I):
                            price = float(m.replace(",", ""))
                            if 100 < price < 20000:
                                results.append({"price": price, "room": "Standard", "board": "Unknown", "date": ""})
                        if results:
                            break
                except Exception:
                    continue

    except Exception as e:
        print(f"      [DOM error: {e}]")

    return results


async def main():
    from playwright.async_api import async_playwright

    print(f"\n{'='*60}")
    print(f"JET2 SCRAPER v4 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Hotels: {len(TRACKED_HOTELS)}")
    print(f"URL format: /beach/...?duration=X&occupancy=r2c&airport=N&date=dd-mm-yyyy")
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
        page = await context.new_page()

        for hotel in TRACKED_HOTELS:
            for apt_id in hotel["airport_ids"]:
                for dur in hotel["durations"]:
                    apt_name = next((k for k, v in AIRPORTS.items() if v == apt_id), str(apt_id))
                    print(f"\n▶ {hotel['name']} | {apt_name} (ID:{apt_id}) | {dur}N")

                    try:
                        month_data = await scrape_hotel(page, hotel, apt_id, dur)
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
        print(f"  {h['name']}: {len(h['months'])} months, rooms: {', '.join(h['room_types']) or 'none'}")
    print(f"\nTotal: {total_prices} price points across {len(hotel_list)} hotels")
    print(f"Output: {OUTPUT_PATH}")
    if SCREENSHOT_DIR.exists():
        print(f"Screenshots: {len(list(SCREENSHOT_DIR.glob('*.png')))} saved")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
