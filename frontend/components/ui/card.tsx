'use client';
import { ReactNode } from 'react';

export function Card({ children, className = '', onClick }: { children: ReactNode; className?: string; onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      className={`bg-[#141414] border border-white/[0.08] rounded-xl p-5 ${onClick ? 'cursor-pointer hover:border-amber-500/30 transition-colors' : ''} ${className}`}
    >
      {children}
    </div>
  );
}
