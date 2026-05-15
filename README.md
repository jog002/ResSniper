# ResSniper

Personal Resy reservation sniper for Oscar's homelab. Watches for cancellations and scheduled inventory drops, books automatically where configured.

## Setup

```bash
# 1. Python env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. Credentials
cp credentials.yaml.example credentials.yaml
chmod 600 credentials.yaml
# Fill in account_email, then get your auth token:
python refresh_auth.py               # opens a browser; log in manually if prompted
# Paste the token into credentials.yaml, then:
python manage.py lookup-payment-id   # prints your payment_id
# Add payment_id to credentials.yaml

# 3. Verify notifications
python manage.py test-notify

# 4. Look up venue IDs if needed
python manage.py lookup-venue https://resy.com/cities/ny/4-charles-prime-rib

# 5. Edit watch-rules.yaml with your restaurants

# 6. Run watcher in foreground to confirm
python watcher.py

# 7. Deploy via launchd (Mac mini)
mkdir -p logs
# Edit launchd/com.oscargiller.resy-sniper.plist — update paths to match your install location
cp launchd/com.oscargiller.resy-sniper.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.oscargiller.resy-sniper.plist
```

To stop/start/restart:
```bash
launchctl unload ~/Library/LaunchAgents/com.oscargiller.resy-sniper.plist
launchctl load   ~/Library/LaunchAgents/com.oscargiller.resy-sniper.plist
```

## Getting your auth token manually

1. Open Chrome DevTools > Network
2. Go to any restaurant page on resy.com and click the date picker
3. Find the `/4/find` request, look at Request Headers
4. Copy `X-Resy-Auth-Token` value into `credentials.yaml`

Tokens expire periodically. When they do, the watcher notifies you and exits cleanly (no restart loop). Run `python refresh_auth.py` to get a fresh token.

## Watch rules

`watch-rules.yaml` controls which restaurants are watched and how:

- `auto_book: true` — snipe fires automatically
- `auto_book: false` — notification only, you book manually
- `accept_any_time: true` — book any slot (4 Charles mode)
- `preferred_times` / `fallback_times` — ranked list of HH:MM targets
- `hot_hours` — hours (24h ET) where poll cadence increases
- `min_hours_out` / `max_days_out` — booking window

## Scheduled drops

`scheduled-drops.yaml` defines restaurants that release inventory at a fixed time. `update_cron.py` writes cron entries for these. Run it once to install, then it self-updates daily at 1 AM.

```bash
python update_cron.py
```

## Management CLI

```bash
python manage.py list-watches
python manage.py status
python manage.py list-bookings --last 10
python manage.py list-reservations
python manage.py pause carbone
python manage.py resume carbone
python manage.py cancel <reservation_id>
python manage.py add-watch <slug>
python manage.py remove-watch <slug>
```

## Rate limits

Sustained rate is kept under 1 req/sec across all restaurants. On 429 or CAPTCHA: 10-min backoff. Two backoffs → 1-hour backoff. Three backoffs in 2 hours → watcher stops and notifies. Adjust `poll_interval_sec` in `watch-rules.yaml` if you're hitting limits frequently.

## File layout

```
credentials.yaml          # gitignored, mode 600
watch-rules.yaml          # restaurants + booking rules
scheduled-drops.yaml      # known drop times
state/seen.json           # dedup cache (24h TTL)
state/booked.json         # booking log (append-only)
logs/                     # watcher stdout/stderr (launchd)
launchd/                  # macOS LaunchAgent plist
lib/
  provider_base.py        # Slot dataclass + ReservationProvider protocol
  providers.py            # provider factory + venue/provider resolution
  resy_client.py          # Resy API client
  auth.py                 # credential loading/saving
  notifier.py             # macOS notifications
watcher.py                # cancellation polling daemon
snipe.py                  # one-shot booker (subprocess)
scheduled_snipe.py        # scheduled drop sniper
refresh_auth.py           # Playwright token refresh
manage.py                 # CLI
update_cron.py            # writes cron entries for drops
lookup_venue.py           # extract venue_id from Resy URL
```
