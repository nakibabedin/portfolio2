'use client';

import { useState } from 'react';
import { ExternalLink, MapPin, Minus, Plus } from 'lucide-react';
import { formatCents, startCheckout, submitOffer, type MeetupListing } from '@/lib/api';

interface MeetupPanelProps {
  postId: string;
  listing: MeetupListing;
}

const buttonClass =
  'inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-white font-semibold border border-white/20 shadow-md shadow-black/30 transition-all duration-200 w-full md:w-auto backdrop-blur-sm hover:border-white/50 hover:shadow-xl hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent';
const inputClass =
  'w-full p-2.5 border border-white/30 bg-white/10 text-white rounded-lg focus:ring-2 focus:ring-white/50 focus:border-white/50 placeholder-white/40 text-sm';

/**
 * Buying an item sold in person: pay online now, or send a request (with an
 * offer, if the item takes them) and settle at a public meetup.
 */
export default function MeetupPanel({ postId, listing }: MeetupPanelProps) {
  const maxQuantity = Math.min(listing.available, listing.max_quantity);
  const [quantity, setQuantity] = useState(1);
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRequest, setShowRequest] = useState(false);

  const soldOut = listing.available <= 0;
  const canBuyNow = !soldOut && listing.price_cents != null;

  const handleBuy = async () => {
    setIsRedirecting(true);
    setError(null);
    try {
      window.location.href = await startCheckout(postId, null, quantity);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start checkout');
      setIsRedirecting(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-2xl font-semibold text-white">
          {listing.price_cents != null ? formatCents(listing.price_cents) : 'Make an offer'}
        </p>
        <p className={`text-sm ${soldOut ? 'text-red-300' : 'text-white/60'}`}>
          {soldOut ? 'Sold out' : `${listing.available} available`}
        </p>
      </div>

      <p className="flex items-center gap-2 text-xs text-white/50">
        <MapPin className="w-3.5 h-3.5" />
        Pickup only, at a public meetup
      </p>

      {!soldOut && maxQuantity > 1 && (
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
              onClick={() => setQuantity((q) => Math.min(maxQuantity, q + 1))}
              disabled={quantity >= maxQuantity}
              className="p-2 text-white/70 hover:text-white disabled:opacity-30"
              aria-label="Increase quantity"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {!soldOut && (
        <div className="flex flex-col sm:flex-row gap-2">
          {canBuyNow && (
            <button type="button" onClick={handleBuy} disabled={isRedirecting} className={buttonClass}>
              {isRedirecting ? 'Opening checkout…' : 'Buy now'}
              {!isRedirecting && (
                <span className="text-sm font-medium text-white/80">{formatCents(listing.price_cents! * quantity)}</span>
              )}
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowRequest((v) => !v)}
            className={`${buttonClass} font-medium ${showRequest ? 'bg-white/15' : ''}`}
          >
            {listing.accepts_offers ? 'Make an offer' : 'Pay in person'}
          </button>
        </div>
      )}

      {error && <p className="text-sm text-red-300">{error}</p>}

      {showRequest && !soldOut && (
        <RequestForm postId={postId} listing={listing} quantity={quantity} />
      )}

      {listing.fb_marketplace_url && (
        <a
          href={listing.fb_marketplace_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-white/60 underline hover:text-white"
        >
          Also on Facebook Marketplace <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </div>
  );
}

function RequestForm({ postId, listing, quantity }: { postId: string; listing: MeetupListing; quantity: number }) {
  const [offer, setOffer] = useState('');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [website, setWebsite] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) {
      setError('Leave an email so you can be reached.');
      return;
    }
    let offerCents: number | undefined;
    if (listing.accepts_offers) {
      offerCents = Math.round(parseFloat(offer) * 100);
      if (!Number.isFinite(offerCents) || offerCents <= 0) {
        setError('Enter your offer in dollars, like 40.');
        return;
      }
    }
    setIsSending(true);
    setError(null);
    try {
      await submitOffer({
        post_id: postId,
        quantity,
        offer_cents: offerCents,
        name: name.trim() || undefined,
        phone: phone.trim() || undefined,
        email: email.trim(),
        message: message.trim() || undefined,
        website,
      });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send your request');
    } finally {
      setIsSending(false);
    }
  };

  if (sent) {
    return (
      <div className="p-4 rounded-xl border border-white/15 bg-white/5 text-sm text-white/80">
        Sent! You&apos;ll hear back soon to set up a meetup. You can pay then, in cash or online.
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 p-4 rounded-xl border border-white/15 bg-white/5">
      <p className="text-sm text-white/70">
        {listing.accepts_offers
          ? 'Name your price. If it works, you can pay in cash at the meetup or online.'
          : 'Reserve it and pay at the meetup, in cash or online.'}
      </p>
      {listing.accepts_offers && (
        <label className="block">
          <span className="block text-xs text-white/50 mb-1">Your offer</span>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/50 text-sm">$</span>
            <input
              type="number"
              min="1"
              step="0.01"
              inputMode="decimal"
              required
              value={offer}
              onChange={(e) => setOffer(e.target.value)}
              placeholder={listing.price_cents != null ? (listing.price_cents / 100).toFixed(2) : ''}
              className={`${inputClass} pl-7`}
            />
          </div>
          {quantity > 1 && <span className="block text-xs text-white/40 mt-1">Per item, for {quantity} items.</span>}
        </label>
      )}
      <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (optional)" className={inputClass} maxLength={255} />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" className={inputClass} maxLength={255} />
        <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Phone (optional)" className={inputClass} maxLength={64} />
      </div>
      <textarea
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="Anything else? (optional)"
        rows={2}
        maxLength={2000}
        className={`${inputClass} resize-none`}
      />
      {/* Honeypot: hidden from people, filled by bots. */}
      <input
        type="text"
        value={website}
        onChange={(e) => setWebsite(e.target.value)}
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        className="hidden"
        name="website"
      />
      {error && <p className="text-sm text-red-300">{error}</p>}
      <button type="submit" disabled={isSending} className={buttonClass}>
        {isSending ? 'Sending…' : listing.accepts_offers ? 'Send offer' : 'Send request'}
      </button>
    </form>
  );
}
