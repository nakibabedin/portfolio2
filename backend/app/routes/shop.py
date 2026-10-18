"""The shop: Stripe takes the money; Printify prints and ships, or the owner
hands the item over at a public meetup.

A shop post is one of two listing types:

- ``printify``: a Printify product, with sizes/colors priced in Printify.
- ``meetup``: an item the owner sells in person (often also listed on
  Facebook Marketplace). Its price is ``posts.price`` and ``stock`` counts
  what's left. Buyers pay online here, or send a request / offer and settle at
  the meetup -- those live in ``shop_meetup.py``.

The flow for a Printify product, end to end:

1. The product modal reads ``GET /api/shop/listing/{post_id}`` -- the linked
   Printify product's sellable sizes/colors and prices.
2. "Buy" posts the chosen variant to ``POST /api/shop/checkout``. The price is
   re-read from Printify here, never taken from the browser. A ``pending``
   order row is written and the buyer is redirected to Stripe's hosted
   Checkout page, which collects the card and shipping address.
3. Stripe calls ``POST /api/shop/webhooks/stripe`` once the payment succeeds.
   That -- not the buyer landing on the success page, which they may never do
   -- is what marks the order paid and creates the Printify order.
4. Printify calls ``POST /api/shop/webhooks/printify`` as the order moves
   through production and ships, which fills in status and tracking.

Two switches keep money and printing apart while testing:

- ``PRINTIFY_AUTO_SUBMIT`` (default off): live orders are created in Printify
  *on hold*, to be sent to production from the Printify dashboard. Turn it on
  to send them straight to production.
- ``PRINTIFY_TEST_ORDERS`` (default off): Stripe test-mode payments create no
  Printify order at all. Turn it on to see test orders reach Printify (always
  on hold, never sent to production).

A meetup checkout is the same hand-off to Stripe, minus shipping: it holds
the items while the session is open, collects an email and phone, and the
webhook marks the order paid and takes the items out of stock.

The admin endpoints let the CRM link a post to a Printify product and edit
variant prices; edits are written through to Printify, which stays the source
of truth.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID, uuid4

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import SessionLocal, get_db
from app.lib import printify
from app.lib.firebase_auth import verify_firebase_token
from app.models.post import Post
from app.models.shop_order import ShopOffer, ShopOrder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shop", tags=["shop"])

MAX_QUANTITY = 10
CURRENCY = "usd"

# How long a meetup checkout holds its items. Stripe sessions live 30 minutes
# at the least and 24 hours at the most; a pay link sent for an accepted offer
# gets nearly the whole day.
CHECKOUT_HOLD = timedelta(minutes=30)
OFFER_LINK_HOLD = timedelta(hours=23)

MEETUP_NOTE = (
    "Pickup only, at a public meetup. You'll be contacted at the email or phone "
    "you give here to arrange it."
)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _stripe() -> stripe.StripeClient:
    key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="The shop is not configured (STRIPE_SECRET_KEY)")
    return stripe.StripeClient(key)


def _site_url() -> str:
    url = os.getenv("SHOP_PUBLIC_URL") or os.getenv("PORTFOLIO_PUBLIC_URL") or "http://localhost:3000"
    return url.strip().rstrip("/")


def _printify_call(fn, *args, **kwargs):
    """Run a Printify call, turning its failures into HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except printify.PrintifyNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except printify.PrintifyError as exc:
        logger.warning("[Shop] %s", exc)
        raise HTTPException(status_code=502, detail="Printify request failed") from exc


def _shop_post(db: Session, post_id: str) -> Post:
    try:
        UUID(post_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Product not found")
    post = db.query(Post).filter(Post.id == post_id, Post.category == "apparel").first()
    if not post or not (is_meetup(post) or post.printify_product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    return post


def is_meetup(post: Post) -> bool:
    return post.listing_type == "meetup"


def price_cents(post: Post) -> Optional[int]:
    return int(round(float(post.price) * 100)) if post.price is not None else None


def available_stock(db: Session, post: Post) -> int:
    """A meetup item's stock, less what open checkouts are holding."""
    held = (
        db.query(func.coalesce(func.sum(ShopOrder.quantity), 0))
        .filter(
            ShopOrder.post_id == post.id,
            ShopOrder.fulfillment == "meetup",
            ShopOrder.status == "pending",
            ShopOrder.expires_at > datetime.utcnow(),
        )
        .scalar()
    )
    return max(0, (post.stock or 0) - int(held))


def _unix(naive_utc: datetime) -> int:
    return int((naive_utc - datetime(1970, 1, 1)).total_seconds())


def start_meetup_checkout(
    db: Session,
    post: Post,
    quantity: int,
    unit_cents: int,
    hold: timedelta,
    offer: Optional[ShopOffer] = None,
):
    """Open a Stripe Checkout session for a meetup item and hold the items.

    Used both by "Buy now" (listed price, short hold) and by the pay link the
    owner sends for an accepted offer (offer price, day-long hold).
    """
    client = _stripe()
    order_id = uuid4()
    expires_at = datetime.utcnow() + hold
    product_data = {"name": post.title}
    image = (post.gallery_urls or [None])[0] or post.thumbnail_url
    if image and image.startswith("https://"):
        product_data["images"] = [image]

    params = {
        "mode": "payment",
        "client_reference_id": str(order_id),
        "metadata": {"shop_order_id": str(order_id), "post_id": str(post.id)},
        "line_items": [{
            "quantity": quantity,
            "price_data": {"currency": CURRENCY, "unit_amount": unit_cents, "product_data": product_data},
        }],
        "phone_number_collection": {"enabled": True},
        "custom_text": {"submit": {"message": MEETUP_NOTE}},
        "expires_at": _unix(expires_at),
        "success_url": f"{_site_url()}/shop/success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{_site_url()}/shop",
    }
    if offer and offer.email:
        params["customer_email"] = offer.email
    try:
        session = client.v1.checkout.sessions.create(params=params)
    except stripe.StripeError as exc:
        logger.warning("[Shop] Stripe session create failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not start checkout") from exc

    db.add(ShopOrder(
        id=order_id,
        status="pending",
        fulfillment="meetup",
        payment_method="stripe",
        stripe_session_id=session.id,
        livemode=bool(session.livemode),
        post_id=post.id,
        offer_id=offer.id if offer else None,
        quantity=quantity,
        unit_price_cents=unit_cents,
        shipping_cents=0,
        currency=CURRENCY,
        expires_at=expires_at,
    ))
    db.commit()
    return session


def _first_item_shipping(product: dict) -> Optional[int]:
    """Shipping for one of the first sellable variant, or None if Printify
    can't quote right now (the listing still shows; checkout quotes again)."""
    variants = printify.sellable_variants(product)
    if not variants:
        return None
    try:
        return printify.quote_shipping_cents(product["id"], variants[0]["id"], 1)
    except printify.PrintifyError as exc:
        logger.warning("[Shop] Shipping quote unavailable for %s: %s", product.get("id"), exc)
        return None


def _product_url(db: Session, product_id: str) -> str:
    """Where a Printify product is sold on the site: its post, else the shop."""
    post = db.query(Post).filter(Post.printify_product_id == product_id).first()
    if post and post.slug:
        return f"{_site_url()}/shop/{post.album}/{post.slug}"
    return f"{_site_url()}/shop"


def _unlock(db: Session, product: dict) -> dict:
    """Confirm a pending Printify publish so the product can be edited again."""
    if not product.get("is_locked"):
        return product
    _printify_call(printify.acknowledge_publish, product["id"], _product_url(db, product["id"]))
    return _printify_call(printify.get_product, product["id"])


def refresh_cached_price(post: Post) -> None:
    """Copy the linked product's cheapest price onto ``post.price`` so feed
    tiles show a price without calling Printify. Best effort."""
    if not post.printify_product_id:
        return
    try:
        cents = printify.min_price_cents(printify.get_product(post.printify_product_id))
    except (printify.PrintifyError, printify.PrintifyNotConfigured) as exc:
        logger.warning("[Shop] Could not refresh price for post %s: %s", post.id, exc)
        return
    post.price = cents / 100 if cents is not None else None


# --- Public ------------------------------------------------------------------

@router.get("/listing/{post_id}")
def get_listing(post_id: str, db: Session = Depends(get_db)):
    post = _shop_post(db, post_id)
    if is_meetup(post):
        return {
            "type": "meetup",
            "title": post.title,
            "price_cents": price_cents(post),
            "available": available_stock(db, post),
            "accepts_offers": bool(post.accepts_offers),
            "fb_marketplace_url": post.fb_marketplace_url,
            "max_quantity": MAX_QUANTITY,
        }
    product = _printify_call(printify.get_product, post.printify_product_id, fresh=False)
    listing = printify.listing(product, _first_item_shipping(product))
    listing["type"] = "printify"
    listing["ships_to"] = [printify.SHIP_COUNTRY]
    return listing


class CheckoutRequest(BaseModel):
    post_id: str
    # Printify products only; a meetup item has no variants.
    variant_id: Optional[int] = None
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)


@router.post("/checkout")
def create_checkout(body: CheckoutRequest, db: Session = Depends(get_db)):
    client = _stripe()
    post = _shop_post(db, body.post_id)
    if is_meetup(post):
        unit = price_cents(post)
        if not unit:
            raise HTTPException(status_code=409, detail="This item has no price yet")
        # Locked so two buyers can't both be handed the last one.
        db.query(Post).filter(Post.id == post.id).with_for_update().first()
        if available_stock(db, post) < body.quantity:
            raise HTTPException(status_code=409, detail="Not enough left")
        session = start_meetup_checkout(db, post, body.quantity, unit, CHECKOUT_HOLD)
        return {"url": session.url}

    product = _printify_call(printify.get_product, post.printify_product_id)

    variant = printify.find_sellable_variant(product, body.variant_id)
    if not variant:
        raise HTTPException(status_code=409, detail="That option is no longer available")

    shipping = _printify_call(printify.quote_shipping_cents, product["id"], variant["id"], body.quantity)

    order_id = uuid4()
    image = printify.variant_image(product, variant["id"])
    product_data = {"name": f"{post.title} ({variant.get('title', '')})".strip()}
    if image:
        product_data["images"] = [image]

    try:
        session = client.v1.checkout.sessions.create(params={
            "mode": "payment",
            "client_reference_id": str(order_id),
            "metadata": {"shop_order_id": str(order_id), "post_id": str(post.id)},
            "line_items": [{
                "quantity": body.quantity,
                "price_data": {
                    "currency": CURRENCY,
                    "unit_amount": variant["price"],
                    "product_data": product_data,
                },
            }],
            "shipping_address_collection": {"allowed_countries": [printify.SHIP_COUNTRY]},
            "shipping_options": [{
                "shipping_rate_data": {
                    "type": "fixed_amount",
                    "display_name": "Standard shipping",
                    "fixed_amount": {"amount": shipping, "currency": CURRENCY},
                },
            }],
            "phone_number_collection": {"enabled": True},
            "success_url": f"{_site_url()}/shop/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{_site_url()}/shop",
        })
    except stripe.StripeError as exc:
        logger.warning("[Shop] Stripe session create failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not start checkout") from exc

    # Written once the session exists. The webhook can't arrive before this:
    # it needs the buyer to have finished paying on Stripe's page first.
    db.add(ShopOrder(
        id=order_id,
        status="pending",
        stripe_session_id=session.id,
        livemode=bool(session.livemode),
        post_id=post.id,
        printify_product_id=product["id"],
        printify_variant_id=variant["id"],
        variant_title=variant.get("title"),
        quantity=body.quantity,
        unit_price_cents=variant["price"],
        shipping_cents=shipping,
        currency=CURRENCY,
    ))
    db.commit()
    return {"url": session.url}


@router.get("/checkout/{session_id}")
def get_checkout(session_id: str, db: Session = Depends(get_db)):
    """What the success page shows. Read from our row, so it says "processing"
    until Stripe's webhook has actually confirmed the payment."""
    order = db.query(ShopOrder).filter(ShopOrder.stripe_session_id == session_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    post = db.query(Post).filter(Post.id == order.post_id).first() if order.post_id else None
    return {
        "status": order.status,
        "title": post.title if post else None,
        "variant_title": order.variant_title,
        "quantity": order.quantity,
        "amount_total_cents": order.amount_total_cents,
        "currency": order.currency,
        "fulfillment": order.fulfillment,
    }


# --- Webhooks ----------------------------------------------------------------

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(default=None)):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET is not set")

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event.type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        session = event.data.object.to_dict()
        if session.get("payment_status") == "paid":
            # Fulfilment takes a row lock and calls Printify synchronously;
            # off the event loop so neither blocks other requests.
            await run_in_threadpool(_fulfil, session, bool(event.livemode))
    elif event.type == "checkout.session.expired":
        await run_in_threadpool(_expire, event.data.object.id)

    return {"received": True}


def _fulfil(session: dict, livemode: bool) -> None:
    """Mark the order paid and create its Printify order, exactly once.

    Stripe retries a webhook until it gets a 2xx and may deliver the same event
    twice, even concurrently. The row lock serialises duplicates and the
    ``printify_order_id`` check makes a repeat a no-op. A Printify failure is
    re-raised as a 500 so Stripe retries it later.
    """
    db = SessionLocal()
    try:
        order = (
            db.query(ShopOrder)
            .filter(ShopOrder.stripe_session_id == session["id"])
            .with_for_update()
            .first()
        )
        if not order:
            logger.warning("[Shop] Paid session %s has no order row", session["id"])
            return
        if order.fulfillment == "meetup":
            _fulfil_meetup(db, order, session, livemode)
            return
        if order.printify_order_id:
            return

        address = printify.address_to(session)
        order.status = "paid"
        order.livemode = livemode
        order.amount_total_cents = session.get("amount_total")
        order.email = address["email"] or None
        order.shipping_address = address
        payment_intent = session.get("payment_intent")
        order.stripe_payment_intent_id = payment_intent if isinstance(payment_intent, str) else None

        if not livemode and not _flag("PRINTIFY_TEST_ORDERS"):
            order.error = "Stripe test mode: no Printify order created (PRINTIFY_TEST_ORDERS is off)"
            db.commit()
            return

        try:
            order.printify_order_id = printify.create_order({
                "external_id": str(order.id),
                "label": f"{'TEST ' if not livemode else ''}{str(order.id)[:8]}",
                "line_items": [{
                    "product_id": order.printify_product_id,
                    "variant_id": order.printify_variant_id,
                    "quantity": order.quantity,
                }],
                "shipping_method": 1,  # standard, which is what was quoted
                "send_shipping_notification": True,
                "address_to": address,
            })
        except (printify.PrintifyError, printify.PrintifyNotConfigured) as exc:
            order.status = "failed"
            order.error = str(exc)[:2000]
            db.commit()
            logger.error("[Shop] Printify order failed for %s: %s", order.id, exc)
            raise HTTPException(status_code=500, detail="Printify order failed; Stripe will retry")

        order.status = "submitted"
        order.printify_status = "on-hold"
        order.error = None
        db.commit()
        logger.info("[Shop] Order %s -> Printify %s", order.id, order.printify_order_id)

        if livemode and _flag("PRINTIFY_AUTO_SUBMIT"):
            try:
                printify.send_to_production(order.printify_order_id)
                order.printify_status = "sending-to-production"
            except printify.PrintifyError as exc:
                # The order exists on hold; it can be sent from the dashboard.
                order.error = f"send_to_production failed: {exc}"[:2000]
            db.commit()
    finally:
        db.close()


def _fulfil_meetup(db: Session, order: ShopOrder, session: dict, livemode: bool) -> None:
    """Mark a meetup order paid and take its items out of stock, once."""
    if order.status not in ("pending", "expired"):
        return
    contact = printify.address_to(session)
    order.status = "paid"
    order.livemode = livemode
    order.amount_total_cents = session.get("amount_total")
    order.email = contact["email"] or None
    order.phone = contact["phone"] or None
    payment_intent = session.get("payment_intent")
    order.stripe_payment_intent_id = payment_intent if isinstance(payment_intent, str) else None

    post = db.query(Post).filter(Post.id == order.post_id).with_for_update().first() if order.post_id else None
    if post and post.stock is not None:
        if post.stock < order.quantity:
            # The hold should prevent this, but an item sold for cash meanwhile
            # can still beat a slow payer to the last one.
            order.error = f"Oversold: {post.stock} left when this was paid. Refund it or find another."
        post.stock = max(0, post.stock - order.quantity)
    if order.offer_id:
        offer = db.query(ShopOffer).filter(ShopOffer.id == order.offer_id).first()
        if offer:
            offer.status = "paid"
    db.commit()
    logger.info("[Shop] Meetup order %s paid", order.id)


def _expire(session_id: str) -> None:
    db = SessionLocal()
    try:
        order = db.query(ShopOrder).filter(ShopOrder.stripe_session_id == session_id).first()
        if order and order.status == "pending":
            order.status = "expired"
            db.commit()
    finally:
        db.close()


@router.post("/webhooks/printify")
async def printify_webhook(
    request: Request,
    x_pfy_signature: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    secret = os.getenv("PRINTIFY_WEBHOOK_SECRET", "").strip()
    body = await request.body()
    if not printify.verify_webhook_signature(body, x_pfy_signature, secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = await request.json()
    resource = event.get("resource") or {}
    data = resource.get("data") or {}

    if event.get("type") == "product:publish:started" and resource.get("id"):
        try:
            await run_in_threadpool(printify.acknowledge_publish, resource["id"], _product_url(db, resource["id"]))
        except printify.PrintifyError as exc:
            logger.warning("[Shop] Could not confirm publish of %s: %s", resource["id"], exc)
            raise HTTPException(status_code=502, detail="Could not confirm publish")
        return {"received": True}

    order = db.query(ShopOrder).filter(ShopOrder.printify_order_id == resource.get("id")).first()
    if not order:
        return {"received": True}

    topic = event.get("type")
    if topic == "order:updated" and data.get("status"):
        order.printify_status = data["status"]
    elif topic == "order:shipment:created":
        order.printify_status = "shipped"
        carrier = data.get("carrier") or {}
        order.tracking_number = carrier.get("tracking_number") or order.tracking_number
        order.tracking_url = carrier.get("tracking_url") or order.tracking_url
    elif topic == "order:shipment:delivered":
        order.printify_status = "delivered"
    db.commit()
    return {"received": True}


# --- Admin (CRM) -------------------------------------------------------------

@router.get("/admin/printify-products")
def admin_list_products(page: int = 1, current_user=Depends(verify_firebase_token)):
    """Printify products to link a shop post to."""
    body = _printify_call(printify.list_products, page=page)
    return {
        "products": [
            {
                "id": p["id"],
                "title": p.get("title", ""),
                "image": (p.get("images") or [{}])[0].get("src"),
                "min_price_cents": printify.min_price_cents(p),
            }
            for p in body.get("data", [])
        ],
        "last_page": body.get("last_page", 1),
    }


@router.get("/admin/products/{product_id}")
def admin_get_product(product_id: str, current_user=Depends(verify_firebase_token)):
    product = _printify_call(printify.get_product, product_id)
    return printify.listing(product, _first_item_shipping(product), include_costs=True)


class VariantChange(BaseModel):
    id: int
    price_cents: Optional[int] = Field(default=None, ge=0)
    is_enabled: Optional[bool] = None


class VariantsUpdate(BaseModel):
    variants: List[VariantChange]


@router.put("/admin/products/{product_id}/variants")
def admin_update_variants(
    product_id: str,
    body: VariantsUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(verify_firebase_token),
):
    """Edit prices / enabled variants from the CRM, written through to Printify."""
    product = _unlock(db, _printify_call(printify.get_product, product_id))
    changes = {}
    for change in body.variants:
        entry = {}
        if change.price_cents is not None:
            entry["price"] = change.price_cents
        if change.is_enabled is not None:
            entry["is_enabled"] = change.is_enabled
        changes[change.id] = entry
    _printify_call(printify.update_variants, product, changes)

    product = _printify_call(printify.get_product, product_id)
    cents = printify.min_price_cents(product)
    for post in db.query(Post).filter(Post.printify_product_id == product_id).all():
        post.price = cents / 100 if cents is not None else None
    db.commit()
    return printify.listing(product, _first_item_shipping(product), include_costs=True)


@router.get("/admin/orders")
def admin_list_orders(limit: int = 50, db: Session = Depends(get_db), current_user=Depends(verify_firebase_token)):
    orders = (
        db.query(ShopOrder)
        .filter(ShopOrder.status.notin_(("pending", "expired")))
        .order_by(ShopOrder.created_at.desc())
        .limit(limit)
        .all()
    )
    post_ids = {o.post_id for o in orders if o.post_id}
    titles = dict(db.query(Post.id, Post.title).filter(Post.id.in_(post_ids)).all()) if post_ids else {}
    return [
        {
            "id": str(o.id),
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "status": o.status,
            "livemode": o.livemode,
            "fulfillment": o.fulfillment,
            "payment_method": o.payment_method,
            "title": titles.get(o.post_id),
            "email": o.email,
            "phone": o.phone,
            "variant_title": o.variant_title,
            "quantity": o.quantity,
            "amount_total_cents": o.amount_total_cents,
            "printify_order_id": o.printify_order_id,
            "printify_status": o.printify_status,
            "tracking_url": o.tracking_url,
            "error": o.error,
        }
        for o in orders
    ]
