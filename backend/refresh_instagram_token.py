"""Refresh the long-lived Instagram access token.

Instagram's long-lived tokens expire after 60 days. When one lapses, nothing
breaks loudly -- posts keep publishing on the site, the background task fails,
and the toggle just silently stops reaching Instagram. So this needs running on
a schedule well inside that window; monthly is the usual choice.

    python refresh_instagram_token.py

It prints the new token and its expiry. It deliberately does *not* write to
.env: the token lives in the Railway environment in production, and having a
script quietly rewrite credentials in two places is how the two drift apart.
Copy the printed value into wherever INSTAGRAM_ACCESS_TOKEN is set.

A token must be at least 24 hours old to be refreshable, and refreshing resets
the clock to another 60 days from today (it does not extend the original).
"""

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("INSTAGRAM_GRAPH_HOST", "https://graph.instagram.com").strip().rstrip("/")


def refresh() -> int:
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not token:
        print("INSTAGRAM_ACCESS_TOKEN is not set; nothing to refresh.")
        return 1

    try:
        response = httpx.get(
            f"{HOST}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        print(f"Could not reach Instagram: {exc}")
        return 1

    if response.status_code >= 400:
        print(f"Refresh failed: {response.status_code} {response.text[:400]}")
        print(
            "\nIf this says the token is invalid or expired, the 60-day window has "
            "already closed and it cannot be refreshed -- generate a new long-lived "
            "token from the Meta app dashboard."
        )
        return 1

    body = response.json()
    seconds = body.get("expires_in", 0)
    print("New token:")
    print(body.get("access_token", "<missing>"))
    print(f"\nExpires in {seconds} seconds (~{seconds // 86400} days).")
    print("Set this as INSTAGRAM_ACCESS_TOKEN wherever the backend reads its environment.")
    return 0


if __name__ == "__main__":
    sys.exit(refresh())
