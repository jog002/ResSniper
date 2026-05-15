from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Slot:
    provider: str        # "resy" | "sevenrooms"
    venue_key: str       # str(venue_id) for Resy, url_key for SevenRooms
    day: str             # "YYYY-MM-DD"
    time: str            # "YYYY-MM-DD HH:MM:SS"
    seating_type: str
    booking_token: str   # config_token (Resy) | access_persistent_id (SevenRooms)
    party_size: int
    raw: dict | None = None


# Canonical exception hierarchy — all providers raise these
class ProviderError(Exception):
    pass


class AuthExpiredError(ProviderError):
    pass


class CaptchaError(ProviderError):
    pass


class RateLimitedError(ProviderError):
    pass


class BookingNotImplementedError(ProviderError):
    pass


@runtime_checkable
class ReservationProvider(Protocol):
    def find(self, venue_key: str, day: str, party_size: int) -> list[Slot]: ...
    def details(self, slot: Slot) -> str: ...
    def book(self, book_token: str, slot: Slot) -> dict: ...
