'use client';

import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { getInstagramLocations, type InstagramDetails, type InstagramLocation } from '@/lib/api';

/** Pre-filled on every new photo going to Instagram; edit them per post. */
export const DEFAULT_INSTAGRAM_HASHTAGS = ['photography', 'sonynex5n', 'lightroom'];

// Instagram's own limits.
const MAX_HASHTAGS = 30;
const MAX_COLLABORATORS = 3;

/**
 * The form's copy of the details. The location is kept as typed (a Facebook
 * link or a bare id) and only turned into an id when the post is saved, so a
 * link without one can be flagged instead of silently dropped.
 */
export interface InstagramDetailsValue {
  hashtags: string[];
  collaborators: string[];
  locationName: string;
  locationInput: string;
}

export function instagramDetailsValue(post?: Partial<InstagramDetails> | null): InstagramDetailsValue {
  const hashtags = post?.instagram_hashtags ?? [];
  return {
    hashtags: hashtags.length ? hashtags : DEFAULT_INSTAGRAM_HASHTAGS,
    collaborators: post?.instagram_collaborators ?? [],
    locationName: post?.instagram_location_name ?? '',
    locationInput: post?.instagram_location_id ?? '',
  };
}

/**
 * The page id in a Facebook place page link, or a bare id. Handles
 * facebook.com/pages/Name/123…, facebook.com/Name-123…, and profile.php?id=123….
 * A vanity link (facebook.com/SomePlace) has no id in it.
 */
export function parseFacebookPageId(input: string): string | null {
  const text = input.trim();
  if (/^\d{5,20}$/.test(text)) return text;
  const idParam = text.match(/[?&]id=(\d{5,20})/);
  if (idParam) return idParam[1];
  const trailing = text.split(/[?#]/)[0].replace(/\/+$/, '').match(/(?:^|[/-])(\d{5,20})$/);
  return trailing ? trailing[1] : null;
}

/** Instagram ends a hashtag at the first character that isn't a letter, digit or underscore. */
function cleanHashtag(tag: string): string {
  return tag.replace(/[^\p{L}\p{N}_]/gu, '');
}

function cleanUsername(name: string): string {
  return name.trim().replace(/^@/, '').replace(/^https?:\/\/(www\.)?instagram\.com\//i, '').replace(/\/.*$/, '').toLowerCase();
}

/** What's wrong with the details before they can be saved, or null. */
export function instagramDetailsError(value: InstagramDetailsValue): string | null {
  if (value.locationInput.trim() && !parseFacebookPageId(value.locationInput)) {
    return "The location link has no Facebook page id in it. Paste the page id from the place's Facebook page (About → Page transparency).";
  }
  if (value.locationInput.trim() && !value.locationName.trim()) {
    return 'Give the location a name.';
  }
  return null;
}

/** The details as a post create/update payload. */
export function instagramDetailsPayload(value: InstagramDetailsValue): InstagramDetails {
  const locationId = parseFacebookPageId(value.locationInput);
  return {
    instagram_hashtags: value.hashtags,
    instagram_collaborators: value.collaborators,
    instagram_location_id: locationId,
    instagram_location_name: locationId ? value.locationName.trim() || null : null,
  };
}

const inputClass =
  'w-full p-3 border border-white/30 bg-white/10 text-white rounded-lg focus:ring-2 focus:ring-white/50 focus:border-white/50 placeholder-white/50';

interface ChipInputProps {
  label: string;
  hint: string;
  values: string[];
  onChange: (values: string[]) => void;
  clean: (raw: string) => string;
  prefix: string;
  max: number;
  placeholder: string;
  isValid?: (value: string) => boolean;
}

/** Type and press Enter, comma or space to add; Backspace on empty removes the last. */
function ChipInput({ label, hint, values, onChange, clean, prefix, max, placeholder, isValid }: ChipInputProps) {
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);

  const commit = (raw: string) => {
    const next = [...values];
    for (const piece of raw.split(/[\s,]+/)) {
      const item = clean(piece);
      if (!item) continue;
      if (isValid && !isValid(item)) {
        setError(`"${item}" doesn't look right`);
        continue;
      }
      if (next.some((v) => v.toLowerCase() === item.toLowerCase())) continue;
      if (next.length >= max) {
        setError(`Instagram allows ${max} at most`);
        break;
      }
      next.push(item);
    }
    onChange(next);
    setDraft('');
  };

  return (
    <div>
      <label className="block text-sm font-medium text-white/90 mb-2">{label}</label>
      <div className="flex flex-wrap items-center gap-2 p-2 border border-white/30 bg-white/10 rounded-lg focus-within:ring-2 focus-within:ring-white/50">
        {values.map((value) => (
          <span key={value} className="inline-flex items-center gap-1 pl-2 pr-1 py-1 text-sm text-white bg-white/15 rounded-md">
            {prefix}{value}
            <button
              type="button"
              aria-label={`Remove ${value}`}
              onClick={() => onChange(values.filter((v) => v !== value))}
              className="p-0.5 rounded hover:bg-white/20"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
        {values.length < max && (
          <input
            type="text"
            value={draft}
            onChange={(e) => {
              setError(null);
              const text = e.target.value;
              if (/[\s,]$/.test(text)) commit(text);
              else setDraft(text);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                commit(draft);
              } else if (e.key === 'Backspace' && !draft && values.length) {
                onChange(values.slice(0, -1));
              }
            }}
            // A tag typed but not yet entered still counts when the form is saved.
            onBlur={() => draft && commit(draft)}
            className="flex-1 min-w-[8rem] p-1 bg-transparent text-white placeholder-white/50 focus:outline-none"
            placeholder={values.length ? '' : placeholder}
          />
        )}
      </div>
      <p className={`mt-1 text-xs ${error ? 'text-red-300' : 'text-white/50'}`}>{error ?? hint}</p>
    </div>
  );
}

interface InstagramDetailsFieldsProps {
  value: InstagramDetailsValue;
  onChange: (patch: Partial<InstagramDetailsValue>) => void;
  authToken: string | null;
}

/** Hashtags, collaborators and location for a photo going to Instagram. */
export default function InstagramDetailsFields({ value, onChange, authToken }: InstagramDetailsFieldsProps) {
  const [knownLocations, setKnownLocations] = useState<InstagramLocation[]>([]);

  useEffect(() => {
    if (!authToken) return;
    getInstagramLocations(authToken).then(setKnownLocations).catch(() => setKnownLocations([]));
  }, [authToken]);

  const locationId = parseFacebookPageId(value.locationInput);

  return (
    <div className="space-y-4 p-4 bg-white/5 rounded-xl border border-white/10">
      <p className="text-white font-medium">Instagram details</p>

      <ChipInput
        label="Hashtags"
        hint="Added after the Aiko link. A few specific tags beat many generic ones."
        values={value.hashtags}
        onChange={(hashtags) => onChange({ hashtags })}
        clean={cleanHashtag}
        prefix="#"
        max={MAX_HASHTAGS}
        placeholder="photography"
      />

      <ChipInput
        label="Collaborators"
        hint="Instagram usernames, public accounts only. Each gets an invite; once accepted, the post also shows on their profile."
        values={value.collaborators}
        onChange={(collaborators) => onChange({ collaborators })}
        clean={cleanUsername}
        prefix="@"
        max={MAX_COLLABORATORS}
        placeholder="username"
        isValid={(name) => /^[a-z0-9._]{1,30}$/.test(name)}
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <label className="block">
          <span className="block text-sm font-medium text-white/90 mb-2">Location</span>
          <input
            type="text"
            list="instagram-locations"
            value={value.locationName}
            onChange={(e) => {
              const name = e.target.value;
              const known = knownLocations.find((l) => l.name === name);
              onChange(known ? { locationName: name, locationInput: known.id } : { locationName: name });
            }}
            className={inputClass}
            placeholder="Mount Rainier National Park"
          />
          <datalist id="instagram-locations">
            {knownLocations.map((l) => <option key={l.id} value={l.name} />)}
          </datalist>
        </label>
        <label className="block">
          <span className="block text-sm font-medium text-white/90 mb-2">Facebook page link or id</span>
          <input
            type="text"
            value={value.locationInput}
            onChange={(e) => onChange({ locationInput: e.target.value })}
            className={inputClass}
            placeholder="facebook.com/pages/…/123456789"
          />
        </label>
      </div>
      <p className="-mt-2 text-xs text-white/50">
        {value.locationInput.trim()
          ? locationId
            ? `Page id ${locationId}`
            : <span className="text-red-300">No page id in that link</span>
          : 'Instagram names places by their Facebook page. Find the place on Facebook, then copy the page id from About → Page transparency. Places you have used before show up as you type.'}
      </p>
    </div>
  );
}
