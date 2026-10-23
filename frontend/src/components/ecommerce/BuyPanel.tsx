'use client';

import { useEffect, useMemo, useState } from 'react';
import { Minus, Plus } from 'lucide-react';
import { formatCents, getShopListing, startCheckout, type MeetupListing, type ShopListing, type ShopVariant } from '@/lib/api';
import MeetupPanel from './MeetupPanel';

const MAX_QUANTITY = 10;

interface BuyPanelProps {
  postId: string;
  /** Cached "from" price shown while the listing loads, in dollars. */
  fallbackPrice?: string | null;
}

const buttonClass =
  'inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-white font-semibold border border-white/20 shadow-md shadow-black/30 transition-all duration-200 w-full md:w-auto backdrop-blur-sm hover:border-white/50 hover:shadow-xl hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent';

/**
 * How to buy a shop post: a Printify product's size/color picker, or a meetup
 * item's Buy now / request panel, whichever the post sells.
 */
export default function BuyPanel({ postId, fallbackPrice }: BuyPanelProps) {
  const [listing, setListing] = useState<ShopListing | MeetupListing | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    getShopListing(postId)
      .then((result) => {
        if (!cancelled) setListing(result);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('[BuyPanel] Failed to load listing:', err);
        setListing(null);
      });
    return () => {
      cancelled = true;
    };
  }, [postId]);

  if (listing === undefined) {
    return (
      <button type="button" disabled className={buttonClass}>
        Loading…
        {fallbackPrice && <span className="text-sm font-medium text-white/80">{fallbackPrice}</span>}
      </button>
    );
  }

  if (listing?.type === 'meetup') {
    return <MeetupPanel postId={postId} listing={listing} />;
  }

  if (!listing || listing.variants.length === 0) {
    return (
      <button type="button" disabled className={buttonClass} aria-label="Not available yet">
        Coming soon
      </button>
    );
  }

  return <PrintifyBuy postId={postId} listing={listing} />;
}

/**
 * Size/color picker and Buy button for a Printify product.
 *
 * Only sellable variants are in the listing. The price shown here is for the
 * buyer's information only: the backend re-reads it from Printify when it
 * opens Stripe Checkout.
 */
function PrintifyBuy({ postId, listing }: { postId: string; listing: ShopListing }) {
  const [selected, setSelected] = useState<number[]>(listing.variants[0]?.options ?? []);
  const [quantity, setQuantity] = useState(1);
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const variant: ShopVariant | undefined = useMemo(
    () => listing.variants.find((v) => v.options.length === selected.length && v.options.every((id) => selected.includes(id))),
    [listing, selected],
  );

  // Picking a value keeps as many of the other choices as some variant allows,
  // so choosing a color never strands the buyer on a size it doesn't come in.
  const pick = (valueId: number) => {
    const candidates = listing.variants.filter((v) => v.options.includes(valueId));
    const best = candidates
      .map((v) => ({ v, keep: v.options.filter((id) => selected.includes(id)).length }))
      .sort((a, b) => b.keep - a.keep)[0];
    if (best) setSelected(best.v.options);
  };

  const isValueSellable = (valueId: number) => listing.variants.some((v) => v.options.includes(valueId));

  const handleBuy = async () => {
    if (!variant) return;
    setIsRedirecting(true);
    setError(null);
    try {
      window.location.href = await startCheckout(postId, variant.id, quantity);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start checkout');
      setIsRedirecting(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* An option with one sellable value (e.g. a product made in a single
          color) is already selected, so there's nothing to pick. */}
      {listing.options
        .filter((option) => option.values.filter((value) => isValueSellable(value.id)).length > 1)
        .map((option) => (
        <div key={option.name}>
          <p className="text-xs uppercase tracking-wider text-white/50 mb-2">{option.name}</p>
          <div className="flex flex-wrap gap-2">
            {option.values.map((value) => {
              const isSelected = selected.includes(value.id);
              const swatch = option.type === 'color' ? value.colors[0] : undefined;
              return (
                <button
                  key={value.id}
                  type="button"
                  disabled={!isValueSellable(value.id)}
                  onClick={() => pick(value.id)}
                  className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm border transition-colors disabled:opacity-30 ${isSelected
                    ? 'border-white/80 bg-white/20 text-white'
                    : 'border-white/20 text-white/70 hover:border-white/50 hover:text-white'}`}
                >
                  {swatch && <span className="w-3.5 h-3.5 rounded-full border border-white/40" style={{ backgroundColor: swatch }} />}
                  {value.title}
                </button>
              );
            })}
          </div>
        </div>
      ))}

      <div className="flex items-center gap-3">
        <p className="text-xs uppercase tracking-wider text-white/50">Qty</p>
        <div className="inline-flex items-center rounded-lg border border-white/20">
          <button
            type="button"
            onClick={() => setQuantity((q) => Math.max(1, q - 1))}
            disabled={quantity <= 1}
            className="p-2 text-white/70 hover:text-white disabled:opacity-30"
            aria-label="Decrease quantity"
          >
            <Minus className="w-4 h-4" />
          </button>
          <span className="w-8 text-center text-sm text-white">{quantity}</span>
          <button
            type="button"
            onClick={() => setQuantity((q) => Math.min(MAX_QUANTITY, q + 1))}
            disabled={quantity >= MAX_QUANTITY}
            className="p-2 text-white/70 hover:text-white disabled:opacity-30"
            aria-label="Increase quantity"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="space-y-2">
        <button type="button" onClick={handleBuy} disabled={!variant || isRedirecting} className={buttonClass}>
          {isRedirecting ? 'Opening checkout…' : 'Buy'}
          {variant && !isRedirecting && (
            <span className="text-sm font-medium text-white/80">{formatCents(variant.price_cents * quantity)}</span>
          )}
        </button>
        {variant && listing.shipping_cents != null && (
          <p className="text-xs text-white/50">
            + {formatCents(listing.shipping_cents)} shipping{quantity > 1 ? ' for the first item' : ''} · ships to {listing.ships_to?.join(', ') || 'US'}
          </p>
        )}
        {!variant && <p className="text-xs text-white/50">That combination isn&apos;t available.</p>}
        {error && <p className="text-sm text-red-300">{error}</p>}
      </div>
    </div>
  );
}
