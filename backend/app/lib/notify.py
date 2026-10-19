"""Email the owner when a meetup item needs them: a new request or offer, or
an online purchase to hand over.

Sent through Resend (https://resend.com) with one HTTP call. Each email's
reply-to is the buyer, so answering it from the inbox reaches them directly.

Never in the way of a sale: unset ``RESEND_API_KEY`` or ``SHOP_NOTIFY_EMAIL``
turns emails off, and a failed send is logged, not raised.
"""

import html
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
# Resend's shared sender works without verifying a domain, but only delivers
# to the address the Resend account was opened with -- which, for emails to
# yourself, is exactly what's wanted.
DEFAULT_FROM = "Shop <onboarding@resend.dev>"


def _money(cents: Optional[int]) -> str:
    return f"${cents / 100:,.2f}" if cents is not None else "—"


def _site_url() -> str:
    url = os.getenv("SHOP_PUBLIC_URL") or os.getenv("PORTFOLIO_PUBLIC_URL") or "http://localhost:3000"
    return url.strip().rstrip("/")


def _send(subject: str, lines: list[tuple[str, str]], reply_to: Optional[str]) -> None:
    key = os.getenv("RESEND_API_KEY", "").strip()
    to = os.getenv("SHOP_NOTIFY_EMAIL", "").strip()
    if not key or not to:
        return

    admin = f"{_site_url()}/admin"
    rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#666'>{html.escape(k)}</td>"
        f"<td style='padding:4px 0'>{html.escape(v)}</td></tr>"
        for k, v in lines if v
    )
    body_html = (
        f"<table style='font-family:sans-serif;font-size:14px'>{rows}</table>"
        f"<p style='font-family:sans-serif;font-size:14px'><a href='{admin}'>Open the shop admin</a>"
        f" &middot; reply to this email to answer the buyer.</p>"
    )
    body_text = "\n".join(f"{k}: {v}" for k, v in lines if v) + f"\n\nShop admin: {admin}\nReply to this email to answer the buyer."

    payload = {
        "from": os.getenv("SHOP_EMAIL_FROM", "").strip() or DEFAULT_FROM,
        "to": [to],
        "subject": subject,
        "html": body_html,
        "text": body_text,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        response = httpx.post(RESEND_URL, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=15)
        if response.status_code >= 400:
            logger.warning("[Notify] Resend %s: %s", response.status_code, response.text[:300])
    except httpx.HTTPError as exc:
        logger.warning("[Notify] Resend unreachable: %s", exc)


def new_offer(
    title: str,
    quantity: int,
    offer_cents: Optional[int],
    listed_cents: Optional[int],
    name: Optional[str],
    email: str,
    phone: Optional[str],
    message: Optional[str],
) -> None:
    if offer_cents is not None:
        subject = f"Offer: {_money(offer_cents)} for {title}"
        price = f"{_money(offer_cents)} (listed {_money(listed_cents)})"
    else:
        subject = f"Pay-in-person request: {title}"
        price = f"{_money(listed_cents)} (listed price)"
    _send(subject, [
        ("Item", title + (f" × {quantity}" if quantity > 1 else "")),
        ("Price", price + (" each" if quantity > 1 else "")),
        ("Name", name or ""),
        ("Email", email),
        ("Phone", phone or ""),
        ("Message", message or ""),
    ], reply_to=email)


def meetup_paid(
    title: str,
    quantity: int,
    amount_cents: Optional[int],
    email: Optional[str],
    phone: Optional[str],
    livemode: bool,
) -> None:
    _send(f"{'' if livemode else '[TEST] '}Paid online, set up a meetup: {title}", [
        ("Item", title + (f" × {quantity}" if quantity > 1 else "")),
        ("Paid", _money(amount_cents) + ("" if livemode else " (Stripe test mode)")),
        ("Email", email or ""),
        ("Phone", phone or ""),
    ], reply_to=email)
