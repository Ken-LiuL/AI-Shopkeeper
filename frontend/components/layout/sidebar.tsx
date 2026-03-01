'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { useState } from 'react';

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

  const selectedStore = stores.find(s => s.id === selectedStoreId) || stores[0];

  return (
    <aside className="w-60 bg-background border-r border-border flex flex-col">
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
    </aside>
  );
}
