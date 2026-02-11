'use client';
import { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  className?: string;
}

interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  onRowClick?: (row: T) => void;
  page?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
}

export function Table<T extends Record<string, any>>({ columns, data, onRowClick, page, totalPages, onPageChange }: TableProps<T>) {
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.08]">
              {columns.map((col) => (
                <th key={col.key} className={`text-left text-gray-400 font-medium py-3 px-4 ${col.className || ''}`}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr
                key={i}
                onClick={() => onRowClick?.(row)}
                className={`border-b border-white/[0.04] ${onRowClick ? 'cursor-pointer hover:bg-white/[0.03]' : ''} transition-colors`}
              >
                {columns.map((col) => (
                  <td key={col.key} className={`py-3 px-4 text-gray-300 ${col.className || ''}`}>
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))}
            {data.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="text-center text-gray-500 py-8">暂无数据</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {totalPages && totalPages > 1 && onPageChange && (
        <div className="flex items-center justify-between mt-4 px-4">
          <span className="text-sm text-gray-500">第 {page} / {totalPages} 页</span>
          <div className="flex gap-2">
            <button
              onClick={() => onPageChange(page! - 1)}
              disabled={page === 1}
              className="px-3 py-1 rounded bg-white/5 text-gray-400 text-sm disabled:opacity-30 hover:bg-white/10"
            >上一页</button>
            <button
              onClick={() => onPageChange(page! + 1)}
              disabled={page === totalPages}
              className="px-3 py-1 rounded bg-white/5 text-gray-400 text-sm disabled:opacity-30 hover:bg-white/10"
            >下一页</button>
          </div>
        </div>
      )}
    </div>
  );
}
