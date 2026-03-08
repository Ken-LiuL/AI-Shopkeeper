'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Sidebar } from '@/components/layout/sidebar';
import { OnboardingGuide } from '@/components/onboarding/guide';
import { AIAssistantFAB } from '@/components/ai-assistant-fab';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [authed] = useState(() => {
    if (typeof window === 'undefined') return false;
    return !!localStorage.getItem('auth_token');
  });

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
      <main className="flex-1 overflow-auto w-full md:w-auto">
        <div className="p-6 lg:p-8 pt-16 md:pt-6">{children}</div>
      </main>
      <OnboardingGuide />
      <AIAssistantFAB />
    </div>
  );
}
