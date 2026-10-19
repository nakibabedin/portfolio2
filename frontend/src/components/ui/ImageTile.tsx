'use client';

import { motion } from 'framer-motion';
import Image from 'next/image';

interface ImageTileProps {
  item: {
    id: string;
    title: string;
    description: string;
    image: string;
    category: string;
    isText?: boolean;
    price?: number | null;
    isActive?: boolean;
    isFavorite?: boolean;
    galleryUrls?: string[];
  };
  index: number;
}

const TILE_SIZES = "(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw";

// A photo group fills its tile as a collage: two side by side, three as one
// large and two stacked, four or more as a 2x2 with the rest counted on the
// last cell.
function Mosaic({ urls, title, eager }: { urls: string[]; title: string; eager: boolean }) {
  const shown = urls.slice(0, 4);
  const extra = urls.length - shown.length;
  const layout =
    shown.length === 2 ? 'grid-cols-2 grid-rows-1'
      : shown.length === 3 ? 'grid-cols-3 grid-rows-2'
        : 'grid-cols-2 grid-rows-2';

  return (
    <div className={`absolute inset-0 grid gap-0.5 ${layout}`}>
      {shown.map((url, i) => (
        <div
          key={url}
          className={`relative overflow-hidden ${shown.length === 3 && i === 0 ? 'col-span-2 row-span-2' : ''}`}
        >
          <Image
            src={url}
            alt={i === 0 ? title : `${title} (${i + 1})`}
            fill
            className="object-cover group-hover:scale-[1.02] transition-transform duration-300"
            loading={eager && i === 0 ? "eager" : "lazy"}
            sizes={shown.length === 3 && i === 0 ? TILE_SIZES : "(max-width: 768px) 50vw, (max-width: 1200px) 25vw, 17vw"}
          />
          {extra > 0 && i === shown.length - 1 && (
            <div className="absolute inset-0 bg-black/50 flex items-center justify-center text-white text-xl font-semibold">
              +{extra}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function ImageTile({ item, index }: ImageTileProps) {
  const isText = item.isText || (!item.image && item.category.toLowerCase() === 'bio');
  const groupUrls = item.category === 'photo' ? (item.galleryUrls ?? []) : [];

  return (
    <div className="group cursor-pointer h-full">
      <div className="relative overflow-hidden rounded-2xl shadow-lg hover:shadow-xl transition-shadow duration-300 h-full">
        {isText ? (
          <div className="absolute inset-0 bg-gradient-to-br from-black via-black/80 to-black/60 text-white p-6 flex flex-col justify-end">
            <div className="space-y-3">
              <h3 className="text-xl font-semibold line-clamp-3">{item.title}</h3>
              <p className="text-sm text-white/70 line-clamp-4">{item.description}</p>
            </div>
          </div>
        ) : groupUrls.length > 1 ? (
          <Mosaic urls={groupUrls} title={item.title} eager={index === 0} />
        ) : (
          <Image
            src={item.image}
            alt={item.title}
            fill
            className="object-cover group-hover:scale-[1.02] transition-transform duration-300"
            loading={index === 0 ? "eager" : "lazy"}
            sizes={TILE_SIZES}
          />
        )}

        {/* Active Project Indicator */}
        {item.isActive && (
          <div className="absolute top-3 right-3 z-10">
            <div className="relative flex items-center justify-center w-4 h-4">
              <div className="absolute w-full h-full bg-black/20 rounded-full backdrop-blur-[1px]" />
              <div className="w-2.5 h-2.5 bg-green-500 rounded-full shadow-[0_0_8px_rgba(34,197,94,0.6)]" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
