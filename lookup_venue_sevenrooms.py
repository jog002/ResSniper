#!/usr/bin/env python3
"""Discover the SevenRooms venue slug (venue_key) for a restaurant.

Visits the restaurant's website using a headless browser, intercepts
SevenRooms widget requests, and extracts the venue slug.

Usage:
  python lookup_venue_sevenrooms.py <restaurant_website_url>

Examples:
  python lookup_venue_sevenrooms.py https://www.catchrestaurants.com/location/catch-nyc/
  python lookup_venue_sevenrooms.py danielnyc.com
"""

import re
import sys
import urllib.parse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def extract_slugs_from_url(url: str) -> list[str]:
    """Extract venue slug(s) from a SevenRooms URL."""
    parsed = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(parsed.query))

    # venues=catchdallas,catchla,catchny  (group page with multiple locations)
    if "venues" in params:
        return [s.strip() for s in params["venues"].split(",") if s.strip()]
    # venue=catchny  (single-venue availability API call)
    if "venue" in params:
        return [params["venue"]]
    # /explore/{group}/reservations/{slug}  or  /reservations/{slug}
    m = re.search(r"/reservations/([a-z0-9_-]+)", url, re.I)
    if m:
        return [m.group(1)]
    return []


def lookup(restaurant_url: str) -> tuple[list[str], str | None]:
    """
    Returns (venue_slugs, source_url).
    venue_slugs: list of slugs found (e.g. ["catchny"] or multiple for group pages)
    source_url: the SevenRooms URL where they were found
    """
    if not restaurant_url.startswith("http"):
        restaurant_url = "https://" + restaurant_url

    print(f"Opening: {restaurant_url}")
    found_slugs: list[str] = []
    found_source = None

    def on_request(request):
        nonlocal found_source
        if found_slugs:
            return
        url = request.url
        if "sevenrooms.com" not in url:
            return
        slugs = extract_slugs_from_url(url)
        if slugs:
            found_slugs.extend(slugs)
            found_source = url

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", on_request)

        try:
            page.goto(restaurant_url, wait_until="domcontentloaded", timeout=20_000)
            # Wait for initial JS to run
            page.wait_for_timeout(2_000)

            # Try clicking reservation-related buttons to trigger the widget
            RESERVE_SELECTORS = [
                "text=Reserve",
                "text=Reservations",
                "text=Book a Table",
                "text=Book Now",
                "text=Make a Reservation",
                "a[href*='sevenrooms']",
                "button[class*='reserv' i]",
                "a[class*='reserv' i]",
            ]
            for selector in RESERVE_SELECTORS:
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=500):
                        el.click(timeout=1000)
                        print(f"  Clicked: {selector!r}")
                        page.wait_for_timeout(2_000)
                        if found_slug:
                            break
                except Exception:
                    continue

            # Final wait for any lazy requests
            if not found_slugs:
                page.wait_for_timeout(3_000)
        except PlaywrightTimeout:
            pass
        except Exception as e:
            print(f"Page error (continuing): {e}")
        finally:
            browser.close()

    return found_slugs, found_source


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    slugs, source = lookup(sys.argv[1])

    if slugs:
        if len(slugs) == 1:
            slug = slugs[0]
            print(f"\nvenue_key (use this in watch-rules.yaml): {slug}")
        else:
            print(f"\nMultiple venues found (this is a group page with multiple locations):")
            for i, s in enumerate(slugs):
                print(f"  [{i}] {s}")
            choice = input("Enter the number of the venue you want, or type the slug directly: ").strip()
            try:
                slug = slugs[int(choice)]
            except (ValueError, IndexError):
                slug = choice or slugs[0]
            print(f"\nvenue_key: {slug}")
        print(f"Found in: {source}")
        print(f"\nVerify with:")
        print(f"  python -c \"from lib.providers import get_poll_client; import datetime; "
              f"d=(datetime.date.today()+datetime.timedelta(days=1)).strftime('%Y-%m-%d'); "
              f"c=get_poll_client('sevenrooms'); slots=c.find('{slug}',d,2); print(len(slots),'slots')\"")
    else:
        print(
            "\nCould not find SevenRooms venue slug on this page.\n"
            "Possible reasons:\n"
            "  - The restaurant uses a different booking system\n"
            "  - The widget loads after additional user interaction\n"
            "\nManual steps:\n"
            "  1. Open the restaurant's reservation page in Chrome\n"
            "  2. DevTools → Network → filter 'sevenrooms'\n"
            "  3. Look for a URL containing 'venues=' or 'venue='\n"
            "  4. Copy that slug value"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
