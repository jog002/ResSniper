import requests
import json
from urllib.parse import urlencode

from lib.provider_base import Slot

# Re-export canonical exceptions for backward compat
from lib.provider_base import AuthExpiredError, CaptchaError, RateLimitedError  # noqa: F401

API_BASE = "https://api.resy.com"
PUBLIC_API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"


class ResyClient:
    def __init__(self, auth_token=None, payment_id=None, api_key=PUBLIC_API_KEY):
        self.auth_token = auth_token
        self.payment_id = payment_id
        self.api_key = api_key
        self.session = requests.Session()

    @classmethod
    def poll_only(cls, api_key=PUBLIC_API_KEY):
        """Client for /4/find polling only — no user account credentials needed."""
        return cls(auth_token=None, payment_id=None, api_key=api_key)

    def _headers(self, content_type=None):
        h = {
            "Authorization": f'ResyAPI api_key="{self.api_key}"',
            "Origin": "https://resy.com",
            "Referer": "https://resy.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Safari/605.1.15"
            ),
            "Accept": "application/json, text/plain, */*",
        }
        if self.auth_token:
            h["X-Resy-Auth-Token"] = self.auth_token
            h["X-Resy-Universal-Auth"] = self.auth_token
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

    def find(self, venue_key: str, day: str, party_size: int) -> list[Slot]:
        """Poll availability. venue_key is str(venue_id) for Resy."""
        venue_id = int(venue_key)
        params = {
            "lat": 0,
            "long": 0,
            "day": day,
            "party_size": party_size,
            "venue_id": venue_id,
        }
        r = self.session.get(
            f"{API_BASE}/4/find", params=params, headers=self._headers(), timeout=10
        )
        self._check(r)
        data = r.json()
        slots = []
        for v in data.get("results", {}).get("venues", []):
            for slot in v.get("slots", []):
                slots.append(
                    Slot(
                        provider="resy",
                        venue_key=venue_key,
                        day=day,
                        time=slot["date"]["start"],
                        seating_type=slot["config"].get("type", "Dining Room"),
                        booking_token=slot["config"]["token"],
                        party_size=party_size,
                        raw=slot,
                    )
                )
        return slots

    def details(self, slot: Slot) -> str:
        """Fetch book_token for a slot. Returns the book_token string."""
        body = urlencode(
            {
                "config_id": slot.booking_token,
                "day": slot.day,
                "party_size": slot.party_size,
            }
        )
        r = self.session.post(
            f"{API_BASE}/3/details",
            data=body,
            headers=self._headers("application/x-www-form-urlencoded"),
            timeout=10,
        )
        self._check(r)
        return r.json()["book_token"]["value"]

    def book(self, book_token: str, slot: Slot) -> dict:
        """Book a reservation. Returns result dict with normalized reservation_id key."""
        body = urlencode(
            {
                "book_token": book_token,
                "struct_payment_method": json.dumps({"id": self.payment_id}),
                "source_id": "resy.com-venue-details",
            }
        )
        r = self.session.post(
            f"{API_BASE}/3/book",
            data=body,
            headers=self._headers("application/x-www-form-urlencoded"),
            timeout=15,
        )
        self._check(r)
        result = r.json()
        # Normalize: ensure reservation_id is present
        if "reservation_id" not in result and "resy_token" in result:
            result["reservation_id"] = result["resy_token"]
        return result

    def cancel(self, reservation_id, resy_token):
        body = urlencode(
            {"reservation_id": reservation_id, "resy_token": resy_token}
        )
        r = self.session.delete(
            f"{API_BASE}/3/cancel",
            data=body,
            headers=self._headers("application/x-www-form-urlencoded"),
            timeout=10,
        )
        self._check(r)
        return r.json()

    def my_reservations(self):
        r = self.session.get(
            f"{API_BASE}/3/user/reservations", headers=self._headers(), timeout=10
        )
        self._check(r)
        return r.json()

    def user(self):
        r = self.session.get(
            f"{API_BASE}/2/user", headers=self._headers(), timeout=10
        )
        self._check(r)
        return r.json()
