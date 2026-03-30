'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Sidebar } from '@/components/layout/sidebar';
import { OnboardingGuide } from '@/components/onboarding/guide';
import { AIAssistantFAB } from '@/components/ai-assistant-fab';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    const syncAuth = () => {
      if (typeof window === 'undefined') return;
      setAuthed(!!localStorage.getItem('auth_token'));
    };

    syncAuth();
    window.addEventListener('storage', syncAuth);

    return () => window.removeEventListener('storage', syncAuth);
  }, [pathname]);

  useEffect(() => {
    if (!authed && pathname !== '/login') {
      router.push('/login');
    }
  }, [authed, pathname, router]);

  // Login page: no sidebar, just render children
  if (pathname === '/login') {
    return <>{children}</>;
  }

  // Not authed → redirect happening, show nothing
  if (!authed) return null;

  // Authed → render full layout
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-auto w-full md:w-auto min-w-0">
        <div className="p-4 md:p-6 lg:p-8 pt-16 md:pt-6">{children}</div>
      </main>
      <OnboardingGuide />
      <AIAssistantFAB />
    </div>
  );
}
