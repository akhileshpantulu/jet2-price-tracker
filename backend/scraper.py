"""
Jet2holidays Price Scraper v6
==============================
- No external dependencies beyond playwright
- Manual stealth patches (no playwright-stealth needed)
- HTTP/2 disabled to fix ERR_HTTP2_PROTOCOL_ERROR
- Correct Jet2 URL format

URL format:
  jet2holidays.com/beach/greece/kos/mastichari/gaia-palace
    ?duration=7&occupancy=r2c&airport=3&date=02-05-2026
"""

import json
import re
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

AIRPORTS = {
    "STN": 99,   # London Stansted
    "LGW": 7,    # London Gatwick
    "LTN": 127,  # London Luton
}

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

TRACKED_HOTELS = [
    {
        "name": "Gaia Palace",
        "url_path": "beach/greece/kos/mastichari/gaia-palace",
        "destination_label": "Kos, Greece",
        "stars": 5,
        "rating": 4.5,
        "airport_ids": [99, 7, 127],
        "durations": [7],
    },
    {
        "name": "Sunwing Alcudia Beach",
        "url_path": "beach/balearics/majorca/alcudia/sunwing-alcudia-beach",
        "destination_label": "Majorca, Spain",
        "stars": 4,
        "rating": 4.3,
        "airport_ids": [99, 7, 127],
        "durations": [7],
    },
    {
        "name": "Hotel Flamingo Oasis",
        "url_path": "beach/spain/costa-blanca/benidorm/hotel-flamingo-oasis",
        "destination_label": "Benidorm, Spain",
        "stars": 4,
        "rating": 4.1,
        "airport_ids": [99, 7, 127],
        "durations": [7],
    },
]

OUTPUT_DIR = Path(__file__).parent.parent / "frontend" / "public"
OUTPUT_PATH = OUTPUT_DIR / "pricing_data.json"
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


STEALTH_JS = """
() => {
    // Hide webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    
    // Fix chrome object
    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
    
    // Fix permissions
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(parameters);
    
    // Fix plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    
    // Fix languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-GB', 'en'],
    });
}
"""


def build_url(hotel, airport_id, duration, date_obj):
    return (
        f"https://www.jet2holidays.com/{hotel['url_path']}"
        f"?duration={duration}"
        f"&occupancy=r2c"
        f"&airport={airport_id}"
        f"&date={date_obj.strftime('%d-%m-%Y')}"
    )


async def safe_goto(page, url, retries=2):
    """Navigate with retries for HTTP2 errors."""
    for attempt in range(retries):
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            if resp and resp.status and resp.status >= 400:
                print(f"[HTTP {resp.status}] ", end="", flush=True)
                if resp.status == 403:
                    return False
            return True
        except Exception as e:
            err = str(e)
            if attempt < retries - 1:
                print(f"[retry {attempt+1}] ", end="", flush=True)
                await asyncio.sleep(2)
            else:
                print(f"[failed: {err[:50]}] ", end="", flush=True)
                return False
    return False


async def scrape_hotel(page, hotel, airport_id, duration):
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
                    api_prices.extend(_extract_prices(body))
            except Exception:
                pass

        page.on("response", capture_response)

        ss_path = SCREENSHOT_DIR / f"{slug}_{apt_name}_{month_key}.png"

        loaded = await safe_goto(page, url)

        if not loaded:
            print("✗ failed")
            page.remove_listener("response", capture_response)
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

        # Wait for price elements
        for sel in ["text=£", "[class*='price']", "[class*='Price']"]:
            try:
                await page.wait_for_selector(sel, timeout=10000, state="visible")
                break
            except Exception:
                continue

        await asyncio.sleep(3)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        await asyncio.sleep(2)

        # Screenshot
        try:
            await page.screenshot(path=str(ss_path), full_page=True)
        except Exception:
            pass

        # DOM prices
        dom_prices = await _extract_dom_prices(page)
        page.remove_listener("response", capture_response)

        # Combine + filter
        valid = []
        seen = set()
        for p in api_prices + dom_prices:
            price = p["price"]
            if price in (100, 50, 25, 200, 150) or price < 100 or price > 20000:
                continue
            key = (p.get("room", ""), round(price))
            if key not in seen:
                seen.add(key)
                valid.append(p)

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
                        "available": True,
                        "airport": apt_name,
                        "nights": duration,
                    }
            print(f"✓ {len(valid)} prices")
        elif unavail:
            print("— not available")
        else:
            print("— no prices found")

        await asyncio.sleep(1)

    return all_month_data


def _extract_prices(obj, depth=0):
    if depth > 8 or not obj:
        return []
    found = []
    if isinstance(obj, dict):
        price = None
        for k in ["pricePerPerson", "price", "leadInPrice", "pricePP",
                   "fromPrice", "totalPricePerPerson", "adultPrice"]:
            if k in obj:
                try:
                    price = float(obj[k])
                except (ValueError, TypeError):
                    pass
                if price and price > 50:
                    break
        if price and price > 50:
            entry = {"price": price, "room": "Standard", "board": "Unknown", "date": ""}
            for k in ["departureDate", "date", "outboundDate"]:
                if k in obj and obj[k]:
                    entry["date"] = str(obj[k])[:10]; break
            for k in ["roomType", "roomDescription", "roomName", "name"]:
                if k in obj and isinstance(obj[k], str) and 3 < len(obj[k]) < 80:
                    entry["room"] = obj[k].strip(); break
            for k in ["boardBasis", "mealPlan", "board"]:
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
                    room, board = "Standard", "Unknown"
                    try:
                        ctx = await el.evaluate("""el => {
                            let p = el;
                            for (let i = 0; i < 6 && p; i++) {
                                p = p.parentElement;
                                if (p && p.className &&
                                    /room|card|option|package|result|item/i.test(p.className))
                                    return p.innerText;
                            }
                            return el.parentElement?.innerText || '';
                        }""")
                        rm = re.search(r'(Standard|Superior|Family|Suite|Sea View|Deluxe|Premium|Double|Twin)', ctx, re.I)
                        if rm: room = rm.group(1).title()
                        bm = re.search(r'(Self Catering|Bed (?:&|and) Breakfast|Half Board|Full Board|All Inclusive)', ctx, re.I)
                        if bm: board = bm.group(1)
                    except Exception:
                        pass
                    results.append({"price": price, "room": room, "board": board, "date": ""})
            except Exception:
                continue
    except Exception as e:
        print(f"[DOM: {e}] ", end="")
    return results


async def main():
    print(f"\n{'='*60}")
    print(f"JET2 SCRAPER v6 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    all_hotels = {}
    total_prices = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-http2",
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
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )

        # Apply stealth patches
        await context.add_init_script(STEALTH_JS)

        page = await context.new_page()

        # Visit homepage first to get cookies
        print("\nVisiting homepage for session cookies...")
        try:
            await page.goto("https://www.jet2holidays.com/",
                          wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept')"]:
                try:
                    btn = page.locator(sel)
                    if await btn.count() > 0:
                        await btn.first.click(timeout=3000)
                        break
                except Exception:
                    pass
            await page.screenshot(path=str(SCREENSHOT_DIR / "00_homepage.png"))
            print("✓ Homepage loaded")
        except Exception as e:
            print(f"✗ Homepage: {e}")
            # Take screenshot anyway
            try:
                await page.screenshot(path=str(SCREENSHOT_DIR / "00_homepage_error.png"))
            except Exception:
                pass

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
        print("  ⚠ No prices found — check screenshots")
    print(f"Total: {total_prices} prices | Output: {OUTPUT_PATH}")
    print(f"Screenshots: {len(list(SCREENSHOT_DIR.glob('*.png')))} saved")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
