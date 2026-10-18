'use client';

import { useEffect, useMemo, useState } from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import {
  formatCents,
  getPrintifyProduct,
  listPrintifyProducts,
  updatePrintifyVariants,
  type PrintifyProductSummary,
  type ShopListing,
} from '@/lib/api';

interface PrintifyProductPanelProps {
  productId: string | null;
  onChange: (productId: string | null) => void;
  authToken: string | null;
}

type Draft = Record<number, { price: string; enabled: boolean }>;

/**
 * Admin: link a shop post to a Printify product and price its variants.
 *
 * Printify is the source of truth for prices. Edits here are written straight
 * to Printify with their own Save button, separate from saving the post: the
 * post only stores which product it sells.
 */
export default function PrintifyProductPanel({ productId, onChange, authToken }: PrintifyProductPanelProps) {
  const [products, setProducts] = useState<PrintifyProductSummary[] | null>(null);
  const [product, setProduct] = useState<ShopListing | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadProducts = () => {
    if (!authToken) return;
    listPrintifyProducts(authToken)
      .then(setProducts)
      .catch((err) => setError(err.message));
  };

  useEffect(loadProducts, [authToken]);

  const applyProduct = (listing: ShopListing) => {
    setProduct(listing);
    setDraft(Object.fromEntries(listing.variants.map((v) => [
      v.id,
      { price: (v.price_cents / 100).toFixed(2), enabled: Boolean(v.is_enabled) },
    ])));
  };

  useEffect(() => {
    setProduct(null);
    setNotice(null);
    if (!productId || !authToken) return;
    setIsLoading(true);
    setError(null);
    getPrintifyProduct(productId, authToken)
      .then(applyProduct)
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }, [productId, authToken]);

  const changes = useMemo(() => {
    if (!product) return [];
    return product.variants.flatMap((v) => {
      const d = draft[v.id];
      if (!d) return [];
      const priceCents = Math.round(parseFloat(d.price) * 100);
      const change: { id: number; price_cents?: number; is_enabled?: boolean } = { id: v.id };
      if (Number.isFinite(priceCents) && priceCents !== v.price_cents) change.price_cents = priceCents;
      if (d.enabled !== Boolean(v.is_enabled)) change.is_enabled = d.enabled;
      return Object.keys(change).length > 1 ? [change] : [];
    });
  }, [product, draft]);

  const setAllPrices = (value: string) => {
    setDraft((prev) => Object.fromEntries(Object.entries(prev).map(([id, d]) => [id, { ...d, price: value }])));
  };

  const handleSave = async () => {
    if (!product || !authToken || changes.length === 0) return;
    setIsSaving(true);
    setError(null);
    try {
      applyProduct(await updatePrintifyVariants(product.product_id, changes, authToken));
      setNotice('Saved to Printify.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save prices');
    } finally {
      setIsSaving(false);
    }
  };

  const inputClass = 'p-2 border border-white/30 bg-white/10 text-white rounded-lg focus:ring-2 focus:ring-white/50 focus:border-white/50';

  return (
    <div className="space-y-4 p-4 bg-white/5 rounded-xl border border-white/10">
      <div>
        <label className="block text-sm font-medium text-white/90 mb-2">Printify product</label>
        <div className="flex gap-2">
          <select
            value={productId ?? ''}
            onChange={(e) => onChange(e.target.value || null)}
            className={`flex-1 min-w-0 ${inputClass} p-3`}
          >
            <option value="" className="bg-neutral-900">Not linked (not for sale)</option>
            {productId && !products?.some((p) => p.id === productId) && (
              <option value={productId} className="bg-neutral-900">{productId}</option>
            )}
            {products?.map((p) => (
              <option key={p.id} value={p.id} className="bg-neutral-900">
                {p.title}{p.min_price_cents != null ? ` · from ${formatCents(p.min_price_cents)}` : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={loadProducts}
            className="p-3 text-white/70 hover:text-white bg-white/10 hover:bg-white/20 border border-white/30 rounded-lg transition-colors"
            aria-label="Reload Printify products"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
        <p className="mt-2 text-xs text-white/50">
          Design the product in{' '}
          <a href="https://printify.com/app/products" target="_blank" rel="noreferrer" className="underline inline-flex items-center gap-1">
            Printify <ExternalLink className="w-3 h-3" />
          </a>
          , then link it here. The link is saved with the post.
        </p>
      </div>

      {isLoading && <p className="text-sm text-white/60">Loading variants…</p>}

      {product && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-white/90">Prices</p>
            <label className="flex items-center gap-2 text-xs text-white/60">
              Set all to $
              <input
                type="number"
                step="0.01"
                min="0"
                placeholder="—"
                onChange={(e) => e.target.value && setAllPrices(e.target.value)}
                className={`w-20 ${inputClass}`}
              />
            </label>
          </div>
          <div className="max-h-72 overflow-y-auto rounded-lg border border-white/10">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-neutral-900/90 text-white/50 text-xs uppercase tracking-wider">
                <tr>
                  <th className="p-2 text-left">Sell</th>
                  <th className="p-2 text-left">Variant</th>
                  <th className="p-2 text-right">Cost</th>
                  <th className="p-2 text-right">Price</th>
                  <th className="p-2 text-right">Profit</th>
                </tr>
              </thead>
              <tbody>
                {product.variants.map((v) => {
                  const d = draft[v.id];
                  const priceCents = Math.round(parseFloat(d?.price ?? '') * 100);
                  const profit = Number.isFinite(priceCents) && v.cost_cents != null ? priceCents - v.cost_cents : null;
                  return (
                    <tr key={v.id} className={`border-t border-white/5 ${d?.enabled ? '' : 'opacity-50'}`}>
                      <td className="p-2">
                        <input
                          type="checkbox"
                          checked={d?.enabled ?? false}
                          onChange={(e) => setDraft((prev) => ({ ...prev, [v.id]: { ...prev[v.id], enabled: e.target.checked } }))}
                          className="w-4 h-4 accent-white"
                        />
                      </td>
                      <td className="p-2 text-white/80">
                        {v.title}
                        {v.is_available === false && <span className="ml-2 text-xs text-amber-300">out of stock</span>}
                      </td>
                      <td className="p-2 text-right text-white/60">{v.cost_cents != null ? formatCents(v.cost_cents) : '—'}</td>
                      <td className="p-2 text-right">
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={d?.price ?? ''}
                          onChange={(e) => setDraft((prev) => ({ ...prev, [v.id]: { ...prev[v.id], price: e.target.value } }))}
                          className={`w-24 text-right ${inputClass}`}
                        />
                      </td>
                      <td className={`p-2 text-right ${profit != null && profit < 0 ? 'text-red-300' : 'text-white/80'}`}>
                        {profit != null ? formatCents(profit) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-white/50">
            Cost is what Printify charges you to print it. Shipping is charged to the buyer on top
            {product.shipping_cents != null ? ` (${formatCents(product.shipping_cents)} for the first item)` : ''}.
            Stripe takes its fee out of the total.
          </p>
          <div className="flex items-center justify-end gap-3">
            {notice && changes.length === 0 && <span className="text-xs text-green-300">{notice}</span>}
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving || changes.length === 0}
              className="px-4 py-2 text-sm font-medium text-white bg-white/20 hover:bg-white/30 border border-white/30 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSaving ? 'Saving…' : changes.length ? `Save ${changes.length} change${changes.length === 1 ? '' : 's'} to Printify` : 'No price changes'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-500/20 border border-red-400/50 text-red-200 rounded-lg text-sm">{error}</div>
      )}
    </div>
  );
}
