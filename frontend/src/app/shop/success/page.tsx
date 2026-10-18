'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { formatCents, getCheckoutStatus, type ShopOrderStatus } from '@/lib/api';

// Stripe redirects here the moment the card is charged, but the order is only
// confirmed once Stripe's webhook reaches the backend -- usually a second or
// two later. Poll briefly until it has.
const POLL_MS = 2000;
const MAX_POLLS = 15;

function OrderConfirmation() {
  const sessionId = useSearchParams().get('session_id');
  const [order, setOrder] = useState<ShopOrderStatus | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let polls = 0;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await getCheckoutStatus(sessionId);
        setOrder(result);
        if (result.status !== 'pending' || ++polls >= MAX_POLLS) return;
      } catch {
        if (++polls >= MAX_POLLS) {
          setFailed(true);
          return;
        }
      }
      timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => clearTimeout(timer);
  }, [sessionId]);

  const confirmed = order && order.status !== 'pending' && order.status !== 'expired';

  return (
    <div className="bg-white/5 border border-white/10 rounded-2xl p-6 backdrop-blur space-y-4">
      {confirmed ? (
        <>
          <h1 className="text-3xl font-bold text-white">Thank you!</h1>
          <p className="text-white/70">
            Your order for{' '}
            <span className="text-white">
              {order.quantity > 1 ? `${order.quantity} × ` : ''}{order.title ?? 'your item'}
              {order.variant_title ? ` (${order.variant_title})` : ''}
            </span>{' '}
            is confirmed{order.amount_total_cents != null ? `: ${formatCents(order.amount_total_cents, order.currency)}` : ''}.
          </p>
          <p className="text-white/60 text-sm">
            A receipt is on its way to your email. Each piece is printed to order, so it usually ships within a few business days.
          </p>
        </>
      ) : failed || !sessionId ? (
        <>
          <h1 className="text-3xl font-bold text-white">Thanks for your order</h1>
          <p className="text-white/70">
            We couldn&apos;t load the details here, but if your card was charged your order went through and a receipt is on its way to your email.
          </p>
        </>
      ) : (
        <>
          <h1 className="text-3xl font-bold text-white">Confirming your order…</h1>
          <p className="text-white/60">This only takes a moment.</p>
        </>
      )}
      <Link href="/shop" className="inline-block text-sm text-white/70 underline hover:text-white">
        Back to the shop
      </Link>
    </div>
  );
}

export default function ShopSuccessPage() {
  return (
    <div className="min-h-screen bg-black p-8">
      <div className="max-w-2xl mx-auto pt-16">
        <Suspense fallback={null}>
          <OrderConfirmation />
        </Suspense>
      </div>
    </div>
  );
}
