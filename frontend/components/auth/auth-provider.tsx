'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Sidebar } from '@/components/layout/sidebar';
import { OnboardingGuide } from '@/components/onboarding/guide';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    if (token) {
      setAuthed(true);
    } else if (pathname !== '/login') {
      router.push('/login');
    }
    setChecked(true);
  }, [pathname, router]);

  // Login page: no sidebar, just render children
  if (pathname === '/login') {
    return <>{children}</>;
  }

  // Not yet checked
  if (!checked) return null;

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
    </div>
  );
}
