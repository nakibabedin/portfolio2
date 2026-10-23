'use client';

import Image from 'next/image';
import { Copy } from 'lucide-react';

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

export default function ImageTile({ item, index }: ImageTileProps) {
  const isText = item.isText || (!item.image && item.category.toLowerCase() === 'bio');
  // A photo group shows only its cover, with a badge saying there are more.
  const isGallery = item.category === 'photo' && (item.galleryUrls?.length ?? 0) > 1;

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

        {(isGallery || item.isActive) && (
          <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
            {/* Active Project Indicator */}
            {item.isActive && (
              <div className="relative flex items-center justify-center w-4 h-4">
                <div className="absolute w-full h-full bg-black/20 rounded-full backdrop-blur-[1px]" />
                <div className="w-2.5 h-2.5 bg-green-500 rounded-full shadow-[0_0_8px_rgba(34,197,94,0.6)]" />
              </div>
            )}
            {isGallery && (
              <Copy
                aria-label="Gallery"
                className="w-5 h-5 text-white/60 group-hover:text-white transition-colors duration-300 drop-shadow-[0_1px_2px_rgba(0,0,0,0.6)]"
                strokeWidth={2}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
