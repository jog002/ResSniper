"""Provider factory — returns poll/book clients for any supported provider."""

from lib.auth import load_provider_credentials


def resolve_provider(rule: dict, defaults: dict | None = None) -> str:
    """Get provider from rule or defaults. Falls back to 'resy'."""
    return rule.get("provider") or (defaults or {}).get("provider", "resy")


def resolve_venue_key(rule: dict) -> str:
    """Get venue_key string from rule. venue_key takes priority over venue_id."""
    if "venue_key" in rule:
        return str(rule["venue_key"])
    if "venue_id" in rule:
        return str(rule["venue_id"])
    raise ValueError(f"Rule has neither venue_key nor venue_id: {rule}")


def get_poll_client(provider: str):
    """Return an anonymous poll-only client for the given provider."""
    if provider == "resy":
        from lib.resy_client import ResyClient
        return ResyClient.poll_only()
    if provider == "sevenrooms":
        from lib.sevenrooms_client import SevenRoomsClient
        return SevenRoomsClient()
    raise ValueError(f"Unknown provider: {provider!r}")


def get_book_client(provider: str, creds: dict | None = None):
    """Return a booking-capable client for the given provider."""
    if provider == "resy":
        from lib.resy_client import ResyClient
        if creds is None:
            creds = load_provider_credentials("resy")
        return ResyClient(creds["auth_token"], creds["payment_id"], creds.get("api_key"))
    if provider == "sevenrooms":
        from lib.sevenrooms_client import SevenRoomsClient
        if creds is None:
            creds = load_provider_credentials("sevenrooms")
        return SevenRoomsClient(auth_token=creds.get("auth_token"))
    raise ValueError(f"Unknown provider: {provider!r}")
