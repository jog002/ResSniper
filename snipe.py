#!/usr/bin/env python3
"""One-shot booker. Called by watcher.py as a subprocess when a slot is found."""

import argparse
import json
import os
import sys
import time

from lib.provider_base import Slot
from lib.providers import get_book_client
from lib.auth import load_provider_credentials
from lib.notifier import notify

parser = argparse.ArgumentParser(description="Book a single reservation slot")
parser.add_argument("slug")
parser.add_argument("--provider", default="resy")
parser.add_argument("--venue-key", required=True)
parser.add_argument("--booking-token", required=True)
parser.add_argument("--day", required=True)
parser.add_argument("--party-size", type=int, required=True)
parser.add_argument("--match-kind", required=True)
parser.add_argument("--seating-type", default="Dining Room")
parser.add_argument("--time", required=True)
args = parser.parse_args()

slot = Slot(
    provider=args.provider,
    venue_key=args.venue_key,
    day=args.day,
    time=args.time,
    seating_type=args.seating_type,
    booking_token=args.booking_token,
    party_size=args.party_size,
)

creds = load_provider_credentials(args.provider)
client = get_book_client(args.provider, creds)

t0 = time.time()
try:
    book_token = client.details(slot)
    result = client.book(book_token, slot)
    elapsed = time.time() - t0
    rid = result.get("reservation_id", "?")
    notify(
        f"BOOKED {args.slug}",
        f"{args.day} party of {args.party_size} ({args.match_kind}) in {elapsed:.1f}s\nID: {rid}",
        level="success",
    )
    os.makedirs("state", exist_ok=True)
    with open("state/booked.json", "a") as f:
        f.write(
            json.dumps(
                {
                    "ts": time.time(),
                    "slug": args.slug,
                    "day": args.day,
                    "party_size": args.party_size,
                    "match": args.match_kind,
                    "provider": args.provider,
                    "result": result,
                }
            )
            + "\n"
        )
except Exception as e:
    notify(
        f"FAILED {args.slug}",
        f"{args.day} {args.party_size}p: {type(e).__name__}: {e}",
        level="error",
    )
    sys.exit(1)
