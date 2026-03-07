'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { useState, useEffect } from 'react';

const nav = [
  { href: '/', label: '仪表盘', icon: '📊' },
  { href: '/analytics', label: '数据分析', icon: '📈' },
  { href: '/orders', label: '订单管理', icon: '📋' },
  { href: '/products', label: '商品管理', icon: '📦' },
  { href: '/pricing', label: '智能定价', icon: '💰' },
  { href: '/competitors', label: '竞品监控', icon: '🏪' },
  { href: '/reports', label: '报表', icon: '📈' },
  { href: '/chat', label: 'AI 客服', icon: '💬' },
  { href: '/alerts', label: '告警', icon: '🔔' },
  { href: '/selection', label: '智能选品', icon: '🎯' },
  { href: '/bundles', label: '智能套餐', icon: '🎁' },
  { href: '/settings/sync', label: '数据同步', icon: '🔄' },
];

const stores = [
  { id: '1232550', name: '医疗器械店(旗舰店)' },
  { id: '1221411', name: '医疗器械店(南门店)' },
  { id: '1175006', name: '医疗器械店(北门店)' },
];

export function Sidebar() {
  const pathname = usePathname();
  const [selectedStoreId, setSelectedStoreId] = useState('1232550');
  const [isStoreDropdownOpen, setIsStoreDropdownOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [username, setUsername] = useState('');

  useEffect(() => {
    const u = localStorage.getItem('auth_username') || 'admin';
    setUsername(u);
  }, []);

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

  const selectedStore = stores.find(s => s.id === selectedStoreId) || stores[0];

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
        <h1 className="text-lg font-bold text-blue-600">🤖 AI 店长</h1>
        <p className="text-sm text-muted-foreground mt-1">智能管理后台</p>

        {/* 店铺切换器 */}
        <div className="mt-4 relative">
          <button
            onClick={() => setIsStoreDropdownOpen(!isStoreDropdownOpen)}
            className="w-full flex items-center justify-between px-3 py-2 text-sm bg-gray-50 rounded-lg border border-gray-200 hover:bg-gray-100 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="text-blue-500">🏪</span>
              <span className="font-medium truncate">{selectedStore.name}</span>
            </div>
            <span className={`text-gray-400 transition-transform ${isStoreDropdownOpen ? 'rotate-180' : ''}`}>
              ▼
            </span>
          </button>

          {isStoreDropdownOpen && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-50">
              {stores.map((store) => (
                <button
                  key={store.id}
                  onClick={() => {
                    setSelectedStoreId(store.id);
                    setIsStoreDropdownOpen(false);
                  }}
                  className={cn(
                    "w-full text-left px-3 py-2 text-sm hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg",
                    store.id === selectedStoreId ? "bg-blue-50 text-blue-700" : "text-gray-700"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-blue-500">🏪</span>
                    <span>{store.name}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <nav className="flex-1 py-4 px-4 space-y-1">
        {nav.map((item) => {
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
      </nav>
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
