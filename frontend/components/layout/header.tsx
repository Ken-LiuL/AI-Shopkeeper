'use client';

export function Header({ title }: { title: string }) {
  return (
    <header className="h-16 border-b border-white/[0.08] flex items-center px-6">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
    </header>
  );
}
