-- Meetup listings: shop items the owner sells in person, often also listed on
-- Facebook Marketplace (which has no API, so the two are kept in step by hand).
--
-- A shop post is either a Printify product (`listing_type = 'printify'`,
-- printed and shipped by Printify) or a meetup item (`'meetup'`): its price is
-- `posts.price`, `stock` is how many are left, and buyers either pay online
-- through Stripe or send a request / offer and settle at a public meetup.

ALTER TABLE posts ADD COLUMN IF NOT EXISTS listing_type VARCHAR(16);
ALTER TABLE posts ADD COLUMN IF NOT EXISTS stock INTEGER;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS accepts_offers BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS fb_marketplace_url TEXT;

UPDATE posts SET listing_type = 'printify'
WHERE printify_product_id IS NOT NULL AND listing_type IS NULL;

-- A buyer asking to buy a meetup item: at the listed price, or (when the item
-- takes offers) at the price they offer. Email is required, phone optional.
CREATE TABLE IF NOT EXISTS shop_offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID REFERENCES posts(id) ON DELETE SET NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    -- NULL: the buyer will pay the listed price.
    offer_cents INTEGER,
    name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(64),
    message TEXT,
    -- 'new' | 'accepted' | 'declined' | 'paid'
    status VARCHAR(16) NOT NULL DEFAULT 'new',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_shop_offers_created_at ON shop_offers (created_at DESC);

-- Orders now come from Printify products and meetup items, paid by Stripe or
-- in cash at the meetup (a cash order has no Stripe session).
ALTER TABLE shop_orders ADD COLUMN IF NOT EXISTS fulfillment VARCHAR(16) NOT NULL DEFAULT 'printify';
ALTER TABLE shop_orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(16) NOT NULL DEFAULT 'stripe';
ALTER TABLE shop_orders ADD COLUMN IF NOT EXISTS phone VARCHAR(64);
ALTER TABLE shop_orders ADD COLUMN IF NOT EXISTS offer_id UUID REFERENCES shop_offers(id) ON DELETE SET NULL;
-- While a meetup checkout is open its items are held; the hold lapses here.
ALTER TABLE shop_orders ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE shop_orders ALTER COLUMN stripe_session_id DROP NOT NULL;
ALTER TABLE shop_orders ALTER COLUMN printify_product_id DROP NOT NULL;
ALTER TABLE shop_orders ALTER COLUMN printify_variant_id DROP NOT NULL;
