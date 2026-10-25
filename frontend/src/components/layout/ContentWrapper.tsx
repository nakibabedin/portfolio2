import CreatePost from '@/components/ui/CreatePost';
import ScrollToTop from '@/components/ui/ScrollToTop';

interface ContentWrapperProps {
  children: React.ReactNode;
}

export default function ContentWrapper({ children }: ContentWrapperProps) {
  return (
    <div className="flex-1 min-w-0">
      {/* Persistent Create Post Button - always visible */}
      <CreatePost />
      <ScrollToTop />

      {/* Page Content */}
      {children}
    </div>
  );
}

