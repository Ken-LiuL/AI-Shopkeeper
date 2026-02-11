'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

const nav = [
  { href: '/', label: '总览', icon: '📊' },
  { href: '/products', label: '商品管理', icon: '📦' },
  { href: '/selection', label: '选品推荐', icon: '🎯' },
  { href: '/alerts', label: '预警中心', icon: '🔔' },
  { href: '/bundles', label: '套餐管理', icon: '🎁' },
  { href: '/customer-service', label: '智能客服', icon: '💬' },
  { href: '/listing', label: '上架管理', icon: '🚀' },
  { href: '/settings', label: '系统设置', icon: '⚙️' },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="fixed left-0 top-0 h-full w-60 bg-[#0e0e0e] border-r border-white/[0.08] flex flex-col z-40">
      <div className="px-5 py-6 border-b border-white/[0.08]">
        <h1 className="text-lg font-bold text-amber-500">🤖 AI 店长</h1>
        <p className="text-xs text-gray-500 mt-1">智能管理后台</p>
      </div>
      <nav className="flex-1 py-4 px-3 space-y-1">
        {nav.map((item) => {
          const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                active ? 'bg-amber-500/10 text-amber-500' : 'text-gray-400 hover:text-white hover:bg-white/[0.04]'
              }`}
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
