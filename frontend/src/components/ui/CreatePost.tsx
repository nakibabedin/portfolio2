'use client';

import { useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { PlusIcon } from '@heroicons/react/24/outline';
import PostModal from './PostModal';
import { useAuth } from '@/providers/AuthProvider';

// First URL segment -> the modal's subject. Some sections have a dedicated
// page under a longer name (/photography) besides the /[category] route.
const SUBJECT_BY_PATH: Record<string, string> = {
  art: 'art',
  artwork: 'art',
  photo: 'photo',
  photography: 'photo',
  music: 'music',
  projects: 'projects',
  bio: 'bio',
  shop: 'shop',
};

export default function CreatePost() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { user, loading, signInWithGoogle } = useAuth();
  const pathname = usePathname();

  // The button lives in the layout, so where it was pressed is only knowable
  // from the URL. Inside a section (and album), the modal opens already
  // pointed at it; anywhere else it starts from a clean slate.
  const [defaultSubject, defaultAlbum] = useMemo(() => {
    const [segment, album] = (pathname || '')
      .split('/')
      .filter(Boolean)
      .map(decodeURIComponent);

    const subject = SUBJECT_BY_PATH[segment ?? ''];
    if (!subject) return ['', ''];
    // "favorites" is a view across albums, not an album anything can be filed
    // under.
    return [subject, album && album !== 'favorites' ? album : ''];
  }, [pathname]);

  if (loading) {
    return null;
  }

  const handleSignIn = async () => {
    try {
      await signInWithGoogle();
    } catch (err) {
      console.error('[Auth] Sign-in failed:', err);
    }
  };

  return (
    <>
      {user ? (
        <>
          <div className="fixed top-4 right-4 md:top-auto md:bottom-6 md:right-6 z-50">
            <motion.button
              className="w-10 h-10 md:w-14 md:h-14 rounded-xl md:rounded-2xl flex items-center justify-center shadow-lg text-white backdrop-blur-sm"
              style={{ backgroundColor: 'rgba(255, 255, 255, 0.175)' }}
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => setIsModalOpen(true)}
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.2 }}
            >
              <PlusIcon className="w-5 h-5 md:w-6 md:h-6" />
            </motion.button>
          </div>
        </>
      ) : null}

      <AnimatePresence>
        {isModalOpen && (
          <PostModal
            isOpen={isModalOpen}
            onClose={() => setIsModalOpen(false)}
            defaultSubject={defaultSubject}
            defaultAlbum={defaultAlbum}
          />
        )}
      </AnimatePresence>
    </>
  );
}
