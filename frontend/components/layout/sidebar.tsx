'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';

const nav = [
  { href: '/', label: '仪表盘', icon: '📊' },
  { href: '/analytics', label: '数据分析', icon: '📈' },
  { href: '/products', label: '商品管理', icon: '📦' },
  { href: '/competitors', label: '竞品监控', icon: '🏪' },
  { href: '/reports', label: '经营报表', icon: '📋' },
  { href: '/chat', label: 'AI 客服', icon: '💬' },
  { href: '/alerts', label: '预警中心', icon: '🔔' },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-60 bg-background border-r border-border flex flex-col">
      <div className="px-6 py-6 border-b border-border">
        <h1 className="text-lg font-bold text-blue-600">🤖 AI 店长</h1>
        <p className="text-sm text-muted-foreground mt-1">智能管理后台</p>
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
