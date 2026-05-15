#!/usr/bin/env python3
"""Test whether /4/find works with progressively fewer credentials.
Run this once credentials.yaml is populated to find the minimum auth needed for polling.

Usage: python test_anon_polling.py
"""

import json
import requests
from datetime import datetime, timedelta

from lib.auth import load_credentials

API_BASE = "https://api.resy.com"
PUBLIC_API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"

# Weak app-level token spotted in the wild (leavenstee/hot-date, circa 2018).
# May be expired — worth trying.
WEAK_TOKEN = "yDFWhG7_KneKK2Nj9veohXnEgZu3XuF0DT491IVN5i17tXJ1nkj6pFV3e0ENb5dZ"

# 4 Charles Prime Rib — known venue, reliably has some inventory
TEST_VENUE_ID = 893
TEST_PARTY_SIZE = 2
TEST_DAY = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")


def try_find(label: str, headers: dict) -> bool:
    params = {
        "lat": 0,
        "long": 0,
        "day": TEST_DAY,
        "party_size": TEST_PARTY_SIZE,
        "venue_id": TEST_VENUE_ID,
    }
    try:
        r = requests.get(f"{API_BASE}/4/find", params=params, headers=headers, timeout=10)
        status = r.status_code
        slots = []
        if status == 200:
            for v in r.json().get("results", {}).get("venues", []):
                slots.extend(v.get("slots", []))
        result = f"HTTP {status}"
        if status == 200:
            result += f" — {len(slots)} slot(s) returned"
        else:
            result += f" — {r.text[:120]}"
        ok = status == 200
        icon = "✓" if ok else "✗"
        print(f"  {icon}  [{label}] {result}")
        return ok
    except Exception as e:
        print(f"  !  [{label}] Exception: {e}")
        return False


def base_headers():
    return {
        "Origin": "https://resy.com",
        "Referer": "https://resy.com/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Safari/605.1.15"
        ),
        "Accept": "application/json, text/plain, */*",
    }


def main():
    creds = load_credentials()
    auth_token = creds["auth_token"]
    api_key = creds.get("api_key", PUBLIC_API_KEY)

    print(f"\nTarget: venue_id={TEST_VENUE_ID}, day={TEST_DAY}, party={TEST_PARTY_SIZE}\n")

    cases = [
        (
            "full auth (baseline)",
            {
                **base_headers(),
                "Authorization": f'ResyAPI api_key="{api_key}"',
                "X-Resy-Auth-Token": auth_token,
                "X-Resy-Universal-Auth": auth_token,
            },
        ),
        (
            "api_key only, no auth_token headers",
            {
                **base_headers(),
                "Authorization": f'ResyAPI api_key="{api_key}"',
            },
        ),
        (
            "api_key + weak token (X-Resy-Auth-Token only)",
            {
                **base_headers(),
                "Authorization": f'ResyAPI api_key="{api_key}"',
                "X-Resy-Auth-Token": WEAK_TOKEN,
            },
        ),
        (
            "api_key + weak token (both auth headers)",
            {
                **base_headers(),
                "Authorization": f'ResyAPI api_key="{api_key}"',
                "X-Resy-Auth-Token": WEAK_TOKEN,
                "X-Resy-Universal-Auth": WEAK_TOKEN,
            },
        ),
        (
            "no auth at all (bare headers only)",
            base_headers(),
        ),
    ]

    results = {}
    for label, headers in cases:
        results[label] = try_find(label, headers)

    print("\n--- Summary ---")
    winners = [label for label, ok in results.items() if ok]
    if not winners:
        print("No anonymous/partial-auth path found. Need full user auth for polling.")
    else:
        print("Working with reduced credentials:")
        for w in winners:
            print(f"  - {w}")
        if "api_key only, no auth_token headers" in winners:
            print("\nVerdict: can poll anonymously with just the public api_key. No second account needed.")
        elif any("weak" in w for w in winners):
            print("\nVerdict: weak app-level token works for polling. No user account needed.")
        else:
            print("\nVerdict: full user auth required for all cases that worked.")


if __name__ == "__main__":
    main()
