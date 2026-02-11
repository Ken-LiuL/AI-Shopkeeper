'use client';
import { ReactNode } from 'react';

export function EmptyState({ icon = '📭', title = '暂无数据', description, action }: {
  icon?: string;
  title?: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3">
      <span className="text-4xl">{icon}</span>
      <h4 className="text-white font-medium">{title}</h4>
      {description && <p className="text-sm text-gray-500 max-w-sm text-center">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
