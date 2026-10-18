'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, Copy, Mail, Phone, RefreshCw } from 'lucide-react';
import { useAuth } from '@/providers/AuthProvider';
import {
  completeShopOrder,
  createOfferPayLink,
  declineOffer,
  formatCents,
  listShopOffers,
  listShopOrders,
  markOfferPaidCash,
  type ShopOfferRow,
  type ShopOrderRow,
} from '@/lib/api';

const smallButton =
  'px-3 py-1.5 text-sm font-medium text-white bg-white/10 hover:bg-white/20 border border-white/30 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed';

function when(iso: string | null): string {
  if (!iso) return '';
  // Stored as naive UTC.
  const date = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/** The shop's back office: requests and offers on meetup items, and orders. */
export default function ShopAdmin() {
  const { user, token, loading } = useAuth();
  const [offers, setOffers] = useState<ShopOfferRow[] | null>(null);
  const [orders, setOrders] = useState<ShopOrderRow[] | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    Promise.all([listShopOffers(token, showClosed), listShopOrders(token)])
      .then(([o, r]) => {
        if (cancelled) return;
        setOffers(o);
        setOrders(r);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load the shop');
      });
    return () => {
      cancelled = true;
    };
  }, [token, showClosed, reloadKey]);

  if (loading) return <Shell><p className="text-white/60">Checking sign-in…</p></Shell>;
  if (!user || !token) return <Shell><p className="text-white/60">Sign in as admin (Settings) to see the shop.</p></Shell>;

  const openCount = offers?.filter((o) => o.status === 'new').length ?? 0;

  return (
    <Shell>
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold text-white">Shop</h1>
          <p className="text-white/60 mt-2">Requests on meetup items, and every paid order.</p>
        </div>
        <button type="button" onClick={load} className={`${smallButton} inline-flex items-center gap-2`}>
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {error && <div className="p-3 bg-red-500/20 border border-red-400/50 text-red-200 rounded-lg text-sm">{error}</div>}

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-xl font-semibold text-white">
            Requests &amp; offers{openCount > 0 && <span className="ml-2 text-sm font-normal text-amber-300">{openCount} new</span>}
          </h2>
          <label className="flex items-center gap-2 text-sm text-white/60">
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} className="accent-white" />
            Show declined &amp; paid
          </label>
        </div>
        {offers === null ? (
          <p className="text-white/50 text-sm">Loading…</p>
        ) : offers.length === 0 ? (
          <p className="text-white/50 text-sm">No open requests.</p>
        ) : (
          <div className="space-y-3">
            {offers.map((offer) => (
              <OfferCard key={offer.id} offer={offer} token={token} onChange={load} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold text-white">Orders</h2>
        {orders === null ? (
          <p className="text-white/50 text-sm">Loading…</p>
        ) : orders.length === 0 ? (
          <p className="text-white/50 text-sm">No orders yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-white/10">
            <table className="w-full text-sm">
              <thead className="bg-white/5 text-white/50 text-xs uppercase tracking-wider">
                <tr>
                  <th className="p-3 text-left">When</th>
                  <th className="p-3 text-left">Item</th>
                  <th className="p-3 text-left">Paid</th>
                  <th className="p-3 text-left">Buyer</th>
                  <th className="p-3 text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <OrderRow key={order.id} order={order} token={token} onChange={load} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-black px-4 py-8 sm:p-8">
      <div className="max-w-5xl mx-auto space-y-8">{children}</div>
    </div>
  );
}

function Contact({ email, phone }: { email: string | null; phone: string | null }) {
  return (
    <span className="flex flex-wrap gap-x-4 gap-y-1">
      {phone && (
        <a href={`sms:${phone}`} className="inline-flex items-center gap-1 text-white/80 hover:text-white underline">
          <Phone className="w-3.5 h-3.5" /> {phone}
        </a>
      )}
      {email && (
        <a href={`mailto:${email}`} className="inline-flex items-center gap-1 text-white/80 hover:text-white underline break-all">
          <Mail className="w-3.5 h-3.5" /> {email}
        </a>
      )}
    </span>
  );
}

function OfferCard({ offer, token, onChange }: { offer: ShopOfferRow; token: string; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [payLink, setPayLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const unit = offer.offer_cents ?? offer.listed_price_cents;
  const isOpen = offer.status === 'new' || offer.status === 'accepted';

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  };

  const makeLink = () => run(async () => {
    const { url } = await createOfferPayLink(offer.id, token);
    setPayLink(url);
    setCopied(false);
  });

  const copy = async () => {
    if (!payLink) return;
    try {
      await navigator.clipboard.writeText(payLink);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={`p-4 rounded-xl border bg-white/5 space-y-3 ${offer.status === 'new' ? 'border-amber-300/40' : 'border-white/10'}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-white font-medium">
          {offer.title ?? 'Deleted item'}
          {offer.quantity > 1 && <span className="text-white/60"> × {offer.quantity}</span>}
        </p>
        <span className="text-xs text-white/50">{when(offer.created_at)} · {offer.status}</span>
      </div>

      <p className="text-sm text-white/80">
        {offer.offer_cents != null ? (
          <>
            Offers <span className="text-white font-semibold">{formatCents(offer.offer_cents)}</span>
            {offer.listed_price_cents != null && <span className="text-white/50"> (listed {formatCents(offer.listed_price_cents)})</span>}
          </>
        ) : (
          <>At the listed price{unit != null && <> of <span className="text-white font-semibold">{formatCents(unit)}</span></>}</>
        )}
        {offer.quantity > 1 && unit != null && <span className="text-white/50"> · {formatCents(unit * offer.quantity)} total</span>}
        <span className="text-white/50"> · {offer.available} in stock</span>
      </p>

      <div className="text-sm">
        {offer.name && <span className="text-white/90 mr-4">{offer.name}</span>}
        <Contact email={offer.email} phone={offer.phone} />
      </div>
      {offer.message && <p className="text-sm text-white/70 italic whitespace-pre-wrap">“{offer.message}”</p>}

      {isOpen && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button type="button" onClick={makeLink} disabled={busy} className={smallButton}>
            {offer.pay_link_expires_at ? 'New pay link' : 'Send pay link'}
          </button>
          <button
            type="button"
            onClick={() => run(async () => { await markOfferPaidCash(offer.id, token); onChange(); })}
            disabled={busy}
            className={smallButton}
          >
            Paid in cash
          </button>
          <button
            type="button"
            onClick={() => run(async () => { await declineOffer(offer.id, token); onChange(); })}
            disabled={busy}
            className={`${smallButton} text-white/60`}
          >
            Decline
          </button>
          {offer.pay_link_expires_at && !payLink && (
            <span className="text-xs text-white/50">A pay link is open until {when(offer.pay_link_expires_at)}</span>
          )}
        </div>
      )}

      {payLink && (
        <div className="flex items-center gap-2 p-2 rounded-lg bg-black/40 border border-white/10">
          <input readOnly value={payLink} className="flex-1 min-w-0 bg-transparent text-xs text-white/80 outline-none" onFocus={(e) => e.target.select()} />
          <button type="button" onClick={copy} className={`${smallButton} inline-flex items-center gap-1`}>
            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />} {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      )}
      {payLink && <p className="text-xs text-white/50">Text or email this to the buyer. It holds the item for 23 hours.</p>}
      {error && <p className="text-sm text-red-300">{error}</p>}
    </div>
  );
}

function OrderRow({ order, token, onChange }: { order: ShopOrderRow; token: string; onChange: () => void }) {
  const [busy, setBusy] = useState(false);

  const status =
    order.fulfillment === 'printify'
      ? order.printify_status ?? order.status
      : order.status === 'paid' ? 'paid, to hand over' : order.status;

  const handOver = async () => {
    setBusy(true);
    try {
      await completeShopOrder(order.id, token);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className="border-t border-white/5 align-top">
      <td className="p-3 text-white/60 whitespace-nowrap">{when(order.created_at)}</td>
      <td className="p-3 text-white/90">
        {order.title ?? '—'}
        {order.variant_title && <span className="text-white/50"> ({order.variant_title})</span>}
        {order.quantity > 1 && <span className="text-white/50"> × {order.quantity}</span>}
        <span className="block text-xs text-white/40">{order.fulfillment === 'printify' ? 'Printify' : 'Meetup'}</span>
      </td>
      <td className="p-3 text-white/90 whitespace-nowrap">
        {order.amount_total_cents != null ? formatCents(order.amount_total_cents) : '—'}
        <span className="block text-xs text-white/40">
          {order.payment_method === 'cash' ? 'Cash' : 'Card'}
          {!order.livemode && ' · test'}
        </span>
      </td>
      <td className="p-3 text-sm"><Contact email={order.email} phone={order.phone} /></td>
      <td className="p-3 text-white/80">
        <span className="whitespace-nowrap">{status}</span>
        {order.tracking_url && (
          <a href={order.tracking_url} target="_blank" rel="noreferrer" className="block text-xs underline text-white/60">Tracking</a>
        )}
        {order.fulfillment === 'meetup' && order.status === 'paid' && (
          <button type="button" onClick={handOver} disabled={busy} className={`${smallButton} mt-2 block`}>
            Handed over
          </button>
        )}
        {order.error && <span className="block text-xs text-amber-300 mt-1">{order.error}</span>}
      </td>
    </tr>
  );
}
