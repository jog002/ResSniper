# Resy Sniper Handover

This document describes a personal Resy reservation sniper to be built and run on Oscar's homelab. The system polls Resy's internal API for openings at watched restaurants and books matches automatically. It is for Oscar's personal account, on his behalf, with his credentials. It is not a multi-user service and is not for resale.

Build it as described. Ask before deviating on anything that affects request volume to Resy or that touches credentials.

## Goals

Two booking modes coexist on the same infrastructure.

**Scheduled drops.** Many top NYC restaurants release a fixed inventory at a fixed time (e.g. 9:00 AM ET, 30 days out). The sniper sleeps until just before drop, polls hard for a few seconds, and books the best matching time per a priority list.

**Cancellation watching.** A continuous polling loop watches selected restaurants for cancellations that reappear as available slots. When an opening matches the rules for that restaurant, the sniper fires immediately. For some restaurants (4 Charles Prime Rib in particular) any opening 24+ hours out should be auto-booked regardless of time. For others, only specific time windows trigger auto-booking.

Both modes share the same Resy API client, the same auth, the same notifier, and the same booking pipeline.

## Non-goals

- No web UI. Configuration is YAML files. Querying state is via Claude Code over Discord.
- No support for other people's accounts.
- No CAPTCHA solving. If Resy throws CAPTCHA, log it, notify Oscar, and back off.
- No payment method entry. Payment ID is read from credentials, never modified.

## Risk acknowledgement

Resy's terms of service likely prohibit automated access. The mitigations are: polite request rates, residential IP (Oscar's home network), single account, no credential sharing, immediate backoff on any signal of detection (419 errors, CAPTCHA, unusual response codes). If the account is flagged, Oscar accepts the risk. Do not implement evasion techniques beyond standard browser-like headers.

## Architecture

```
resy-sniper/
├── credentials.yaml              # api_key, auth_token, payment_id (gitignored)
├── watch-rules.yaml              # restaurants to monitor + booking rules
├── scheduled-drops.yaml          # known scheduled drop times per restaurant
├── state/
│   ├── seen.json                 # dedup of openings already processed
│   └── booked.json               # log of successful bookings
├── lib/
│   ├── resy_client.py            # Resy API wrapper
│   ├── notifier.py               # Discord webhook notifier
│   └── auth.py                   # auth refresh helpers
├── watcher.py                    # the cancellation polling daemon
├── snipe.py                      # one-shot booker, called by watcher
├── scheduled_snipe.py            # scheduled drop sniper, called by cron
├── refresh_auth.py               # Playwright-based token refresh
├── manage.py                     # CLI for Claude Code to call (list, cancel, add)
├── systemd/
│   └── resy-watcher.service      # systemd unit for the watcher daemon
└── logs/
```

Three runtime processes:

1. **`watcher.py`** runs continuously as a systemd service. Polls Resy for cancellations on watched restaurants. Fires `snipe.py` as a subprocess when a match is found.
2. **`scheduled_snipe.py`** is launched by cron at known drop times for specific (restaurant, date) pairs.
3. **`refresh_auth.py`** is run manually (or weekly via cron) when auth tokens expire. Uses Playwright with a persistent profile to log in and scrape fresh tokens.

The notifier is **synchronous and direct** — a Python function that POSTs to a Discord webhook. No Claude Code in the hot path. Claude Code over Discord is used separately as a management interface (see "Management interface" below).

## Resy API reference

Base URL: `https://api.resy.com`

The booking flow is three sequential calls. Auth uses two values: `api_key` (a hardcoded public value used by the Resy app, fine to ship as a default) and `auth_token` (Oscar's session token, secret).

### Headers (all requests)

```
Authorization: ResyAPI api_key="<api_key>"
X-Resy-Auth-Token: <auth_token>
X-Resy-Universal-Auth: <auth_token>
Origin: https://resy.com
Referer: https://resy.com/
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15
Accept: application/json, text/plain, */*
```

`Content-Type: application/x-www-form-urlencoded` for POSTs that send a body.

A 419 status code means the auth token expired. Trap it as a specific exception so the watcher can notify and stop, rather than spinning.

### Endpoints

**`GET /4/find`** — availability check. Cheap, fast, the only call you poll.

```
GET /4/find?lat=0&long=0&day=2026-05-15&party_size=2&venue_id=12345
```

Response contains `results.venues[].slots[]`. Each slot has:
- `config.token` — the config_token, needed for the next call
- `date.start` — string like `"2026-05-15 19:00:00"`
- `config.type` — e.g. `"Dining Room"`, `"Bar"`, `"Counter"`

**`POST /3/details`** — get a `book_token`. Briefly holds the slot.

```
POST /3/details
Body: config_id=<config_token>&day=2026-05-15&party_size=2
```

Response contains `book_token.value`. This token is short-lived (~1-2 minutes).

**`POST /3/book`** — final commit.

```
POST /3/book
Body: book_token=<book_token>&struct_payment_method={"id":<payment_id>}&source_id=resy.com-venue-details
```

Response on success contains a `reservation_id` and `resy_token`. Save both.

**`GET /2/user`** — returns user profile including `payment_method_id`. Run once during setup to populate `credentials.yaml`.

**`GET /3/user/reservations`** — current and past reservations. Used by the management interface.

**`DELETE /3/cancel`** — cancel a reservation. Used by the management interface only, never by the watcher.

### Looking up venue IDs

The `venue_id` for a restaurant is in the URL of an image on its Resy page, and also appears as a query parameter in `/find` calls when you visit the venue page in a browser with devtools open. Document the lookup procedure in the README. For the initial config, use:

- 4 Charles Prime Rib: look up
- Carbone: 6194 (verify)
- Don Angie: 5286 (verify)

Build a one-off script `lookup_venue.py` that takes a Resy URL slug and prints the venue_id by hitting the venue's HTML page and parsing.

## Configuration files

### `credentials.yaml`

```yaml
api_key: "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"   # public app key, fine as default
auth_token: "<extracted from browser network tab after login>"
payment_id: 12345678                            # from GET /2/user
account_email: "oscar@example.com"              # for refresh_auth.py
```

Gitignored. Mode 600. Loaded once per process.

### `watch-rules.yaml`

```yaml
defaults:
  party_size: 2
  poll_interval_sec: 60
  notify_on_book: true
  notify_on_failure: true

restaurants:
  4-charles-prime-rib:
    venue_id: 893
    auto_book: true
    party_size: 2
    accept_any_time: true
    min_hours_out: 24
    max_days_out: 60
    poll_interval_sec: 20
    hot_hours: [14, 15, 16, 17, 18]   # 2-6 PM ET, poll faster
    hot_poll_interval_sec: 10

  carbone:
    venue_id: 6194
    auto_book: true
    party_size: 2
    preferred_times: ["19:00", "19:15", "19:30", "18:45", "20:00"]
    fallback_times: ["18:30", "18:45", "20:15", "20:30"]
    min_hours_out: 48
    max_days_out: 30
    poll_interval_sec: 60

  don-angie:
    venue_id: 5286
    auto_book: false
    notify: true
    party_size: 2
    poll_interval_sec: 90
```

### `scheduled-drops.yaml`

```yaml
# Known scheduled drops. Cron reads this to schedule scheduled_snipe.py runs.
# A drop is "30 days out at 9 AM ET" - compute target date dynamically.
drops:
  carbone:
    venue_id: 6194
    drop_time_et: "09:00"
    days_in_advance: 30          # restaurant releases 30 days out
    party_size: 2
    preferred_times: ["19:00", "19:15", "19:30", "18:45", "20:00"]
    fallback_times: ["18:30", "20:15"]
    schedule_dates: weekdays     # which target weekdays to attempt
```

A separate script `update_cron.py` reads this file and writes the cron entries needed (it computes "today + days_in_advance = target date", schedules for tomorrow's 8:59 AM, etc).

## The Resy client

```python
# lib/resy_client.py
import requests, json
from urllib.parse import urlencode

API_BASE = "https://api.resy.com"
PUBLIC_API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"

class AuthExpiredError(Exception): pass
class CaptchaError(Exception): pass
class RateLimitedError(Exception): pass

class ResyClient:
    def __init__(self, auth_token, payment_id, api_key=PUBLIC_API_KEY):
        self.auth_token = auth_token
        self.payment_id = payment_id
        self.api_key = api_key
        self.session = requests.Session()

    def _headers(self, content_type=None):
        h = {
            "Authorization": f'ResyAPI api_key="{self.api_key}"',
            "X-Resy-Auth-Token": self.auth_token,
            "X-Resy-Universal-Auth": self.auth_token,
            "Origin": "https://resy.com",
            "Referer": "https://resy.com/",
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                           "Version/17.0 Safari/605.1.15"),
            "Accept": "application/json, text/plain, */*",
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _check(self, r):
        if r.status_code == 419:
            raise AuthExpiredError(f"Auth expired: {r.text[:200]}")
        if r.status_code == 429:
            raise RateLimitedError(f"Rate limited: {r.text[:200]}")
        if "captcha" in r.text.lower()[:500]:
            raise CaptchaError("Captcha challenge detected")
        r.raise_for_status()
        return r

    def find(self, venue_id, day, party_size):
        params = {"lat": 0, "long": 0, "day": day,
                  "party_size": party_size, "venue_id": venue_id}
        r = self.session.get(f"{API_BASE}/4/find", params=params,
                              headers=self._headers(), timeout=10)
        self._check(r)
        data = r.json()
        slots = []
        for v in data.get("results", {}).get("venues", []):
            for slot in v.get("slots", []):
                slots.append({
                    "config_token": slot["config"]["token"],
                    "time": slot["date"]["start"],
                    "type": slot["config"].get("type", "Dining Room"),
                })
        return slots

    def details(self, config_token, day, party_size):
        body = urlencode({"config_id": config_token, "day": day,
                          "party_size": party_size})
        r = self.session.post(
            f"{API_BASE}/3/details", data=body,
            headers=self._headers("application/x-www-form-urlencoded"),
            timeout=10)
        self._check(r)
        return r.json()["book_token"]["value"]

    def book(self, book_token):
        body = urlencode({
            "book_token": book_token,
            "struct_payment_method": json.dumps({"id": self.payment_id}),
            "source_id": "resy.com-venue-details",
        })
        r = self.session.post(
            f"{API_BASE}/3/book", data=body,
            headers=self._headers("application/x-www-form-urlencoded"),
            timeout=15)
        self._check(r)
        return r.json()

    def my_reservations(self):
        r = self.session.get(f"{API_BASE}/3/user/reservations",
                              headers=self._headers(), timeout=10)
        self._check(r)
        return r.json()

    def user(self):
        r = self.session.get(f"{API_BASE}/2/user",
                              headers=self._headers(), timeout=10)
        self._check(r)
        return r.json()
```

## The notifier (Discord webhook)

```python
# lib/notifier.py
import os, requests, time

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def notify(title, message, level="info"):
    """Post a notification to Discord. level: info, success, warn, error."""
    color = {"info": 3447003, "success": 3066993,
             "warn": 16776960, "error": 15158332}[level]
    payload = {
        "embeds": [{
            "title": title,
            "description": message,
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }]
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        # Notifier failures must not crash the caller.
        print(f"[notify] failed: {e}")
```

The Discord webhook URL is loaded from environment, not committed. Set it in the systemd unit's `Environment=` directive.

For high-priority alerts (booked successfully, auth expired) consider also pinging a role or using a separate webhook in a channel that's not muted on Oscar's phone.

## The watcher

The watcher's job: continuously poll watched restaurants, dedupe openings already seen, fire snipes for matching slots.

Key design decisions to preserve:

- **Single global loop with per-restaurant gating.** Outer loop ticks every 5 seconds. Each restaurant maintains its own `last_polled_at` and only fires `/find` calls when its `poll_interval_sec` has elapsed. This way different restaurants can have very different cadences without juggling threads.
- **Date sweeping is staggered.** Don't check all 60 days every cycle. Each cycle, check 5-10 dates from a rotating window. Full coverage of a 60-day window takes 2-3 minutes but per-second request rate stays sane.
- **Hot hours.** For restaurants that flag `hot_hours`, use `hot_poll_interval_sec` between those hours. 4 Charles cancellations cluster 2-6 PM ET, so poll faster then.
- **Dedup with TTL.** `state/seen.json` records every (restaurant, date, time) seen, with a timestamp. Entries older than 24 hours are pruned so a slot that reappears later still triggers.
- **Subprocess snipes.** When a match fires, launch `snipe.py` as a subprocess and continue. Don't block the watcher loop on the booking call. The watcher marks the slot as seen *before* spawning, so a duplicate from the next cycle can't fire on the same slot.
- **Backoff on signal.** On `RateLimitedError` or `CaptchaError`, sleep 10 minutes and notify. On `AuthExpiredError`, notify and exit (systemd will not restart on clean exit; require manual `refresh_auth.py`).
- **Random jitter.** Add 0-300ms of jitter between requests in a sweep. Real browsers are bursty but never perfectly periodic.

```python
# watcher.py (skeleton, fill in details)
import json, os, random, subprocess, time, yaml
from datetime import datetime, timedelta
from lib.resy_client import ResyClient, AuthExpiredError, CaptchaError, RateLimitedError
from lib.notifier import notify

STATE_FILE = "state/seen.json"
DATES_PER_SWEEP = 7   # check N dates per cycle, rotate through window

def load_state():
    if not os.path.exists(STATE_FILE): return {}
    with open(STATE_FILE) as f: return json.load(f)

def save_state(s):
    os.makedirs("state", exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f: json.dump(s, f)
    os.replace(tmp, STATE_FILE)

def prune_seen(seen):
    cutoff = time.time() - 86400
    return {k: v for k, v in seen.items() if isinstance(v, (int, float)) and v > cutoff}

def dates_in_window(rule, offset, count):
    now = datetime.now()
    min_d = (now + timedelta(hours=rule.get("min_hours_out", 24))).date()
    max_d = (now + timedelta(days=rule.get("max_days_out", 30))).date()
    span = (max_d - min_d).days + 1
    out = []
    for i in range(count):
        d = min_d + timedelta(days=(offset + i) % span)
        out.append(d.strftime("%Y-%m-%d"))
    return out

def time_matches(slot_time_str, rule):
    if rule.get("accept_any_time"):
        return ("any", slot_time_str.split(" ")[1][:5])
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

def check_restaurant(client, slug, rule, seen, sweep_offset):
    matches = []
    for day in dates_in_window(rule, sweep_offset, DATES_PER_SWEEP):
        try:
            slots = client.find(rule["venue_id"], day, rule.get("party_size", 2))
        except AuthExpiredError:
            raise
        except (RateLimitedError, CaptchaError):
            raise
        except Exception as e:
            print(f"[{slug}] {day}: {e}")
            continue
        time.sleep(0.4 + random.random() * 0.3)
        for slot in slots:
            key = f"slot:{slug}:{day}:{slot['time']}"
            if key in seen: continue
            m = time_matches(slot["time"], rule)
            if not m: continue
            seen[key] = time.time()
            matches.append((slot, day, m))
    return matches

def main():
    with open("watch-rules.yaml") as f: config = yaml.safe_load(f)
    with open("credentials.yaml") as f: creds = yaml.safe_load(f)
    client = ResyClient(creds["auth_token"], creds["payment_id"],
                        creds.get("api_key"))
    sweep_offsets = {slug: 0 for slug in config["restaurants"]}
    notify("Resy watcher started",
           f"Watching {len(config['restaurants'])} restaurants")
    backoff_until = 0

    while True:
        if time.time() < backoff_until:
            time.sleep(5); continue
        seen = prune_seen(load_state())
        for slug, rule in config["restaurants"].items():
            interval = current_interval(rule)
            last_key = f"_last:{slug}"
            if seen.get(last_key, 0) > time.time() - interval: continue
            seen[last_key] = time.time()
            try:
                matches = check_restaurant(client, slug, rule, seen,
                                            sweep_offsets[slug])
            except AuthExpiredError:
                notify("Auth expired", "Run refresh_auth.py", level="error")
                save_state(seen); return
            except (RateLimitedError, CaptchaError) as e:
                notify("Backing off 10min", str(e), level="warn")
                backoff_until = time.time() + 600
                save_state(seen); break
            sweep_offsets[slug] += DATES_PER_SWEEP
            for slot, day, match in matches:
                summary = f"{slug} {day} {match[1]} ({match[0]})"
                if rule.get("auto_book"):
                    notify("Sniping", summary, level="info")
                    subprocess.Popen(["python", "snipe.py", slug,
                                      slot["config_token"], day,
                                      str(rule.get("party_size", 2)), match[0]])
                else:
                    notify("Opening (manual)", summary, level="info")
        save_state(seen)
        time.sleep(5)

if __name__ == "__main__":
    main()
```

## The sniper (cancellation flow)

```python
# snipe.py
import sys, os, time, json, yaml
from lib.resy_client import ResyClient
from lib.notifier import notify

slug, config_token, day, party_size, match_kind = sys.argv[1:6]
party_size = int(party_size)

with open("credentials.yaml") as f: creds = yaml.safe_load(f)
client = ResyClient(creds["auth_token"], creds["payment_id"], creds.get("api_key"))

t0 = time.time()
try:
    book_token = client.details(config_token, day, party_size)
    result = client.book(book_token)
    elapsed = time.time() - t0
    rid = result.get("reservation_id") or result.get("resy_token", "?")
    notify(f"BOOKED {slug}",
           f"{day} party of {party_size} ({match_kind}) in {elapsed:.1f}s\nID: {rid}",
           level="success")
    os.makedirs("state", exist_ok=True)
    with open("state/booked.json", "a") as f:
        f.write(json.dumps({"ts": time.time(), "slug": slug, "day": day,
                            "match": match_kind, "result": result}) + "\n")
except Exception as e:
    notify(f"FAILED {slug}", f"{day} {party_size}p: {type(e).__name__}: {e}",
           level="error")
    sys.exit(1)
```

## The scheduled drop sniper

`scheduled_snipe.py` is similar to `snipe.py` but waits until drop time, then aggressively polls a single (restaurant, date) for inventory, and books per a priority list.

Behavior:
- Read target from CLI args: slug, target_date, drop_timestamp
- Sleep until 30 seconds before drop_timestamp
- From -5 seconds onward, poll `/find` every 500ms
- On first slot match against `preferred_times`, attempt `/details` + `/book`
- If `/details` fails (slot taken), continue polling and try the next preferred time
- If 60 seconds pass without any preferred slot, fall through to `fallback_times`
- After 5 minutes total elapsed, give up and notify
- Notify on success or failure regardless

`update_cron.py` reads `scheduled-drops.yaml` and writes a `crontab` that schedules `scheduled_snipe.py` runs based on `days_in_advance` and `drop_time_et`. Run `update_cron.py` daily at 1 AM via cron itself.

## Auth refresh

`refresh_auth.py` uses Playwright with a persistent profile to log into Resy and scrape fresh tokens.

Procedure:
1. Launch Chromium with `user_data_dir=./scripts/playwright-state` (cookies persist between runs).
2. Navigate to `https://resy.com`.
3. If not logged in, prompt for manual login via terminal (Oscar enters credentials and 2FA in the browser window). On subsequent runs, the persisted session usually still works.
4. After confirming login, navigate to a restaurant page and trigger a `/find` call by clicking the date picker.
5. Capture the `Authorization` and `X-Resy-Auth-Token` headers from the network log.
6. Update `credentials.yaml` (preserving file mode 600).
7. Send a notify ping that auth was refreshed.

This is a manual run when the watcher reports `AuthExpiredError`. Optionally, schedule it weekly via cron with `--headless --skip-if-fresh` flags that exit early if the current token is less than 7 days old.

## Management interface

The watcher has no user-facing UI. Oscar manages it via Claude Code over Discord. `manage.py` exposes a CLI that Claude Code calls.

Commands to implement:

```
manage.py list-watches              # print watch-rules.yaml in human form
manage.py add-watch <slug>          # interactive: prompts for venue_id, rules
manage.py remove-watch <slug>
manage.py pause <slug>              # set auto_book: false without removing
manage.py resume <slug>
manage.py list-bookings [--last N]  # read state/booked.json
manage.py list-reservations         # call client.my_reservations()
manage.py cancel <reservation_id>   # confirms, then DELETE /3/cancel
manage.py status                    # is watcher running, last poll, last book
manage.py lookup-venue <resy_url>   # extract venue_id from a Resy URL
manage.py test-notify               # send a Discord test ping
```

Each command is a thin function. Claude Code can be told (via its Discord integration) "list my upcoming reservations" and it runs `python manage.py list-reservations` over SSH to the homelab box, parses output, replies in Discord.

The split: Discord webhook for time-critical event notifications (programmatic, fast). Claude Code over Discord for queries and configuration changes (interactive, slow, smart).

## Systemd unit

```ini
# systemd/resy-watcher.service
[Unit]
Description=Resy cancellation watcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=oscar
WorkingDirectory=/home/oscar/resy-sniper
Environment="DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/..."
ExecStart=/home/oscar/resy-sniper/.venv/bin/python watcher.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/home/oscar/resy-sniper/logs/watcher.log
StandardError=append:/home/oscar/resy-sniper/logs/watcher.err

[Install]
WantedBy=multi-user.target
```

`Restart=on-failure` not `Restart=always` so a clean exit on `AuthExpiredError` doesn't loop.

## Polling and rate limit guidance

These rates are sustainable from a residential IP based on community reports. Do not exceed them without testing carefully.

- Per-restaurant `/find` call: minimum 10 seconds between calls. 20-60s is normal.
- Sleep 0.4-0.7s between consecutive `/find` calls in a date sweep (random jitter).
- Total request volume budget: aim for under 1 request/second sustained across all restaurants.
- On `429` or CAPTCHA: 10-minute backoff, then resume. Two backoffs in 30 minutes: 1-hour backoff and notify.
- Three backoffs in 2 hours: stop the watcher entirely and notify.

These are guardrails, not features. If they trip frequently, the rates are too aggressive — adjust the YAML, don't disable the guardrails.

## Setup steps

1. `git init` the project. Add `.gitignore` covering `credentials.yaml`, `state/`, `logs/`, `scripts/playwright-state/`, `.venv/`.
2. Python 3.11+ in `.venv`. `pip install requests pyyaml playwright` and `playwright install chromium`.
3. Manually log in once via `refresh_auth.py` to populate `credentials.yaml`.
4. Run `python manage.py test-notify` to confirm Discord webhook works.
5. Run `python manage.py lookup-venue https://resy.com/cities/ny/4-charles-prime-rib` to populate the first watch rule.
6. Edit `watch-rules.yaml` with desired restaurants.
7. Run `python watcher.py` in foreground to confirm behavior.
8. Install systemd unit, enable, start.
9. Tail logs for a day and tune intervals.

## Things to confirm with Oscar before building

- Discord webhook URL (Oscar will provide).
- Whether to also implement the scheduled drop sniper in v1 or v2 (it's parallel work, not a dependency).
- Whether to require explicit confirmation in Discord before any auto-book fires for the first 7 days (safety net while tuning).
- Default `min_hours_out` for 4 Charles is 24 in the example config — confirm this matches Oscar's preference.

## Out of scope (for now)

- Multi-account support
- Web UI
- CAPTCHA solving
- Calendar integration (auto-add bookings to Google Calendar) — easy v2 add via the existing Discord notifier hooks
- Smart conflict detection (don't book if I already have a reservation that night) — useful v2
- Auth token auto-refresh (currently manual on expiry)

## File deliverables checklist

- [ ] `lib/resy_client.py`
- [ ] `lib/notifier.py`
- [ ] `lib/auth.py`
- [ ] `watcher.py`
- [ ] `snipe.py`
- [ ] `scheduled_snipe.py`
- [ ] `refresh_auth.py`
- [ ] `manage.py`
- [ ] `update_cron.py`
- [ ] `lookup_venue.py`
- [ ] `watch-rules.yaml` (with starter entries)
- [ ] `scheduled-drops.yaml` (empty stub)
- [ ] `credentials.yaml.example`
- [ ] `systemd/resy-watcher.service`
- [ ] `.gitignore`
- [ ] `README.md` (setup, ops, troubleshooting)
- [ ] `requirements.txt` or `pyproject.toml`
