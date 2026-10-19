"""Meetup items: requests, offers, and settling up in person.

Besides "Buy now" (a Stripe checkout, in ``shop.py``), a buyer can send a
request for a meetup item: how many, an email (and optionally a phone), an
optional message, and -- when the owner lets the item take offers -- the price
they offer. Requests land in the admin, where the owner:

- sends a **pay link**: a Stripe checkout at the agreed price, which holds the
  items for most of a day and is paid through the same webhook as "Buy now";
- marks it **paid in cash** at the meetup, which records the sale and takes
  the items out of stock; or
- **declines** it.

Facebook Marketplace has no API for personal listings, so nothing here talks
to Facebook: the post just links to the listing, and the owner marks an item
sold in one place when it sells in the other.
"""

import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.lib import notify
from app.lib.firebase_auth import verify_firebase_token
from app.models.post import Post
from app.models.shop_order import ShopOffer, ShopOrder
from app.routes.shop import (
    CURRENCY,
    MAX_QUANTITY,
    OFFER_LINK_HOLD,
    _shop_post,
    _stripe,
    available_stock,
    is_meetup,
    price_cents,
    start_meetup_checkout,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shop", tags=["shop"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The request form is public. A handful per visitor every ten minutes is
# plenty for a person and makes it a poor target for a script.
RATE_LIMIT = 5
RATE_WINDOW_S = 600
_recent: dict[str, deque] = defaultdict(deque)


def _allow(ip: str) -> bool:
    now = time.monotonic()
    hits = _recent[ip]
    while hits and now - hits[0] > RATE_WINDOW_S:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return False
    hits.append(now)
    return True


def _offer(db: Session, offer_id: str) -> ShopOffer:
    try:
        UUID(offer_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Request not found")
    offer = db.query(ShopOffer).filter(ShopOffer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Request not found")
    return offer


def _offer_post(db: Session, offer: ShopOffer) -> Post:
    post = db.query(Post).filter(Post.id == offer.post_id).first() if offer.post_id else None
    if not post:
        raise HTTPException(status_code=409, detail="The item for this request no longer exists")
    return post


def _agreed_unit_cents(offer: ShopOffer, post: Post) -> int:
    unit = offer.offer_cents if offer.offer_cents is not None else price_cents(post)
    if not unit:
        raise HTTPException(status_code=409, detail="This item has no price yet")
    return unit


def _expire_open_links(db: Session, offer: ShopOffer) -> None:
    """Close any pay link still open for this offer, so it can't be paid twice."""
    pending = (
        db.query(ShopOrder)
        .filter(ShopOrder.offer_id == offer.id, ShopOrder.status == "pending")
        .all()
    )
    if not pending:
        return
    client = _stripe()
    for order in pending:
        try:
            client.v1.checkout.sessions.expire(order.stripe_session_id)
        except Exception as exc:  # noqa: BLE001 - already expired or paid; the webhook sorts out paid ones
            logger.warning("[Shop] Could not expire session %s: %s", order.stripe_session_id, exc)
        order.status = "expired"


# --- Public ------------------------------------------------------------------

class OfferRequest(BaseModel):
    post_id: str
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)
    # Cents. Required when the item takes offers; omitted otherwise (the
    # buyer reserves it at the listed price).
    offer_cents: Optional[int] = Field(default=None, ge=1)
    name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=64)
    message: Optional[str] = Field(default=None, max_length=2000)
    # Hidden from people; a bot that fills every field fills this one too.
    website: Optional[str] = None


@router.post("/offers")
def create_offer(
    body: OfferRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if body.website:
        return {"received": True}
    if not _allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Too many requests; try again in a few minutes")

    post = _shop_post(db, body.post_id)
    if not is_meetup(post):
        raise HTTPException(status_code=404, detail="Product not found")

    email = (body.email or "").strip() or None
    phone = (body.phone or "").strip() or None
    if not email:
        raise HTTPException(status_code=422, detail="Leave an email so you can be reached")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="That email doesn't look right")
    if phone and len(re.sub(r"\D", "", phone)) < 7:
        raise HTTPException(status_code=422, detail="That phone number doesn't look right")
    # An item that takes offers is asked for with a price; one that doesn't is
    # reserved at its listed price.
    if post.accepts_offers and body.offer_cents is None:
        raise HTTPException(status_code=422, detail="Enter your offer")
    if body.offer_cents is not None and not post.accepts_offers:
        raise HTTPException(status_code=422, detail="This item doesn't take offers")
    if available_stock(db, post) < body.quantity:
        raise HTTPException(status_code=409, detail="Not enough left")

    offer = ShopOffer(
        post_id=post.id,
        quantity=body.quantity,
        offer_cents=body.offer_cents,
        name=(body.name or "").strip() or None,
        email=email,
        phone=phone,
        message=(body.message or "").strip() or None,
    )
    db.add(offer)
    db.commit()
    # After the response, so a slow mail service never delays the buyer.
    background_tasks.add_task(
        notify.new_offer, post.title, offer.quantity, offer.offer_cents, price_cents(post),
        offer.name, offer.email, offer.phone, offer.message,
    )
    return {"received": True}


# --- Admin -------------------------------------------------------------------

@router.get("/admin/offers")
def admin_list_offers(
    include_closed: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(verify_firebase_token),
):
    query = db.query(ShopOffer)
    if not include_closed:
        query = query.filter(ShopOffer.status.in_(("new", "accepted")))
    offers = query.order_by(ShopOffer.created_at.desc()).limit(100).all()
    posts = {
        p.id: p
        for p in db.query(Post).filter(Post.id.in_({o.post_id for o in offers if o.post_id})).all()
    } if offers else {}
    open_links = {
        o.offer_id: o.expires_at
        for o in db.query(ShopOrder).filter(
            ShopOrder.offer_id.in_([o.id for o in offers]),
            ShopOrder.status == "pending",
            ShopOrder.expires_at > datetime.utcnow(),
        ).all()
    } if offers else {}
    out = []
    for o in offers:
        post = posts.get(o.post_id)
        out.append({
            "id": str(o.id),
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "status": o.status,
            "post_id": str(o.post_id) if o.post_id else None,
            "title": post.title if post else None,
            "listed_price_cents": price_cents(post) if post else None,
            "available": available_stock(db, post) if post else 0,
            "quantity": o.quantity,
            "offer_cents": o.offer_cents,
            "name": o.name,
            "email": o.email,
            "phone": o.phone,
            "message": o.message,
            "pay_link_expires_at": open_links[o.id].isoformat() if o.id in open_links else None,
        })
    return out


@router.post("/admin/offers/{offer_id}/pay-link")
def admin_offer_pay_link(offer_id: str, db: Session = Depends(get_db), current_user=Depends(verify_firebase_token)):
    """A Stripe checkout at the agreed price, for the owner to send the buyer."""
    offer = _offer(db, offer_id)
    if offer.status not in ("new", "accepted"):
        raise HTTPException(status_code=409, detail=f"This request is already {offer.status}")
    post = _offer_post(db, offer)
    unit = _agreed_unit_cents(offer, post)

    db.query(Post).filter(Post.id == post.id).with_for_update().first()
    _expire_open_links(db, offer)  # releases their hold before re-checking stock
    db.flush()
    if available_stock(db, post) < offer.quantity:
        raise HTTPException(status_code=409, detail="Not enough left")

    offer.status = "accepted"
    session = start_meetup_checkout(db, post, offer.quantity, unit, OFFER_LINK_HOLD, offer=offer)
    return {"url": session.url, "amount_cents": unit * offer.quantity}


@router.post("/admin/offers/{offer_id}/paid-cash")
def admin_offer_paid_cash(offer_id: str, db: Session = Depends(get_db), current_user=Depends(verify_firebase_token)):
    """Record a sale settled in person, and take the items out of stock."""
    offer = _offer(db, offer_id)
    if offer.status not in ("new", "accepted"):
        raise HTTPException(status_code=409, detail=f"This request is already {offer.status}")
    post = _offer_post(db, offer)
    unit = _agreed_unit_cents(offer, post)

    db.query(Post).filter(Post.id == post.id).with_for_update().first()
    _expire_open_links(db, offer)
    if post.stock is not None:
        post.stock = max(0, post.stock - offer.quantity)
    offer.status = "paid"
    db.add(ShopOrder(
        status="completed",
        fulfillment="meetup",
        payment_method="cash",
        livemode=True,
        post_id=post.id,
        offer_id=offer.id,
        quantity=offer.quantity,
        unit_price_cents=unit,
        shipping_cents=0,
        amount_total_cents=unit * offer.quantity,
        currency=CURRENCY,
        email=offer.email,
        phone=offer.phone,
    ))
    db.commit()
    return {"status": offer.status, "stock": post.stock}


@router.post("/admin/offers/{offer_id}/decline")
def admin_offer_decline(offer_id: str, db: Session = Depends(get_db), current_user=Depends(verify_firebase_token)):
    offer = _offer(db, offer_id)
    if offer.status == "paid":
        raise HTTPException(status_code=409, detail="This request is already paid")
    _expire_open_links(db, offer)
    offer.status = "declined"
    db.commit()
    return {"status": offer.status}


@router.post("/admin/orders/{order_id}/complete")
def admin_complete_order(order_id: str, db: Session = Depends(get_db), current_user=Depends(verify_firebase_token)):
    """Mark a paid meetup order as handed over."""
    try:
        UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Order not found")
    order = db.query(ShopOrder).filter(ShopOrder.id == order_id).first()
    if not order or order.fulfillment != "meetup":
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "paid":
        raise HTTPException(status_code=409, detail=f"This order is {order.status}")
    order.status = "completed"
    db.commit()
    return {"status": order.status}
