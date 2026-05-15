#!/usr/bin/env python3
"""Management CLI for ResSniper. Called by Claude Code or directly.

Commands:
  list-watches              Print watch-rules.yaml in human form
  add-watch <slug>          Interactive: add a new restaurant to watch
  remove-watch <slug>       Remove a restaurant from watch-rules.yaml
  pause <slug>              Set auto_book: false
  resume <slug>             Set auto_book: true
  list-bookings [--last N]  Show bookings from state/booked.json
  list-reservations         Call Resy for current reservations
  cancel <reservation_id>   Cancel a reservation (confirms first)
  status                    Watcher process status, last poll, last booking
  lookup-venue <resy_url>             Extract venue_id from a Resy restaurant URL
  lookup-venue-sevenrooms <url>       Find SevenRooms venue_key from a restaurant website
  lookup-payment-id                   Print payment_id from your Resy account
  test-notify                         Send a test macOS notification
"""

import argparse
import json
import os
import subprocess
import sys
import time
import yaml

from lib.auth import load_provider_credentials
from lib.notifier import notify
from lib.providers import get_book_client, resolve_provider, resolve_venue_key
from lib.provider_base import AuthExpiredError

WATCH_RULES = "watch-rules.yaml"
BOOKED_LOG = "state/booked.json"


# ── helpers ──────────────────────────────────────────────────────────────────

def load_rules():
    with open(WATCH_RULES) as f:
        return yaml.safe_load(f)


def save_rules(rules):
    with open(WATCH_RULES, "w") as f:
        yaml.dump(rules, f, default_flow_style=False, sort_keys=False)


def make_client(provider="resy"):
    creds = load_provider_credentials(provider)
    return get_book_client(provider, creds)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_list_watches(_args):
    rules = load_rules()
    restaurants = rules.get("restaurants", {})
    defaults = rules.get("defaults", {})
    if not restaurants:
        print("No restaurants in watch-rules.yaml")
        return
    for slug, rule in restaurants.items():
        auto = "AUTO-BOOK" if rule.get("auto_book") else "notify-only"
        times = rule.get("preferred_times") or ("any" if rule.get("accept_any_time") else "—")
        provider = resolve_provider(rule, defaults)
        venue_key = resolve_venue_key(rule) if ("venue_id" in rule or "venue_key" in rule) else "?"
        print(
            f"  {slug:30s} [{provider:12s}] venue={venue_key:20s}  "
            f"party={rule.get('party_size', 2)}  {auto}  "
            f"poll={rule.get('poll_interval_sec', 60)}s  times={times}"
        )


def cmd_add_watch(args):
    rules = load_rules()
    slug = args.slug
    if slug in rules.get("restaurants", {}):
        print(f"'{slug}' already exists in watch-rules.yaml. Edit it directly or remove first.")
        sys.exit(1)

    provider = input("provider [resy/sevenrooms] (default: resy): ").strip().lower() or "resy"
    if provider not in ("resy", "sevenrooms"):
        print(f"Unknown provider '{provider}'. Must be 'resy' or 'sevenrooms'.")
        sys.exit(1)

    if provider == "resy":
        venue_key_label = "venue_id (numeric)"
        venue_key_field = "venue_id"
    else:
        venue_key_label = "venue_key (URL slug, e.g. lebernardindining)"
        venue_key_field = "venue_key"

    venue_key_raw = input(f"{venue_key_label} for {slug}: ").strip()
    party_size = input("party_size [2]: ").strip() or "2"
    auto_book = input("auto_book? [y/N]: ").strip().lower() == "y"

    if provider == "sevenrooms" and auto_book:
        print("Note: SevenRooms booking is not yet implemented. Setting auto_book: false.")
        auto_book = False

    accept_any = False
    preferred = []
    if auto_book:
        accept_any = input("accept any time? [y/N]: ").strip().lower() == "y"
        if not accept_any:
            raw = input("preferred_times (comma-separated HH:MM, e.g. 19:00,19:30): ")
            preferred = [t.strip() for t in raw.split(",") if t.strip()]
    poll = input("poll_interval_sec [60]: ").strip() or "60"

    entry: dict = {
        "auto_book": auto_book,
        "party_size": int(party_size),
        "poll_interval_sec": int(poll),
    }
    if provider != rules.get("defaults", {}).get("provider", "resy"):
        entry["provider"] = provider
    if provider == "resy":
        entry[venue_key_field] = int(venue_key_raw)
    else:
        entry[venue_key_field] = venue_key_raw
    if accept_any:
        entry["accept_any_time"] = True
    elif preferred:
        entry["preferred_times"] = preferred

    rules.setdefault("restaurants", {})[slug] = entry
    save_rules(rules)
    print(f"Added '{slug}' ({provider}) to watch-rules.yaml")


def cmd_remove_watch(args):
    rules = load_rules()
    slug = args.slug
    if slug not in rules.get("restaurants", {}):
        print(f"'{slug}' not found")
        sys.exit(1)
    confirm = input(f"Remove '{slug}'? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return
    del rules["restaurants"][slug]
    save_rules(rules)
    print(f"Removed '{slug}'")


def cmd_pause(args):
    rules = load_rules()
    slug = args.slug
    if slug not in rules.get("restaurants", {}):
        print(f"'{slug}' not found")
        sys.exit(1)
    rules["restaurants"][slug]["auto_book"] = False
    save_rules(rules)
    print(f"'{slug}' paused (auto_book: false). Watcher will only notify.")


def cmd_resume(args):
    rules = load_rules()
    slug = args.slug
    if slug not in rules.get("restaurants", {}):
        print(f"'{slug}' not found")
        sys.exit(1)
    rules["restaurants"][slug]["auto_book"] = True
    save_rules(rules)
    print(f"'{slug}' resumed (auto_book: true).")


def cmd_list_bookings(args):
    if not os.path.exists(BOOKED_LOG):
        print("No bookings yet.")
        return
    with open(BOOKED_LOG) as f:
        lines = [l.strip() for l in f if l.strip()]
    entries = [json.loads(l) for l in lines]
    if args.last:
        entries = entries[-args.last:]
    for e in entries:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["ts"]))
        rid = (e.get("result") or {}).get("reservation_id", "?")
        src = e.get("source", "cancellation")
        print(
            f"  {ts}  {e['slug']:25s} {e['day']}  "
            f"party={e.get('party_size', 2)}  ({e['match']})  "
            f"id={rid}  [{src}]"
        )


def cmd_list_reservations(_args):
    client = make_client()
    data = client.my_reservations()
    reservations = data.get("reservations", [])
    if not reservations:
        print("No upcoming reservations.")
        return
    for r in reservations:
        venue = r.get("venue", {}).get("name", "?")
        day = r.get("day", "?")
        time_str = r.get("time_slot", r.get("start", "?"))
        rid = r.get("id", "?")
        party = r.get("num_seats", "?")
        print(f"  id={rid}  {venue:30s} {day} {time_str}  party={party}")


def cmd_cancel(args):
    client = make_client()
    rid = args.reservation_id

    # Fetch reservations to find resy_token
    data = client.my_reservations()
    reservations = data.get("reservations", [])
    match = next((r for r in reservations if str(r.get("id")) == str(rid)), None)

    if not match:
        print(f"Reservation id={rid} not found in upcoming reservations.")
        sys.exit(1)

    venue = match.get("venue", {}).get("name", "?")
    day = match.get("day", "?")
    resy_token = match.get("resy_token") or match.get("booking_token")
    if not resy_token:
        print("Could not find resy_token for this reservation. Cannot cancel via API.")
        sys.exit(1)

    print(f"About to cancel: {venue} on {day} (id={rid})")
    confirm = input("Confirm cancel? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    result = client.cancel(rid, resy_token)
    print(f"Cancelled. Response: {result}")


def cmd_status(_args):
    # Check if watcher process is running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "watcher.py"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            pids = result.stdout.strip()
            print(f"Watcher: RUNNING (pid {pids})")
        else:
            print("Watcher: NOT RUNNING")
    except Exception:
        print("Watcher: status unknown")

    # Last poll from seen.json
    seen_path = "state/seen.json"
    if os.path.exists(seen_path):
        mtime = os.path.getmtime(seen_path)
        age = time.time() - mtime
        print(f"Last poll: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))} ({age:.0f}s ago)")
    else:
        print("Last poll: never (no state/seen.json)")

    # Last booking
    if os.path.exists(BOOKED_LOG):
        with open(BOOKED_LOG) as f:
            lines = [l.strip() for l in f if l.strip()]
        if lines:
            last = json.loads(lines[-1])
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(last["ts"]))
            print(f"Last booking: {last['slug']} {last['day']} at {ts}")
        else:
            print("Last booking: none")
    else:
        print("Last booking: none")


def cmd_lookup_venue(args):
    import re
    import urllib.request

    url = args.resy_url
    # Normalize to HTML page URL
    if not url.startswith("http"):
        url = "https://resy.com/cities/" + url

    print(f"Fetching {url} ...")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Try __NEXT_DATA__ JSON blob first
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            # Walk the JSON looking for venue_id or id in venue-related keys
            raw = json.dumps(data)
            ids = re.findall(r'"venue_id"\s*:\s*(\d+)', raw)
            if ids:
                print(f"venue_id: {ids[0]}")
                return
            # fallback: look for id in venue objects
            ids = re.findall(r'"id"\s*:\s*(\d+)', raw)
            if ids:
                print(f"Possible venue ids (first 5): {ids[:5]}")
                return
        except Exception:
            pass

    # Fallback: search raw HTML
    patterns = [
        r'venue_id["\s:=]+(\d+)',
        r'/venues/(\d+)/',
        r'"id"\s*:\s*(\d+)',
    ]
    for pat in patterns:
        ids = re.findall(pat, html)
        if ids:
            print(f"Possible venue_id (pattern '{pat}'): {ids[0]}")
            print(f"  Other candidates: {ids[1:6]}")
            return

    print("Could not extract venue_id from page. Try opening the restaurant page in a browser with DevTools > Network and looking for /4/find?venue_id=...")


def cmd_lookup_payment_id(_args):
    client = make_client()
    data = client.user()
    payment_methods = data.get("payment_methods", []) or data.get("payment_method", [])
    if not payment_methods:
        print("No payment methods found on account.")
        return
    for pm in payment_methods:
        pid = pm.get("id", "?")
        brand = pm.get("brand", pm.get("display", "?"))
        last4 = pm.get("last4", pm.get("last_four", ""))
        print(f"  payment_id: {pid}  ({brand} ...{last4})")


def cmd_lookup_venue_sevenrooms(args):
    """Find the SevenRooms venue_key by visiting a restaurant's website."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "lookup_venue_sevenrooms.py", args.url],
        check=False,
    )
    sys.exit(result.returncode)


def cmd_test_notify(_args):
    notify("Test notification", "ResSniper notifications are working.", level="success")
    print("Notification sent.")


# ── CLI setup ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ResSniper management CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list-watches")

    p = sub.add_parser("add-watch")
    p.add_argument("slug")

    p = sub.add_parser("remove-watch")
    p.add_argument("slug")

    p = sub.add_parser("pause")
    p.add_argument("slug")

    p = sub.add_parser("resume")
    p.add_argument("slug")

    p = sub.add_parser("list-bookings")
    p.add_argument("--last", type=int, default=None)

    sub.add_parser("list-reservations")

    p = sub.add_parser("cancel")
    p.add_argument("reservation_id")

    sub.add_parser("status")

    p = sub.add_parser("lookup-venue")
    p.add_argument("resy_url")

    p = sub.add_parser("lookup-venue-sevenrooms")
    p.add_argument("url", help="Restaurant website URL (not the SevenRooms URL)")

    sub.add_parser("lookup-payment-id")
    sub.add_parser("test-notify")

    args = parser.parse_args()

    commands = {
        "list-watches": cmd_list_watches,
        "add-watch": cmd_add_watch,
        "remove-watch": cmd_remove_watch,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "list-bookings": cmd_list_bookings,
        "list-reservations": cmd_list_reservations,
        "cancel": cmd_cancel,
        "status": cmd_status,
        "lookup-venue": cmd_lookup_venue,
        "lookup-venue-sevenrooms": cmd_lookup_venue_sevenrooms,
        "lookup-payment-id": cmd_lookup_payment_id,
        "test-notify": cmd_test_notify,
    }

    if not args.command or args.command not in commands:
        parser.print_help()
        sys.exit(1)

    commands[args.command](args)


if __name__ == "__main__":
    main()
