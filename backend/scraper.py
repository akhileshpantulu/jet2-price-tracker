"""
Jet2holidays Price Scraper v7
==============================
Uses simple HTTP requests (no browser!) to fetch hotel page HTML
and extract pricing from the embedded dataLayer JavaScript object.

The price data is in a <script> tag like:
  dataLayer=[{"ecommerce":{"detail":{"actionField":{"list":"Holiday Details"},
    "products":[{"dimension1":"London Stansted","price":"1666.00",...}]}}}]

URL format:
  jet2holidays.com/beach/greece/kos/mastichari/gaia-palace
    ?duration=7&occupancy=r2c&airport=99&date=01-06-2026
"""

import json
import re
import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

AIRPORTS = {
    "STN": 99,   # London Stansted
    "LGW": 7,    # London Gatwick
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "DNT": "1",
}


def build_url(hotel, airport_id, duration, date_obj):
    return (
        f"https://www.jet2holidays.com/{hotel['url_path']}"
        f"?duration={duration}"
        f"&occupancy=r2c"
        f"&airport={airport_id}"
        f"&date={date_obj.strftime('%d-%m-%Y')}"
    )


def extract_datalayer_prices(html):
    """
    Extract pricing from the dataLayer script embedded in the HTML.
    
    Looks for patterns like:
      dataLayer=[{..."products":[{"price":"1666.00","dimension1":"London Stansted",...}]...}]
    """
    results = []

    # Find all dataLayer assignments
    matches = re.findall(r'dataLayer\s*=\s*(\[.+?\]);\s*', html, re.DOTALL)

    for match in matches:
        try:
            data = json.loads(match)
            for item in data:
                products = None
                # Navigate to products array
                if isinstance(item, dict):
                    ec = item.get("ecommerce", {})
                    if isinstance(ec, dict):
                        detail = ec.get("detail", {})
                        if isinstance(detail, dict):
                            products = detail.get("products", [])

                if not products:
                    continue

                for prod in products:
                    if not isinstance(prod, dict):
                        continue
                    price_str = prod.get("price", "")
                    try:
                        price = float(price_str)
                    except (ValueError, TypeError):
                        continue

                    if price < 50 or price > 30000:
                        continue

                    # Extract details from dimension fields
                    airport = prod.get("dimension1", "")
                    destination = prod.get("dimension2", "")
                    resort = prod.get("dimension3", "")
                    dep_date_raw = prod.get("dimension4", "")
                    ret_date_raw = prod.get("dimension5", "")
                    room_type = prod.get("dimension10", "Standard")
                    dep_airport_full = prod.get("dimension21", "")
                    rating = prod.get("dimension14", "")
                    category = prod.get("category", "")
                    variant = prod.get("variant", "")
                    name = prod.get("departure", prod.get("name", ""))
                    discount = prod.get("dimension22", "0")

                    # Parse departure date
                    dep_date = ""
                    if dep_date_raw and len(dep_date_raw) >= 8:
                        try:
                            dep_date = f"{dep_date_raw[:2]}-{dep_date_raw[2:4]}-{dep_date_raw[4:8]}"
                        except Exception:
                            dep_date = dep_date_raw

                    results.append({
                        "price": price,
                        "airport": airport,
                        "departure_date": dep_date,
                        "room_type": room_type if room_type else "Standard",
                        "destination": destination,
                        "resort": resort,
                        "rating": rating,
                        "discount": discount,
                        "variant": variant,
                    })
        except (json.JSONDecodeError, TypeError):
            continue

    # Also try to find prices in other script patterns
    # Some pages might have different formats
    if not results:
        # Look for JSON-like price objects anywhere in scripts
        price_patterns = re.findall(
            r'"price"\s*:\s*"?([\d.]+)"?',
            html
        )
        # Also look for pricePerPerson patterns
        pp_patterns = re.findall(
            r'"(?:pricePerPerson|leadInPrice|fromPrice)"\s*:\s*"?([\d.]+)"?',
            html
        )

        all_prices = set()
        for p in price_patterns + pp_patterns:
            try:
                price = float(p)
                if 100 < price < 30000:
                    all_prices.add(price)
            except ValueError:
                continue

        for price in sorted(all_prices):
            results.append({
                "price": price,
                "airport": "",
                "departure_date": "",
                "room_type": "Standard",
                "destination": "",
                "resort": "",
                "rating": "",
                "discount": "0",
                "variant": "",
            })

    return results


def extract_additional_prices(html):
    """
    Look for any other price data embedded in the HTML source,
    e.g. in JSON-LD, meta tags, or inline scripts.
    """
    results = []

    # JSON-LD offers
    jsonld_matches = re.findall(
        r'<script\s+type="application/ld\+json">(.*?)</script>',
        html, re.DOTALL
    )
    for jm in jsonld_matches:
        try:
            data = json.loads(jm)
            if isinstance(data, dict):
                offers = data.get("offers", {})
                if isinstance(offers, dict):
                    price = offers.get("price")
                    if price:
                        results.append({
                            "price": float(price),
                            "source": "json-ld",
                        })
                elif isinstance(offers, list):
                    for o in offers:
                        price = o.get("price")
                        if price:
                            results.append({
                                "price": float(price),
                                "source": "json-ld",
                            })
        except Exception:
            continue

    return results


def scrape_hotel(session, hotel, airport_id, duration):
    """Scrape one hotel across all months using HTTP requests."""
    now = datetime.now()
    all_month_data = {}
    apt_name = next((k for k, v in AIRPORTS.items() if v == airport_id), str(airport_id))

    for month_offset in range(12):
        target = datetime(now.year, now.month, 1) + timedelta(days=32 * month_offset)
        target = target.replace(day=1)
        month_key = target.strftime("%Y-%m")
        month_label = f"{MONTH_NAMES[target.month]} {target.year}"

        url = build_url(hotel, airport_id, duration, target)
        print(f"    {month_label}: ", end="", flush=True)

        try:
            resp = session.get(url, headers=HEADERS, timeout=15, allow_redirects=True)

            if resp.status_code == 403:
                print("✗ blocked (403)")
                continue
            elif resp.status_code == 404:
                print("— not found (404)")
                continue
            elif resp.status_code >= 400:
                print(f"✗ HTTP {resp.status_code}")
                continue

            html = resp.text

            # Check for no availability in HTML
            lower = html.lower()
            if any(p in lower for p in [
                "no availability", "no holidays found",
                "currently unavailable", "no results found",
                "sorry, there are no"
            ]):
                print("— not available")
                continue

            # Extract prices from dataLayer
            prices = extract_datalayer_prices(html)

            # Also check JSON-LD and other sources
            extra = extract_additional_prices(html)
            if extra:
                for e in extra:
                    prices.append({
                        "price": e["price"],
                        "airport": apt_name,
                        "departure_date": "",
                        "room_type": "Standard",
                        "destination": "",
                        "resort": "",
                        "rating": "",
                        "discount": "0",
                        "variant": "",
                    })

            # Filter valid prices
            valid = []
            seen = set()
            for p in prices:
                price = p["price"]
                if price < 100 or price > 30000:
                    continue
                key = (p.get("room_type", ""), round(price))
                if key not in seen:
                    seen.add(key)
                    valid.append(p)

            if valid:
                all_month_data[month_key] = {"month_label": month_label, "rooms": {}}
                for p in valid:
                    room = p.get("room_type", "Standard") or "Standard"
                    existing = all_month_data[month_key]["rooms"].get(room)
                    if not existing or p["price"] < existing["price_pp"]:
                        all_month_data[month_key]["rooms"][room] = {
                            "price_pp": round(p["price"]),
                            "board_basis": p.get("variant", "Unknown") or "Unknown",
                            "departure_date": p.get("departure_date", ""),
                            "available": True,
                            "airport": apt_name,
                            "nights": duration,
                        }
                print(f"✓ £{valid[0]['price']:.0f}" +
                      (f" (+{len(valid)-1} more)" if len(valid) > 1 else ""))
            else:
                # Check if page loaded at all
                if len(html) < 1000:
                    print(f"✗ empty response ({len(html)} bytes)")
                else:
                    print(f"— no prices in source ({len(html)} bytes)")

        except requests.exceptions.Timeout:
            print("✗ timeout")
        except requests.exceptions.ConnectionError as e:
            print(f"✗ connection error")
        except Exception as e:
            print(f"✗ {str(e)[:50]}")

        time.sleep(1)  # Be respectful

    return all_month_data


def main():
    print(f"\n{'='*60}")
    print(f"JET2 SCRAPER v7 (HTTP) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"No browser needed — direct HTTP requests")
    print(f"{'='*60}")

    all_hotels = {}
    total_prices = 0

    session = requests.Session()

    # Visit homepage first for cookies
    print("\nGetting session cookies from homepage...")
    try:
        resp = session.get("https://www.jet2holidays.com/",
                          headers=HEADERS, timeout=15)
        print(f"✓ Homepage: {resp.status_code} ({len(resp.text)} bytes)")
    except Exception as e:
        print(f"✗ Homepage: {e}")

    for hotel in TRACKED_HOTELS:
        for apt_id in hotel["airport_ids"]:
            for dur in hotel["durations"]:
                apt_name = next((k for k, v in AIRPORTS.items() if v == apt_id), str(apt_id))
                print(f"\n▶ {hotel['name']} | {apt_name} (ID:{apt_id}) | {dur}N")

                month_data = scrape_hotel(session, hotel, apt_id, dur)

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

                time.sleep(1)

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
        months_with_prices = len(h["months"])
        print(f"  {h['name']}: {months_with_prices} months, rooms: {', '.join(h['room_types']) or 'none'}")
    if not hotel_list:
        print("  ⚠ No prices found")
    print(f"\nTotal: {total_prices} prices across {len(hotel_list)} hotels")
    print(f"Output: {OUTPUT_PATH}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
