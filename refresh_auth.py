#!/usr/bin/env python3
"""Refresh Resy auth token using Playwright with a persistent browser profile.
Run this manually when the watcher reports AuthExpiredError.

Optional flags:
  --headless          Run browser in headless mode (may fail on first run)
  --skip-if-fresh     Exit early if current token is less than 7 days old
"""

import argparse
import asyncio
import os
import sys
import time

from lib.auth import load_credentials, save_credentials
from lib.notifier import notify

PLAYWRIGHT_STATE_DIR = os.path.join("scripts", "playwright-state")
RESY_URL = "https://resy.com"


async def capture_token(headless=False):
    """Launch browser, let user log in if needed, capture auth headers."""
    from playwright.async_api import async_playwright

    os.makedirs(PLAYWRIGHT_STATE_DIR, exist_ok=True)
    captured = {}

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PLAYWRIGHT_STATE_DIR,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Intercept network requests to capture auth headers
        async def on_request(request):
            headers = request.headers
            if "x-resy-auth-token" in headers and request.url.startswith(
                "https://api.resy.com"
            ):
                captured["auth_token"] = headers["x-resy-auth-token"]

        page.on("request", on_request)

        await page.goto(RESY_URL)

        # Check if already logged in
        await page.wait_for_load_state("networkidle", timeout=15000)
        if not captured.get("auth_token"):
            print(
                "\nLog in to Resy in the browser window if prompted, "
                "then navigate to any restaurant page and click the date picker."
            )
            print("Waiting for auth token to appear in network traffic...")
            print("(Press Ctrl+C to abort)\n")

        # Wait up to 3 minutes for a token to be captured
        deadline = time.time() + 180
        while not captured.get("auth_token") and time.time() < deadline:
            await asyncio.sleep(1)

        await ctx.close()

    if not captured.get("auth_token"):
        raise TimeoutError("No auth token captured. Did you visit a restaurant page?")

    return captured["auth_token"]


def main():
    parser = argparse.ArgumentParser(description="Refresh Resy auth token")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--skip-if-fresh", action="store_true")
    args = parser.parse_args()

    creds = load_credentials()

    if args.skip_if_fresh:
        refreshed_at = creds.get("refreshed_at", 0)
        age_days = (time.time() - refreshed_at) / 86400
        if age_days < 7:
            print(f"Token is {age_days:.1f} days old — still fresh, skipping.")
            sys.exit(0)

    print("Starting auth refresh...")
    try:
        new_token = asyncio.run(capture_token(headless=args.headless))
    except Exception as e:
        notify("Auth refresh failed", str(e), level="error")
        print(f"Error: {e}")
        sys.exit(1)

    creds["auth_token"] = new_token
    creds["refreshed_at"] = time.time()
    save_credentials(creds)
    notify("Auth refreshed", "credentials.yaml updated with new token", level="success")
    print("Done. credentials.yaml updated.")


if __name__ == "__main__":
    main()
