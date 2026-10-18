import SectionWithFeed from '@/components/sections/SectionWithFeed';
import { dbCategory, getCategoryConfig } from '@/lib/categories';
import { notFound } from 'next/navigation';

export const revalidate = 0;

interface CategoryPageProps {
  params: Promise<{
    category: string;
  }>;
}

export default async function CategoryPage({ params }: CategoryPageProps) {
  const { category } = await params;
  const config = getCategoryConfig(category);

  if (!config) {
    notFound();
  }

  return (
    <SectionWithFeed
      title={config.title}
      directory={config.directory}
      category={dbCategory(config)}
      categorySlug={config.slug}
      useDatabase={true}
    />
  );
}
