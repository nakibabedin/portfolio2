-- Selling apparel: Stripe takes the payment, Printify prints and ships.
--
-- Printify owns the catalog: which sizes and colors exist, what each costs to
-- make, and what each sells for. A shop post only points at a Printify product;
-- `posts.price` is a cached "from" price (the cheapest enabled variant) so feed
-- tiles can show a price without calling Printify.
--
-- `shop_orders` is the bridge between the two services. A row is written when a
-- buyer is sent to Stripe Checkout, marked paid by Stripe's webhook, and then
-- carries the Printify order that webhook created.

ALTER TABLE posts
    ADD COLUMN IF NOT EXISTS printify_product_id VARCHAR(64);

CREATE TABLE IF NOT EXISTS shop_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 'pending'   sent to Checkout, not paid (abandoned sessions stay here)
    -- 'paid'      Stripe confirmed payment; Printify order not created yet
    -- 'submitted' Printify order exists (on hold or sent to production)
    -- 'failed'    paid, but creating the Printify order failed; see `error`
    -- Printify's own status ('in-production', 'fulfilled', ...) is tracked
    -- separately in `printify_status`.
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    stripe_session_id VARCHAR(255) UNIQUE NOT NULL,
    stripe_payment_intent_id VARCHAR(255),
    livemode BOOLEAN NOT NULL DEFAULT FALSE,
    post_id UUID REFERENCES posts(id) ON DELETE SET NULL,
    printify_product_id VARCHAR(64) NOT NULL,
    printify_variant_id BIGINT NOT NULL,
    variant_title VARCHAR(255),
    quantity INTEGER NOT NULL,
    -- All money in cents, as charged to the buyer.
    unit_price_cents INTEGER NOT NULL,
    shipping_cents INTEGER NOT NULL,
    amount_total_cents INTEGER,
    currency VARCHAR(3) NOT NULL DEFAULT 'usd',
    email VARCHAR(255),
    shipping_address JSONB,
    printify_order_id VARCHAR(64) UNIQUE,
    printify_status VARCHAR(64),
    tracking_number VARCHAR(255),
    tracking_url TEXT,
    error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_shop_orders_created_at ON shop_orders (created_at DESC);
