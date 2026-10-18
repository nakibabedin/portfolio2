"""Printify: the catalog behind the shop, and who prints and ships an order.

Printify is the source of truth for everything about a product -- its sizes and
colors, what each variant costs to make (`cost`) and what it sells for
(`price`), both integer cents. The site never keeps its own copy of a price it
charges: checkout re-reads the variant from Printify, so a price changed in
Printify (or from the admin, which writes through to Printify) is what the
buyer pays.

Calls here are synchronous. The Stripe webhook holds a row lock on the order
while it creates the Printify order, and blocking the event loop on that would
stall the whole API; the shop routes run these from FastAPI's threadpool.

API reference: https://developers.printify.com/
"""

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.printify.com/v1"
# Printify rejects requests without a User-Agent.
USER_AGENT = "rileydrcelik-portfolio"
_TIMEOUT = httpx.Timeout(30.0)

# Shipping is quoted before the buyer types an address (hosted Checkout shows
# one flat rate), so the shop ships to a single country and quotes its rate.
SHIP_COUNTRY = "US"

# Printify's live quote is what an order is actually charged. It does not vary
# by address within the US (checked Oct 2026: NY, CA and TX quote the same),
# only by item and quantity, so a placeholder address stands in for the
# buyer's. The catalog's shipping profiles are *not* used: they were stale,
# quoting $4.49 for an order Printify charged $5.35.
_QUOTE_ADDRESS = {
    "first_name": "Quote", "last_name": "Only", "email": "", "phone": "",
    "country": SHIP_COUNTRY, "region": "NY", "address1": "1 Main St", "address2": "",
    "city": "New York", "zip": "10001",
}

# Shipping quotes change rarely; product reads back the public listing,
# opened on every modal view.
_SHIPPING_TTL_S = 3600
_PRODUCT_TTL_S = 60
_cache: dict[str, tuple[float, Any]] = {}


class PrintifyNotConfigured(Exception):
    """PRINTIFY_API_TOKEN or PRINTIFY_SHOP_ID is unset."""


class PrintifyError(Exception):
    """Printify answered with an error, or could not be reached."""


def _config() -> tuple[str, str]:
    token = os.getenv("PRINTIFY_API_TOKEN", "").strip()
    shop_id = os.getenv("PRINTIFY_SHOP_ID", "").strip()
    if not token or not shop_id:
        raise PrintifyNotConfigured("PRINTIFY_API_TOKEN and PRINTIFY_SHOP_ID must be set")
    return token, shop_id


def is_configured() -> bool:
    try:
        _config()
        return True
    except PrintifyNotConfigured:
        return False


def _request(method: str, path: str, json: Optional[dict] = None) -> Any:
    token, _ = _config()
    try:
        response = httpx.request(
            method,
            f"{API_BASE}{path}",
            json=json,
            headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise PrintifyError(f"Printify unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise PrintifyError(f"Printify {method} {path} -> {response.status_code}: {response.text[:500]}")
    return response.json() if response.content else None


def _shop_path(suffix: str) -> str:
    _, shop_id = _config()
    return f"/shops/{shop_id}{suffix}"


def _cached(key: str, ttl_s: float, load):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl_s:
        return hit[1]
    value = load()
    _cache[key] = (time.monotonic(), value)
    return value


# --- API calls ---------------------------------------------------------------

def list_products(page: int = 1, limit: int = 50) -> dict:
    return _request("GET", _shop_path(f"/products.json?page={page}&limit={limit}"))


def get_product(product_id: str, fresh: bool = True) -> dict:
    """A product. ``fresh=False`` allows a copy up to a minute old, for reads
    that only display; anything that charges money reads fresh."""
    load = lambda: _request("GET", _shop_path(f"/products/{product_id}.json"))
    if fresh:
        product = load()
        _cache[f"product:{product_id}"] = (time.monotonic(), product)
        return product
    return _cached(f"product:{product_id}", _PRODUCT_TTL_S, load)


def update_variants(product: dict, changes: dict[int, dict]) -> dict:
    """Write new prices / enabled flags for some variants of ``product``.

    Printify requires *every* variant in a variants update, so the untouched
    ones are sent back as they are. ``changes`` maps variant id to any of
    ``price`` (cents) and ``is_enabled``.
    """
    variants = []
    for variant in product.get("variants", []):
        change = changes.get(variant["id"], {})
        variants.append({
            "id": variant["id"],
            "price": int(change.get("price", variant["price"])),
            "is_enabled": bool(change.get("is_enabled", variant.get("is_enabled", False))),
        })
    updated = _request("PUT", _shop_path(f"/products/{product['id']}.json"), json={"variants": variants})
    _cache.pop(f"product:{product['id']}", None)
    return updated


def acknowledge_publish(product_id: str, url: str) -> None:
    """Tell Printify the product is now live on the site, which unlocks it.

    Pressing Publish in Printify locks the product until the store (this
    site, for an API store) reports back. Until then every edit fails with
    "Product is disabled for editing". The site lists products by linking
    them to posts, so there is nothing else to do on publish but confirm it.
    """
    _request(
        "POST",
        _shop_path(f"/products/{product_id}/publishing_succeeded.json"),
        json={"external": {"id": product_id, "handle": url}},
    )
    _cache.pop(f"product:{product_id}", None)


def quote_shipping_cents(product_id: str, variant_id: int, quantity: int) -> int:
    """Standard US shipping Printify charges for ``quantity`` of one variant."""
    def load():
        body = _request("POST", _shop_path("/orders/shipping.json"), json={
            "line_items": [{"product_id": product_id, "variant_id": variant_id, "quantity": quantity}],
            "address_to": _QUOTE_ADDRESS,
        })
        return int(body["standard"])
    return _cached(f"shipping:{product_id}:{variant_id}:{quantity}", _SHIPPING_TTL_S, load)


def create_order(order: dict) -> str:
    body = _request("POST", _shop_path("/orders.json"), json=order)
    return body["id"]


def send_to_production(order_id: str) -> None:
    _request("POST", _shop_path(f"/orders/{order_id}/send_to_production.json"))


# --- Pure helpers ------------------------------------------------------------

def sellable_variants(product: dict) -> list[dict]:
    """Variants a buyer can pick: enabled for this product and in stock."""
    return [
        v for v in product.get("variants", [])
        if v.get("is_enabled") and v.get("is_available", True)
    ]


def find_sellable_variant(product: dict, variant_id: int) -> Optional[dict]:
    return next((v for v in sellable_variants(product) if v["id"] == variant_id), None)


def min_price_cents(product: dict) -> Optional[int]:
    prices = [v["price"] for v in sellable_variants(product)]
    return min(prices) if prices else None


def variant_image(product: dict, variant_id: int) -> Optional[str]:
    """The mockup Printify rendered for this variant, else the default one."""
    images = product.get("images", [])
    for image in images:
        if variant_id in image.get("variant_ids", []) and image.get("is_default"):
            return image.get("src")
    for image in images:
        if variant_id in image.get("variant_ids", []):
            return image.get("src")
    return images[0].get("src") if images else None


def listing(product: dict, shipping_cents: Optional[int] = None, include_costs: bool = False) -> dict:
    """The product as the site shows it.

    Public listings carry only sellable variants and the option values they
    use, so a size nobody can buy never appears in the picker. The admin view
    (``include_costs``) carries every variant with its cost, which is
    Printify's charge to the shop and never shown to buyers.
    """
    variants = product.get("variants", []) if include_costs else sellable_variants(product)
    used_values = {value_id for v in variants for value_id in v.get("options", [])}

    options = []
    for option in product.get("options", []):
        values = [
            {"id": value["id"], "title": value["title"], "colors": value.get("colors", [])}
            for value in option.get("values", [])
            if value["id"] in used_values
        ]
        if values:
            options.append({"name": option["name"], "type": option.get("type"), "values": values})

    out_variants = []
    for v in variants:
        entry = {
            "id": v["id"],
            "title": v.get("title", ""),
            "price_cents": v["price"],
            "options": v.get("options", []),
        }
        if include_costs:
            entry["cost_cents"] = v.get("cost")
            entry["is_enabled"] = bool(v.get("is_enabled"))
            entry["is_available"] = bool(v.get("is_available", True))
        out_variants.append(entry)

    return {
        "product_id": product["id"],
        "title": product.get("title", ""),
        "options": options,
        "variants": out_variants,
        # First-item shipping, quoted for one variant; sizes of one blank ship
        # alike. Checkout quotes the exact variant and quantity.
        "shipping_cents": shipping_cents,
        "images": [{"src": i.get("src"), "variant_ids": i.get("variant_ids", [])} for i in product.get("images", [])],
    }


def address_to(session: dict) -> dict:
    """Printify's ``address_to`` from a completed Stripe Checkout session.

    Stripe moved the collected shipping address to
    ``collected_information.shipping_details`` in API version 2025-03-31; the
    old top-level ``shipping_details`` is read as a fallback.
    """
    collected = session.get("collected_information") or {}
    shipping = collected.get("shipping_details") or session.get("shipping_details") or {}
    customer = session.get("customer_details") or {}
    address = shipping.get("address") or customer.get("address") or {}

    name = (shipping.get("name") or customer.get("name") or "").strip()
    first_name, _, last_name = name.partition(" ")
    return {
        "first_name": first_name,
        "last_name": last_name or first_name,
        "email": customer.get("email") or "",
        "phone": customer.get("phone") or "",
        "country": address.get("country") or "",
        "region": address.get("state") or "",
        "address1": address.get("line1") or "",
        "address2": address.get("line2") or "",
        "city": address.get("city") or "",
        "zip": address.get("postal_code") or "",
    }


def verify_webhook_signature(body: bytes, header: Optional[str], secret: str) -> bool:
    """Printify signs webhook bodies: ``X-Pfy-Signature: sha256=<hex hmac>``."""
    if not secret or not header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())
