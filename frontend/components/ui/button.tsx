'use client';
import { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';

const variants: Record<Variant, string> = {
  primary: 'bg-amber-500 hover:bg-amber-600 text-black font-semibold',
  secondary: 'bg-white/10 hover:bg-white/15 text-white',
  danger: 'bg-red-600 hover:bg-red-700 text-white',
  ghost: 'hover:bg-white/5 text-gray-400',
};

export function Button({
  children, variant = 'primary', className = '', disabled, ...props
}: { children: ReactNode; variant?: Variant; className?: string } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}
