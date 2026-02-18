"""
Jet2holidays Price Scraper v5
==============================
Fixes ERR_HTTP2_PROTOCOL_ERROR by:
- Using playwright-stealth to avoid bot detection
- Disabling HTTP/2 (forces HTTP/1.1)
- Adding realistic browser fingerprint
- Retrying with fallback strategies

URL format:
  jet2holidays.com/beach/greece/kos/mastichari/gaia-palace
    ?duration=7&occupancy=r2c&airport=3&date=02-05-2026
"""

import json
import re
import os
import sys
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# Install stealth plugin if missing
try:
    from playwright_stealth import stealth_async
except ImportError:
    os.system(f"{sys.executable} -m pip install playwright-stealth")
    from playwright_stealth import stealth_async

AIRPORTS = {
    "STN": 99,   # London Stansted
    "LGW": 7,  # London Gatwick
    "LTN": 127,  # London Luton
}

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

# ----------------------------------------------------------------
# EDIT THIS — add/remove hotels
# url_path = everything after jet2holidays.com/ in the hotel URL
# ----------------------------------------------------------------
TRACKED_HOTELS = [
    {
        "name": "Gaia Palace",
        "url_path": "beach/greece/kos/mastichari/gaia-palace",
        "destination_label": "Kos, Greece",
        "stars": 5,
        "rating": 4.5,
        "airport_ids": [3],
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
    date_str = date_obj.strftime("%d-%m-%Y")
    return (
        f"https://www.jet2holidays.com/{hotel['url_path']}"
        f"?duration={duration}"
        f"&occupancy=r2c"
        f"&airport={airport_id}"
        f"&date={date_str}"
    )


async def safe_goto(page, url, screenshot_path=None, retries=3):
    """Navigate with retries and different wait strategies."""
    for attempt in range(retries):
        try:
            if attempt == 0:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            elif attempt == 1:
                resp = await page.goto(url, wait_until="commit", timeout=30000)
                await asyncio.sleep(5)
            else:
                resp = await page.goto(url, timeout=30000)
                await asyncio.sleep(8)

            if resp and resp.status and resp.status < 400:
                return True
            elif resp:
                print(f"[HTTP {resp.status}] ", end="", flush=True)
                if resp.status == 403:
                    print("BLOCKED ", end="", flush=True)
                    return False

            return True

        except Exception as e:
            err_str = str(e)
            if "ERR_HTTP2_PROTOCOL_ERROR" in err_str:
                print(f"[H2 err, retry {attempt+1}] ", end="", flush=True)
                await asyncio.sleep(3 + attempt * 3)
            elif "Timeout" in err_str:
                print(f"[timeout, retry {attempt+1}] ", end="", flush=True)
                await asyncio.sleep(2)
            else:
                print(f"[err: {err_str[:50]}, retry {attempt+1}] ", end="", flush=True)
                await asyncio.sleep(2)

    # Take screenshot of whatever state we're in
    if screenshot_path:
        try:
            await page.screenshot(path=str(screenshot_path))
        except Exception:
            pass

    return False


async def scrape_hotel(page, hotel, airport_id, duration):
    """Scrape one hotel month by month."""
    now = datetime.now()
    all_month_data = {}
    apt_name = next((k for k, v in AIRPORTS.items() if v == airport_id), str(airport_id))
    slug = hotel["url_path"].split("/")[-1]

    for month_offset in range(12):
        target = datetime(now.year, now.month, 1) + timedelta(days=32 * month_offset)
        target = target.replace(day=1)
        month_key = target.strftime("%Y-%m")
        month_label = f"{MONTH_NAMES[target.month]} {target.year}"

        url = build_url(hotel, airport_id, duration, target)
        print(f"    {month_label}: ", end="", flush=True)

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

        ss_path = SCREENSHOT_DIR / f"{slug}_{apt_name}_{month_key}.png"
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        loaded = await safe_goto(page, url, screenshot_path=ss_path)

        if not loaded:
            print("✗ failed to load")
            page.remove_listener("response", capture_response)
            # Still take a screenshot of whatever we see
            try:
                await page.screenshot(path=str(ss_path))
            except Exception:
                pass
            await asyncio.sleep(5)
            continue

        # Cookie banner (first load)
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

        # Wait for prices to appear
        for sel in ["text=£", "[class*='price']", "[class*='Price']"]:
            try:
                await page.wait_for_selector(sel, timeout=10000, state="visible")
                break
            except Exception:
                continue

        await asyncio.sleep(3)

        # Scroll
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        await asyncio.sleep(2)

        # Screenshot (always, even if no prices found)
        try:
            await page.screenshot(path=str(ss_path), full_page=True)
        except Exception:
            pass

        # DOM extraction
        dom_prices = await _extract_dom_prices(page)
        page.remove_listener("response", capture_response)

        # Combine and validate
        all_prices = api_prices + dom_prices
        valid = []
        seen = set()
        for p in all_prices:
            price = p["price"]
            if price in (100, 50, 25, 200, 150):
                continue
            if price < 100 or price > 20000:
                continue
            key = (p.get("room", ""), round(price))
            if key not in seen:
                seen.add(key)
                valid.append(p)

        # Check availability
        body_text = (await page.text_content("body") or "").lower()
        unavail = any(p in body_text for p in [
            "no availability", "no holidays found", "currently unavailable",
            "no results", "sorry, there are no", "not available"
        ])

        if valid and not unavail:
            all_month_data[month_key] = {"month_label": month_label, "rooms": {}}
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
            print(f"✓ {len(valid)} prices, {len(all_month_data[month_key]['rooms'])} rooms")
        elif unavail:
            print("— not available")
        else:
            print("— no prices found")

        await asyncio.sleep(4)

    return all_month_data


def _extract_prices(obj, depth=0):
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
                    entry["date"] = str(obj[k])[:10]; break
            for k in ["roomType", "roomDescription", "roomName", "name"]:
                if k in obj and isinstance(obj[k], str) and 3 < len(obj[k]) < 80:
                    entry["room"] = obj[k].strip(); break
            for k in ["boardBasis", "mealPlan", "board", "boardType"]:
                if k in obj and isinstance(obj[k], str):
                    entry["board"] = obj[k].strip(); break
            found.append(entry)
        else:
            for v in obj.values():
                found.extend(_extract_prices(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_extract_prices(item, depth + 1))
    return found


async def _extract_dom_prices(page):
    results = []
    try:
        price_els = await page.query_selector_all(
            ":is([class*='price'], [class*='Price'], [class*='cost'], "
            "[class*='amount'], [data-testid*='price'])"
            ":not(nav *):not(header *):not(footer *)"
            ":not([class*='banner'] *):not([class*='promo'] *)"
        )
        for el in price_els:
            try:
                text = await el.inner_text()
                if any(w in text.lower() for w in ["save", "off", "discount"]):
                    continue
                for m in re.findall(r'£\s*([\d,]+(?:\.\d{2})?)', text):
                    price = float(m.replace(",", ""))
                    if price < 100 or price > 20000:
                        continue
                    room = "Standard"
                    board = "Unknown"
                    try:
                        ctx = await el.evaluate(
                            """el => {
                                let p = el;
                                for (let i = 0; i < 6 && p; i++) {
                                    p = p.parentElement;
                                    if (p && p.className &&
                                        /room|card|option|package|result|item/i.test(p.className))
                                        return p.innerText;
                                }
                                return el.parentElement?.innerText || '';
                            }"""
                        )
                        rm = re.search(r'(Standard|Superior|Family|Suite|Sea View|Deluxe|Premium|Double|Twin)', ctx, re.I)
                        if rm: room = rm.group(1).title()
                        bm = re.search(r'(Self Catering|Bed (?:&|and) Breakfast|Half Board|Full Board|All Inclusive)', ctx, re.I)
                        if bm: board = bm.group(1)
                    except Exception:
                        pass
                    results.append({"price": price, "room": room, "board": board, "date": ""})
            except Exception:
                continue

        if not results:
            for sel in ["main", "[role='main']", "[class*='content']"]:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        text = await el.inner_text()
                        for m in re.findall(r'£\s*([\d,]+(?:\.\d{2})?)\s*(?:pp|per\s*person)', text, re.I):
                            price = float(m.replace(",", ""))
                            if 100 < price < 20000:
                                results.append({"price": price, "room": "Standard", "board": "Unknown", "date": ""})
                        if results: break
                except Exception:
                    continue
    except Exception as e:
        print(f"[DOM: {e}] ", end="")
    return results


async def main():
    from playwright.async_api import async_playwright

    print(f"\n{'='*60}")
    print(f"JET2 SCRAPER v5 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    all_hotels = {}
    total_prices = 0

    async with async_playwright() as p:
        # Launch with HTTP/2 disabled to avoid ERR_HTTP2_PROTOCOL_ERROR
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-http2",          # Force HTTP/1.1
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-GB",
            timezone_id="Europe/London",
            java_script_enabled=True,
            # Add realistic browser headers
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            },
        )

        page = await context.new_page()

        # Apply stealth to avoid bot detection
        await stealth_async(page)

        # First, visit the homepage to establish cookies/session
        print("\nEstablishing session via homepage...")
        try:
            await page.goto("https://www.jet2holidays.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            # Accept cookies
            for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept')"]:
                try:
                    btn = page.locator(sel)
                    if await btn.count() > 0:
                        await btn.first.click(timeout=3000)
                        await asyncio.sleep(1)
                        break
                except Exception:
                    pass
            print("✓ Homepage loaded, cookies set")

            # Take a homepage screenshot for reference
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(SCREENSHOT_DIR / "00_homepage.png"))
        except Exception as e:
            print(f"✗ Homepage failed: {e}")

        await asyncio.sleep(2)

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
                                for rn in md["rooms"]:
                                    all_hotels[key]["room_types"].add(rn)
                                    total_prices += 1
                    except Exception as e:
                        print(f"  ✗ Error: {e}")
                    await asyncio.sleep(3)

        await browser.close()

    # Output
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
    print("RESULTS:")
    for h in hotel_list:
        print(f"  {h['name']}: {len(h['months'])} months, rooms: {', '.join(h['room_types']) or 'none'}")
    if not hotel_list:
        print("  ⚠ No prices found — check screenshots for what the browser sees")
    print(f"\nTotal: {total_prices} prices across {len(hotel_list)} hotels")
    print(f"Output: {OUTPUT_PATH}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
