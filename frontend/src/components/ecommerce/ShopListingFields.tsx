'use client';

import PrintifyProductPanel from './PrintifyProductPanel';

export type ListingType = 'printify' | 'meetup';

export interface ShopListingValue {
  listing_type: ListingType;
  printify_product_id: string | null;
  /** Meetup asking price, in dollars. */
  price: number | null;
  stock: number | null;
  accepts_offers: boolean;
  fb_marketplace_url: string | null;
}

interface ShopListingFieldsProps {
  value: ShopListingValue;
  onChange: (patch: Partial<ShopListingValue>) => void;
  authToken: string | null;
}

const inputClass =
  'w-full p-3 border border-white/30 bg-white/10 text-white rounded-lg focus:ring-2 focus:ring-white/50 focus:border-white/50 placeholder-white/50';

/** What's wrong with a shop listing before it can be saved, or null. */
export function shopListingError(value: ShopListingValue): string | null {
  if (value.listing_type === 'printify') {
    return value.printify_product_id ? null : 'Pick the Printify product this post sells.';
  }
  if (value.price == null || !(value.price > 0)) return 'Set an asking price.';
  if (value.stock == null || value.stock < 0) return 'Set how many you have.';
  if (value.fb_marketplace_url && !/^https?:\/\//i.test(value.fb_marketplace_url)) {
    return 'The Facebook link should start with https://';
  }
  return null;
}

/** The listing fields as a post create/update payload. */
export function shopListingPayload(value: ShopListingValue) {
  if (value.listing_type === 'printify') {
    // The price comes from Printify (the backend fills it in on save).
    return { listing_type: 'printify' as const, printify_product_id: value.printify_product_id };
  }
  return {
    listing_type: 'meetup' as const,
    printify_product_id: null,
    price: value.price,
    stock: value.stock,
    accepts_offers: value.accepts_offers,
    fb_marketplace_url: value.fb_marketplace_url?.trim() || null,
  };
}

/**
 * How a shop post is sold: a Printify product (printed and shipped for you)
 * or a meetup item (sold in person, often also on Facebook Marketplace).
 */
export default function ShopListingFields({ value, onChange, authToken }: ShopListingFieldsProps) {
  const options: { id: ListingType; label: string; hint: string }[] = [
    { id: 'printify', label: 'Printify', hint: 'Printed and shipped for you' },
    { id: 'meetup', label: 'Meetup', hint: 'You hand it over in person' },
  ];

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-white/90 mb-2">How it&apos;s sold</label>
        <div className="grid grid-cols-2 gap-2">
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => onChange({ listing_type: option.id })}
              className={`p-3 rounded-lg border text-left transition-colors ${value.listing_type === option.id
                ? 'border-white/70 bg-white/15'
                : 'border-white/20 bg-white/5 hover:border-white/40'}`}
            >
              <span className="block text-sm font-medium text-white">{option.label}</span>
              <span className="block text-xs text-white/50">{option.hint}</span>
            </button>
          ))}
        </div>
      </div>

      {value.listing_type === 'printify' ? (
        <PrintifyProductPanel
          productId={value.printify_product_id}
          onChange={(id) => onChange({ printify_product_id: id })}
          authToken={authToken}
        />
      ) : (
        <div className="space-y-4 p-4 bg-white/5 rounded-xl border border-white/10">
          <div className="grid grid-cols-2 gap-4">
            <label className="block">
              <span className="block text-sm font-medium text-white/90 mb-2">Price (USD)</span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={value.price ?? ''}
                onChange={(e) => onChange({ price: e.target.value === '' ? null : parseFloat(e.target.value) })}
                className={inputClass}
                placeholder="e.g. 40"
              />
            </label>
            <label className="block">
              <span className="block text-sm font-medium text-white/90 mb-2">In stock</span>
              <input
                type="number"
                min="0"
                step="1"
                value={value.stock ?? ''}
                onChange={(e) => onChange({ stock: e.target.value === '' ? null : parseInt(e.target.value, 10) })}
                className={inputClass}
                placeholder="1"
              />
            </label>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex-1">
              <p className="text-white font-medium">Make an offer</p>
              <p className="text-sm text-white/60">Buyers can name their own price</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={value.accepts_offers}
              onClick={() => onChange({ accepts_offers: !value.accepts_offers })}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 ${value.accepts_offers ? 'bg-green-500' : 'bg-white/20'}`}
            >
              <span className={`${value.accepts_offers ? 'translate-x-6' : 'translate-x-1'} inline-block h-4 w-4 transform rounded-full bg-white transition-transform`} />
            </button>
          </div>

          <label className="block">
            <span className="block text-sm font-medium text-white/90 mb-2">Facebook Marketplace link (optional)</span>
            <input
              type="url"
              value={value.fb_marketplace_url ?? ''}
              onChange={(e) => onChange({ fb_marketplace_url: e.target.value || null })}
              className={inputClass}
              placeholder="https://www.facebook.com/marketplace/item/…"
            />
          </label>
          <p className="text-xs text-white/50">
            Facebook doesn&apos;t let other sites read your listings, so when it sells there, set stock to 0 here; when it sells here, mark it sold on Facebook.
          </p>
        </div>
      )}
    </div>
  );
}
