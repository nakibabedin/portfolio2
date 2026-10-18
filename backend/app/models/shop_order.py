"""Shop orders and offers. See database/migration_add_shop.sql and
migration_add_meetup_listings.sql."""

import uuid

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class ShopOrder(Base):
    __tablename__ = "shop_orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String(16), nullable=False, default="pending")
    stripe_session_id = Column(String(255), unique=True, nullable=True)
    stripe_payment_intent_id = Column(String(255), nullable=True)
    livemode = Column(Boolean, nullable=False, default=False)
    post_id = Column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="SET NULL"), nullable=True)
    printify_product_id = Column(String(64), nullable=True)
    printify_variant_id = Column(BigInteger, nullable=True)
    variant_title = Column(String(255), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price_cents = Column(Integer, nullable=False)
    shipping_cents = Column(Integer, nullable=False)
    amount_total_cents = Column(Integer, nullable=True)
    currency = Column(String(3), nullable=False, default="usd")
    email = Column(String(255), nullable=True)
    shipping_address = Column(JSONB, nullable=True)
    printify_order_id = Column(String(64), unique=True, nullable=True)
    printify_status = Column(String(64), nullable=True)
    tracking_number = Column(String(255), nullable=True)
    tracking_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    # 'printify' (printed and shipped) or 'meetup' (handed over in person).
    fulfillment = Column(String(16), nullable=False, default="printify")
    # 'stripe' or 'cash'.
    payment_method = Column(String(16), nullable=False, default="stripe")
    phone = Column(String(64), nullable=True)
    offer_id = Column(UUID(as_uuid=True), ForeignKey("shop_offers.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class ShopOffer(Base):
    __tablename__ = "shop_offers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id = Column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="SET NULL"), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)
    offer_cents = Column(Integer, nullable=True)
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(64), nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="new")
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
