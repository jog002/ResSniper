#!/usr/bin/env python3
"""Scheduled drop sniper. Launched by cron at known drop times.
Sleeps until just before the drop, then polls hard and books the best match.

Args: slug target_date drop_timestamp_utc
  target_date: YYYY-MM-DD (the date to book, e.g. 30 days from now)
  drop_timestamp_utc: Unix timestamp when the restaurant opens inventory
"""

import json
import os
import sys
import time
import yaml

from lib.provider_base import Slot, AuthExpiredError, CaptchaError, RateLimitedError
from lib.providers import get_poll_client, get_book_client, resolve_venue_key, resolve_provider
from lib.auth import load_provider_credentials
from lib.notifier import notify

POLL_INTERVAL_SECONDS = 0.5   # poll every 500ms during the hot window
PREFERRED_TIMEOUT = 60        # seconds to wait for a preferred slot
TOTAL_TIMEOUT = 300           # give up after 5 minutes


def find_best_slot(slots: list[Slot], preferred_times, fallback_times, use_fallback=False):
    """Return (slot, priority) for the best available slot, or (None, None)."""
    time_set = fallback_times if use_fallback else preferred_times
    for target in time_set:
        for slot in slots:
            hhmm = slot.time.split(" ")[1][:5]
            if hhmm == target:
                return slot, ("fallback" if use_fallback else "preferred")
    return None, None


def main():
    if len(sys.argv) < 4:
        print("Usage: scheduled_snipe.py <slug> <target_date> <drop_timestamp_utc>")
        sys.exit(1)

    slug = sys.argv[1]
    target_date = sys.argv[2]
    drop_ts = float(sys.argv[3])

    with open("scheduled-drops.yaml") as f:
        config = yaml.safe_load(f)

    if slug not in config.get("drops", {}):
        print(f"[scheduled_snipe] '{slug}' not found in scheduled-drops.yaml")
        sys.exit(1)

    rule = config["drops"][slug]
    party_size = rule.get("party_size", 2)
    preferred_times = rule.get("preferred_times", [])
    fallback_times = rule.get("fallback_times", [])

    provider = resolve_provider(rule, {})
    venue_key = resolve_venue_key(rule)
    poll_client = get_poll_client(provider)
    creds = load_provider_credentials(provider)
    book_client = get_book_client(provider, creds)

    # Sleep until 30 seconds before drop
    sleep_until = drop_ts - 30
    wait = sleep_until - time.time()
    if wait > 0:
        notify(
            f"Scheduled snipe armed: {slug}",
            f"Target: {target_date}, drop in {wait/60:.1f} min",
        )
        time.sleep(wait)

    notify(f"Snipe window open: {slug}", f"Polling {target_date} at drop time")
    t_start = time.time()
    use_fallback = False

    while True:
        elapsed = time.time() - t_start

        if elapsed > TOTAL_TIMEOUT:
            notify(
                f"Snipe timed out: {slug}",
                f"No booking after {TOTAL_TIMEOUT}s for {target_date}",
                level="warn",
            )
            sys.exit(1)

        if elapsed > PREFERRED_TIMEOUT and not use_fallback:
            use_fallback = True
            notify(
                f"Falling back to fallback times: {slug}",
                f"No preferred slot in {PREFERRED_TIMEOUT}s, trying fallback",
                level="warn",
            )

        try:
            slots = poll_client.find(venue_key, target_date, party_size)
        except AuthExpiredError:
            notify("Auth expired during snipe", "Run refresh_auth.py", level="error")
            sys.exit(1)
        except (RateLimitedError, CaptchaError) as e:
            notify(f"Rate limited during snipe: {slug}", str(e), level="warn")
            time.sleep(30)
            continue
        except Exception as e:
            print(f"[scheduled_snipe] find error: {e}", flush=True)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        slot, priority = find_best_slot(
            slots, preferred_times, fallback_times, use_fallback=use_fallback
        )

        if slot is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        # Attempt to book
        try:
            book_token = book_client.details(slot)
            result = book_client.book(book_token, slot)
            rid = result.get("reservation_id", "?")
            notify(
                f"BOOKED {slug}",
                f"{target_date} {slot.time.split()[1][:5]} party of {party_size} ({priority})\nID: {rid}",
                level="success",
            )
            os.makedirs("state", exist_ok=True)
            with open("state/booked.json", "a") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "slug": slug,
                            "day": target_date,
                            "party_size": party_size,
                            "match": priority,
                            "provider": provider,
                            "result": result,
                            "source": "scheduled_snipe",
                        }
                    )
                    + "\n"
                )
            sys.exit(0)
        except Exception as e:
            # Slot was taken — keep polling
            print(
                f"[scheduled_snipe] book attempt failed ({type(e).__name__}), continuing",
                flush=True,
            )
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
