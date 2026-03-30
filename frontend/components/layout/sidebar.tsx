'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { useState, useEffect } from 'react';

const coreNav = [
  { href: '/', label: 'AI 指挥台', icon: '🧭' },
  { href: '/alerts', label: '预警处理', icon: '🔔' },
  { href: '/inventory', label: '库存修复', icon: '📦' },
  { href: '/products', label: '商品修复', icon: '🧾' },
  { href: '/orders', label: '异常订单', icon: '📋' },
  { href: '/customer-service', label: '客服质量', icon: '💬' },
  { href: '/knowledge', label: '知识中心', icon: '📚' },
];

const settingsNav = [
  { href: '/settings/sync', label: '数据导入', icon: '📥' },
];

const growthNav = [
  { href: '/selection', label: '重点运营', icon: '🎯' },
  { href: '/bundles', label: '套餐候选', icon: '🎁' },
  { href: '/pricing', label: '价格复核', icon: '💰' },
];

export function Sidebar() {
  const pathname = usePathname();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isGrowthOpen, setIsGrowthOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [username] = useState(() => {
    if (typeof window === 'undefined') return 'admin';
    return localStorage.getItem('auth_username') || 'admin';
  });

  useEffect(() => {
    const checkIfMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };

    checkIfMobile();
    window.addEventListener('resize', checkIfMobile);
    return () => window.removeEventListener('resize', checkIfMobile);
  }, []);

  const closeMobileMenu = () => {
    setIsMobileMenuOpen(false);
  };

  return (
    <>
      {/* Mobile hamburger button */}
      <button
        onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
        className="md:hidden fixed top-4 left-4 z-50 p-2 bg-white border border-gray-200 rounded-lg shadow-md"
        aria-label="Toggle menu"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      {/* Mobile overlay */}
      {isMobile && isMobileMenuOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-40 md:hidden"
          onClick={closeMobileMenu}
        />
      )}

      {/* Sidebar */}
      <aside className={cn(
        "w-60 bg-background border-r border-border flex flex-col transition-transform duration-300 ease-in-out",
        "md:translate-x-0", // Always visible on desktop
        isMobile ? (isMobileMenuOpen ? "translate-x-0 fixed inset-y-0 left-0 z-40" : "-translate-x-full fixed inset-y-0 left-0 z-40") : ""
      )}>
      <div className="px-6 py-6 border-b border-border">
        <h1 className="text-lg font-bold text-blue-600">🧭 AI 店长</h1>
        <p className="text-sm text-muted-foreground mt-1">经营动作系统</p>

        <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
          <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
            <span className="text-blue-500">🏪</span>
            <span>当前店铺</span>
          </div>
          <div className="mt-1 text-sm text-gray-600">当前环境按单店运营视角展示。</div>
        </div>
      </div>
      <nav className="flex-1 py-4 px-4">
        <div className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          核心工作流
        </div>
        <div className="space-y-1">
        {coreNav.map((item) => {
          const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={closeMobileMenu}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                active
                  ? "bg-blue-50 text-blue-700 border border-blue-200"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              )}
            >
              <span className="text-base">{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
        </div>

        <div className="mt-6">
          <button
            type="button"
            onClick={() => setIsGrowthOpen((prev) => !prev)}
            className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400"
          >
            <span>增长与实验</span>
            <span className={cn("transition-transform", isGrowthOpen ? "rotate-180" : "")}>▼</span>
          </button>
          {isGrowthOpen ? (
            <div className="mt-2 space-y-1">
              {growthNav.map((item) => {
                const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={closeMobileMenu}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                      active
                        ? "bg-blue-50 text-blue-700 border border-blue-200"
                        : "text-gray-500 hover:bg-gray-50 hover:text-gray-900"
                    )}
                  >
                    <span className="text-base">{item.icon}</span>
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ) : (
            <div className="px-3 py-2 text-xs leading-5 text-slate-500">
              这里只保留当前数据能支撑的增长动作。竞品和上架暂不进入现阶段产品主线。
            </div>
          )}
        </div>
      </nav>
      {/* Settings nav */}
      <div className="px-4 pb-2">
        <div className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          设置
        </div>
        <div className="space-y-1">
          {settingsNav.map((item) => {
            const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={closeMobileMenu}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                  active
                    ? "bg-blue-50 text-blue-700 border border-blue-200"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                )}
              >
                <span className="text-base">{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>
      </div>

      {/* User info + logout */}
      <div className="px-4 py-3 border-t border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-gray-500">👤</span>
            <span className="text-sm text-gray-700 font-medium">{username}</span>
          </div>
          <button
            onClick={() => {
              localStorage.removeItem('auth_token');
              localStorage.removeItem('auth_username');
              window.location.href = '/login';
            }}
            className="text-xs text-gray-400 hover:text-red-500 transition-colors"
          >
            退出
          </button>
        </div>
      </div>
      </aside>
    </>
  );
}
