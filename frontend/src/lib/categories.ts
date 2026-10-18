export interface CategoryConfig {
  title: string;
  directory: string;
  /** The URL segment, e.g. /shop. */
  slug: string;
  /** The category posts are stored under, when it differs from the slug. */
  category?: string;
}

export const CATEGORY_CONFIG: Record<string, CategoryConfig> = {
  bio: {
    title: 'Bio',
    directory: 'pinterest_placeholders',
    slug: 'bio',
  },
  art: {
    title: 'Art',
    directory: 'art_placeholders',
    slug: 'art',
  },
  photo: {
    title: 'Photography',
    directory: 'photo_placeholders',
    slug: 'photo',
  },
  music: {
    title: 'Music',
    directory: 'music_placeholders',
    slug: 'music',
  },
  projects: {
    title: 'Projects',
    directory: 'pinterest_placeholders',
    slug: 'projects',
  },
  shop: {
    title: 'Shop',
    directory: 'apparel_placeholders',
    slug: 'shop',
    category: 'apparel',
  },
};

/** The category a section's posts are stored under in the database. */
export function dbCategory(config: CategoryConfig): string {
  return config.category ?? config.slug;
}

export function getCategoryConfig(slug?: string): CategoryConfig | null {
  if (!slug) return null;
  const key = slug.toLowerCase();
  return CATEGORY_CONFIG[key] ?? null;
}
