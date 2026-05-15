"""SevenRooms API client.

Polling (find) is anonymous — no auth required.
Booking is not yet implemented; requires DevTools capture of the booking flow.

venue_key format:
  The URL slug used in the SevenRooms reservation page, e.g. "catchny" from
  https://www.sevenrooms.com/explore/catchhg/reservations/create/search/?venues=catchny

  To find the slug for a restaurant:
    - If the restaurant has a SevenRooms-hosted page:
        look for the URL pattern sevenrooms.com/explore/{group}/reservations/...?venues={slug}
    - If the restaurant embeds the widget on their own site:
        run: python lookup_venue_sevenrooms.py <restaurant_url>
"""

import requests
from lib.provider_base import Slot, RateLimitedError, BookingNotImplementedError

API_BASE = "https://www.sevenrooms.com"


class SevenRoomsClient:
    def __init__(self, auth_token: str | None = None):
        self.auth_token = auth_token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Safari/605.1.15"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.sevenrooms.com/",
            }
        )

    def _check(self, r: requests.Response) -> requests.Response:
        if r.status_code == 429:
            raise RateLimitedError(f"Rate limited: {r.text[:200]}")
        r.raise_for_status()
        return r

    def find(self, venue_key: str, day: str, party_size: int) -> list[Slot]:
        """Poll availability for a SevenRooms venue.

        Args:
            venue_key: URL slug for the venue (e.g. "catchny")
            day: Date in YYYY-MM-DD format
            party_size: Number of guests

        Returns:
            List of bookable Slot objects (type=="book" and access_persistent_id present).
        """
        params = {
            "venue": venue_key,
            "time_slot": "7:00 PM",      # anchor; halo_size_interval covers full day
            "party_size": party_size,
            "halo_size_interval": 100,    # ~25 hours of 15-min slots each side
            "start_date": day,            # YYYY-MM-DD
            "num_days": 1,
            "channel": "SEVENROOMS_WIDGET",
        }
        r = self.session.get(
            f"{API_BASE}/api-yoa/availability/ng/widget/range",
            params=params,
            timeout=10,
        )
        self._check(r)
        data = r.json()

        slots = []
        availability = data.get("data", {}).get("availability", {})
        # availability = {date_str: [shift, ...]}
        # shift = {shift_category, times: [{type, time_iso, access_persistent_id, public_time_slot_description}]}
        for date_key, shifts in availability.items():
            for shift in shifts:
                if shift.get("is_closed"):
                    continue
                seating_category = shift.get("shift_category", "")
                for t in shift.get("times", []):
                    if t.get("type") != "book":
                        continue
                    access_id = t.get("access_persistent_id")
                    if not access_id:
                        continue
                    slots.append(
                        Slot(
                            provider="sevenrooms",
                            venue_key=venue_key,
                            day=day,
                            time=t["time_iso"],          # "YYYY-MM-DD HH:MM:SS"
                            seating_type=t.get("public_time_slot_description") or seating_category,
                            booking_token=access_id,
                            party_size=party_size,
                            raw=t,
                        )
                    )
        return slots

    def details(self, slot: Slot) -> str:
        """Return booking token for a slot (pass-through for SevenRooms)."""
        return slot.booking_token

    def book(self, book_token: str, slot: Slot) -> dict:
        raise BookingNotImplementedError(
            "SevenRooms booking not yet implemented. "
            "Requires DevTools capture of the booking flow. "
            "Set auto_book: false for SevenRooms restaurants."
        )

    def cancel(self, reservation_id: str, token: str) -> dict:
        raise BookingNotImplementedError(
            "SevenRooms cancellation not yet implemented."
        )
