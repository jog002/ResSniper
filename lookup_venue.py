#!/usr/bin/env python3
"""Look up venue_id from a Resy restaurant URL.
Usage: python lookup_venue.py https://resy.com/cities/ny/4-charles-prime-rib
"""

import json
import re
import sys
import urllib.request


def lookup(url: str) -> str | None:
    if not url.startswith("http"):
        url = "https://resy.com/cities/" + url

    print(f"Fetching {url} ...")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Safari/605.1.15"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Try __NEXT_DATA__ JSON blob first (most reliable)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            raw = json.dumps(data)
            ids = re.findall(r'"venue_id"\s*:\s*(\d+)', raw)
            if ids:
                return ids[0]
        except Exception:
            pass

    # Fallback patterns in raw HTML
    patterns = [
        (r'venue_id["\s:=]+(\d+)', "venue_id attribute"),
        (r'/api\.resy\.com/4/find\?[^"]*venue_id=(\d+)', "find API URL"),
        (r'"id"\s*:\s*(\d+)', "JSON id field"),
    ]
    for pat, label in patterns:
        ids = re.findall(pat, html)
        if ids:
            print(f"  (matched via {label})")
            return ids[0]

    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python lookup_venue.py <resy_url_or_slug>")
        print("  e.g. python lookup_venue.py https://resy.com/cities/ny/4-charles-prime-rib")
        print("  or:  python lookup_venue.py ny/4-charles-prime-rib")
        sys.exit(1)

    url = sys.argv[1]
    venue_id = lookup(url)

    if venue_id:
        print(f"\nvenue_id: {venue_id}")
    else:
        print(
            "\nCould not extract venue_id automatically.\n"
            "Open the restaurant page in a browser with DevTools > Network,\n"
            "click the date picker, and look for a request to /4/find?venue_id=..."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
