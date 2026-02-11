'use client';
import { ReactNode } from 'react';

export function StatsCard({ title, value, icon, trend }: { title: string; value: string | number; icon: ReactNode; trend?: string }) {
  return (
    <div className="bg-[#141414] border border-white/[0.08] rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-gray-400 text-sm">{title}</span>
        <span className="text-amber-500">{icon}</span>
      </div>
      <div className="text-2xl font-bold text-white">{value}</div>
      {trend && <div className="text-xs text-gray-500 mt-1">{trend}</div>}
    </div>
  );
}
