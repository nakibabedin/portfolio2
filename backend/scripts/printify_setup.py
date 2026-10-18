"""One-time Printify setup helpers for the shop.

    python scripts/printify_setup.py shops
        List the shops on your Printify account, to find PRINTIFY_SHOP_ID.

    python scripts/printify_setup.py webhooks https://<api-host>
        Register the order webhooks (status + tracking) and publish confirmation against the deployed
        API, signed with PRINTIFY_WEBHOOK_SECRET. Safe to re-run: topics that
        already point at this URL are skipped.

Reads PRINTIFY_API_TOKEN (and PRINTIFY_SHOP_ID, PRINTIFY_WEBHOOK_SECRET for
`webhooks`) from the environment / backend/.env.
"""

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

API = "https://api.printify.com/v1"
# Order progress, plus product publishes: pressing Publish in Printify locks the
# product until the site confirms it, which the webhook does automatically.
TOPICS = ["order:updated", "order:shipment:created", "order:shipment:delivered", "product:publish:started"]


def _client() -> httpx.Client:
    token = os.environ["PRINTIFY_API_TOKEN"]
    return httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "rileydrcelik-portfolio"},
        timeout=30,
    )


def shops() -> None:
    with _client() as client:
        for shop in client.get("/shops.json").raise_for_status().json():
            print(f"{shop['id']}\t{shop.get('title')}\t({shop.get('sales_channel')})")


def webhooks(api_host: str) -> None:
    shop_id = os.environ["PRINTIFY_SHOP_ID"]
    secret = os.environ["PRINTIFY_WEBHOOK_SECRET"]
    url = f"{api_host.rstrip('/')}/api/shop/webhooks/printify"
    with _client() as client:
        existing = client.get(f"/shops/{shop_id}/webhooks.json").raise_for_status().json()
        have = {(w["topic"], w["url"]) for w in existing}
        for topic in TOPICS:
            if (topic, url) in have:
                print(f"exists   {topic}")
                continue
            client.post(
                f"/shops/{shop_id}/webhooks.json",
                json={"topic": topic, "url": url, "secret": secret},
            ).raise_for_status()
            print(f"created  {topic} -> {url}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "shops":
        shops()
    elif len(sys.argv) >= 3 and sys.argv[1] == "webhooks":
        webhooks(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
