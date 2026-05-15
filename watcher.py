#!/usr/bin/env python3
"""Cancellation watching daemon. Runs continuously, polls watched restaurants,
fires snipe.py as a subprocess when a matching slot is found."""

import json
import os
import random
import subprocess
import sys
import time
import yaml
from datetime import datetime, timedelta

from lib.provider_base import AuthExpiredError, CaptchaError, RateLimitedError
from lib.providers import get_poll_client, resolve_venue_key, resolve_provider
from lib.notifier import notify

STATE_FILE = "state/seen.json"
DATES_PER_SWEEP = 7
TICK_INTERVAL = 5  # outer loop tick in seconds


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(s):
    os.makedirs("state", exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, STATE_FILE)


def prune_seen(seen):
    cutoff = time.time() - 86400
    return {
        k: v
        for k, v in seen.items()
        if isinstance(v, (int, float)) and v > cutoff
    }


def dates_in_window(rule, offset, count):
    now = datetime.now()
    min_d = (now + timedelta(hours=rule.get("min_hours_out", 24))).date()
    max_d = (now + timedelta(days=rule.get("max_days_out", 30))).date()
    span = max((max_d - min_d).days + 1, 1)
    out = []
    for i in range(count):
        d = min_d + timedelta(days=(offset + i) % span)
        out.append(d.strftime("%Y-%m-%d"))
    return out


def time_matches(slot_time_str, rule):
    if rule.get("accept_any_time"):
        hhmm = slot_time_str.split(" ")[1][:5]
        return ("any", hhmm)
    hhmm = slot_time_str.split(" ")[1][:5]
    if hhmm in rule.get("preferred_times", []):
        return ("preferred", hhmm)
    if hhmm in rule.get("fallback_times", []):
        return ("fallback", hhmm)
    return None


def current_interval(rule):
    hour = datetime.now().hour
    if hour in rule.get("hot_hours", []):
        return rule.get("hot_poll_interval_sec", rule.get("poll_interval_sec", 60))
    return rule.get("poll_interval_sec", 60)


def check_restaurant(client, slug, rule, seen, sweep_offset, venue_key):
    matches = []
    for day in dates_in_window(rule, sweep_offset, DATES_PER_SWEEP):
        try:
            slots = client.find(venue_key, day, rule.get("party_size", 2))
        except (AuthExpiredError, RateLimitedError, CaptchaError):
            raise
        except Exception as e:
            print(f"[{slug}] {day}: {e}", flush=True)
            continue
        time.sleep(0.4 + random.random() * 0.3)
        for slot in slots:
            key = f"slot:{slug}:{day}:{slot.time}"
            if key in seen:
                continue
            m = time_matches(slot.time, rule)
            if not m:
                continue
            seen[key] = time.time()
            matches.append((slot, day, m))
    return matches


def main():
    with open("watch-rules.yaml") as f:
        config = yaml.safe_load(f)

    restaurants = config["restaurants"]
    defaults = config.get("defaults", {})
    sweep_offsets = {slug: 0 for slug in restaurants}
    backoff_until = 0
    backoff_count = 0
    backoff_window_start = time.time()

    # One poll client per distinct provider
    poll_clients: dict = {}

    def get_client(provider: str):
        if provider not in poll_clients:
            poll_clients[provider] = get_poll_client(provider)
        return poll_clients[provider]

    notify(
        "ResSniper watcher started",
        f"Watching {len(restaurants)} restaurants: {', '.join(restaurants)}",
    )

    while True:
        now = time.time()

        if now < backoff_until:
            time.sleep(TICK_INTERVAL)
            continue

        # Reset backoff counter if window has passed
        if now - backoff_window_start > 7200:
            backoff_count = 0
            backoff_window_start = now

        seen = prune_seen(load_state())

        for slug, rule in restaurants.items():
            interval = current_interval(rule)
            last_key = f"_last:{slug}"
            if seen.get(last_key, 0) > now - interval:
                continue
            seen[last_key] = now

            provider = resolve_provider(rule, defaults)
            venue_key = resolve_venue_key(rule)
            client = get_client(provider)

            try:
                matches = check_restaurant(
                    client, slug, rule, seen, sweep_offsets[slug], venue_key
                )
            except AuthExpiredError:
                notify("Auth expired", "Run: python refresh_auth.py", level="error")
                save_state(seen)
                sys.exit(0)  # clean exit; systemd won't restart on exit code 0
            except (RateLimitedError, CaptchaError) as e:
                backoff_count += 1
                if backoff_count >= 3:
                    notify(
                        "Watcher stopping",
                        "3 backoffs in 2h. Restart manually after investigating.",
                        level="error",
                    )
                    save_state(seen)
                    sys.exit(1)
                elif backoff_count == 2:
                    delay = 3600
                    notify(
                        "Backing off 1h (2nd backoff)",
                        str(e),
                        level="warn",
                    )
                else:
                    delay = 600
                    notify("Backing off 10min", str(e), level="warn")
                backoff_until = time.time() + delay
                save_state(seen)
                break

            sweep_offsets[slug] = sweep_offsets[slug] + DATES_PER_SWEEP

            for slot, day, match in matches:
                summary = f"{slug} | {day} {match[1]} ({match[0]})"
                if rule.get("auto_book"):
                    notify("Sniping", summary, level="info")
                    subprocess.Popen(
                        [
                            sys.executable,
                            "snipe.py",
                            "--provider", provider,
                            "--venue-key", venue_key,
                            "--booking-token", slot.booking_token,
                            "--day", slot.day,
                            "--party-size", str(slot.party_size),
                            "--match-kind", match[0],
                            "--seating-type", slot.seating_type,
                            "--time", slot.time,
                            slug,
                        ]
                    )
                else:
                    notify("Opening found (manual booking)", summary, level="info")

        save_state(seen)
        time.sleep(TICK_INTERVAL)


if __name__ == "__main__":
    main()
