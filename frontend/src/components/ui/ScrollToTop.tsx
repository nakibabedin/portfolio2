'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUpIcon } from '@heroicons/react/24/outline';
import { useAuth } from '@/providers/AuthProvider';

export default function ScrollToTop() {
  const [isVisible, setIsVisible] = useState(false);
  const { user, loading } = useAuth();

  useEffect(() => {
    let ticking = false;

    // Only worth offering once the top of the page is a screen away.
    const update = () => {
      setIsVisible(window.scrollY > window.innerHeight);
      ticking = false;
    };
    const handleScroll = () => {
      if (!ticking) {
        window.requestAnimationFrame(update);
        ticking = true;
      }
    };

    update();
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const scrollToTop = () => {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
  };

  // On desktop the create button (signed in only) holds the bottom-right
  // corner, so this sits above it then. On mobile that button is up top and
  // this clears the bottom nav bar instead.
  const hasCreateButton = Boolean(user) && !loading;

  return (
    <AnimatePresence>
      {isVisible && (
        <div className={`fixed bottom-20 right-4 md:right-6 z-40 ${hasCreateButton ? 'md:bottom-24' : 'md:bottom-6'}`}>
          <motion.button
            type="button"
            aria-label="Scroll to top"
            title="Scroll to top"
            className="w-10 h-10 md:w-14 md:h-14 rounded-xl md:rounded-2xl flex items-center justify-center shadow-lg text-white backdrop-blur-sm"
            style={{ backgroundColor: 'rgba(255, 255, 255, 0.175)' }}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.95 }}
            onClick={scrollToTop}
            initial={{ opacity: 0, scale: 0 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0 }}
            transition={{ duration: 0.2 }}
          >
            <ArrowUpIcon className="w-5 h-5 md:w-6 md:h-6" />
          </motion.button>
        </div>
      )}
    </AnimatePresence>
  );
}
