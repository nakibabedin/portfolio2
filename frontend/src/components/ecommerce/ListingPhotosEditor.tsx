'use client';

import { useState } from 'react';
import { ImagePlus, X } from 'lucide-react';
import { uploadImage } from '@/lib/api';
import { compressImageFile } from '@/lib/images';

// A shop listing's photos in the order they show. The first is the listing's
// thumbnail: the shop tile, the checkout image and the first slide. Saved
// photos carry their url; ones added here carry the file until save.
export interface ListingPhoto {
    key: string;
    preview: string;
    url?: string;
    file?: File;
}

export function listingPhotosFromUrls(urls: string[]): ListingPhoto[] {
    return urls.map((url) => ({ key: url, preview: url, url }));
}

// Uploads the photos added since the listing was saved and returns every
// photo's url, in order.
export async function uploadListingPhotos(photos: ListingPhoto[], authToken: string): Promise<string[]> {
    const urls: string[] = [];
    for (const photo of photos) {
        if (photo.url) {
            urls.push(photo.url);
            continue;
        }
        let file = photo.file!;
        try {
            file = await compressImageFile(file, { maxWidth: 1600, maxHeight: 1600, quality: 0.75 });
        } catch (err) {
            console.warn('[ListingPhotos] Compression failed, uploading original:', err);
        }
        const { url } = await uploadImage(file, 'apparel', authToken);
        urls.push(url);
    }
    return urls;
}

interface ListingPhotosEditorProps {
    photos: ListingPhoto[];
    onChange: (photos: ListingPhoto[]) => void;
    disabled?: boolean;
}

export default function ListingPhotosEditor({ photos, onChange, disabled }: ListingPhotosEditorProps) {
    const [dragIndex, setDragIndex] = useState<number | null>(null);

    const move = (from: number, to: number) => {
        if (from === to || to < 0 || to >= photos.length) return;
        const next = [...photos];
        const [photo] = next.splice(from, 1);
        next.splice(to, 0, photo);
        onChange(next);
    };

    const handleAdd = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files ?? []).filter((file) => file.type.startsWith('image/'));
        e.target.value = '';
        const keys = new Set(photos.map((p) => p.key));
        const added = files
            .map((file) => ({ key: `${file.name}-${file.size}`, preview: URL.createObjectURL(file), file }))
            .filter((photo) => !keys.has(photo.key));
        if (added.length > 0) onChange([...photos, ...added]);
    };

    return (
        <div>
            <label className="block text-sm font-medium text-white/90 mb-2">Photos</label>
            <p className="text-sm text-white/60 mb-3">
                Drag to reorder. The first is the thumbnail on the shop and at checkout.
            </p>
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
                {photos.map((photo, index) => (
                    <div
                        key={photo.key}
                        draggable={!disabled && photos.length > 1}
                        onDragStart={() => setDragIndex(index)}
                        onDragOver={(ev) => ev.preventDefault()}
                        onDrop={(ev) => {
                            ev.preventDefault();
                            if (dragIndex !== null) move(dragIndex, index);
                            setDragIndex(null);
                        }}
                        onDragEnd={() => setDragIndex(null)}
                        className={`relative group rounded-lg ${photos.length > 1 ? 'cursor-grab active:cursor-grabbing' : ''} ${dragIndex === index ? 'opacity-40' : ''}`}
                    >
                        <img
                            src={photo.preview}
                            alt={`Photo ${index + 1}`}
                            className={`w-full aspect-square object-cover rounded-lg border ${index === 0 ? 'border-white' : 'border-white/20'}`}
                            draggable={false}
                        />
                        <span className="absolute top-1.5 left-1.5 px-1.5 py-0.5 text-xs font-medium bg-black/70 text-white rounded">
                            {index === 0 ? 'Thumbnail' : index + 1}
                        </span>
                        <button
                            type="button"
                            onClick={() => onChange(photos.filter((_, i) => i !== index))}
                            disabled={disabled}
                            aria-label={`Remove photo ${index + 1}`}
                            className="absolute top-1.5 right-1.5 p-1 bg-black/60 rounded-full text-white sm:opacity-0 sm:group-hover:opacity-100 transition-opacity"
                        >
                            <X className="w-3.5 h-3.5" />
                        </button>
                        {/* Buttons too, for touch screens where dragging doesn't work */}
                        {photos.length > 1 && (
                            <div className="absolute bottom-1.5 inset-x-1.5 flex justify-between gap-1 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                                <button
                                    type="button"
                                    onClick={() => move(index, index - 1)}
                                    disabled={disabled || index === 0}
                                    aria-label={`Move photo ${index + 1} earlier`}
                                    className="px-1.5 bg-black/60 rounded text-white text-sm disabled:invisible"
                                >
                                    ‹
                                </button>
                                {index > 0 && (
                                    <button
                                        type="button"
                                        onClick={() => move(index, 0)}
                                        disabled={disabled}
                                        title="Make this the thumbnail"
                                        aria-label={`Make photo ${index + 1} the thumbnail`}
                                        className="min-w-0 truncate px-1.5 bg-black/60 rounded text-white text-xs"
                                    >
                                        Thumbnail
                                    </button>
                                )}
                                <button
                                    type="button"
                                    onClick={() => move(index, index + 1)}
                                    disabled={disabled || index === photos.length - 1}
                                    aria-label={`Move photo ${index + 1} later`}
                                    className="px-1.5 bg-black/60 rounded text-white text-sm disabled:invisible"
                                >
                                    ›
                                </button>
                            </div>
                        )}
                    </div>
                ))}
                <label className={`flex flex-col items-center justify-center aspect-square border-2 border-dashed border-white/30 rounded-lg bg-white/5 transition-colors ${disabled ? 'opacity-50' : 'cursor-pointer hover:bg-white/10'}`}>
                    <ImagePlus className="w-6 h-6 text-white/60" />
                    <span className="text-xs text-white/60 mt-1">Add photos</span>
                    <input type="file" accept="image/*" multiple className="hidden" onChange={handleAdd} disabled={disabled} />
                </label>
            </div>
        </div>
    );
}
