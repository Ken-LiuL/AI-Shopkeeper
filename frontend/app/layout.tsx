import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Sidebar } from '@/components/layout/sidebar';
import { OnboardingGuide } from '@/components/onboarding/guide';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'AI 店长 - 智能管理后台',
  description: '便利店 AI 智能管理系统',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className={`${inter.className} bg-background text-foreground antialiased`}>
        <div className="flex h-screen">
          <Sidebar />
          <main className="flex-1 overflow-auto">
            <div className="p-6 lg:p-8">{children}</div>
          </main>
        </div>
        <OnboardingGuide />
      </body>
    </html>
  );
}
