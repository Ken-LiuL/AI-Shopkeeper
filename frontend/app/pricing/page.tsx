'use client';
import { useEffect, useState, useCallback } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { Table, Column } from '@/components/ui/table';
import { StatsCard } from '@/components/ui/stats-card';
import { getPricingSuggestions, applyPriceChanges } from '@/lib/api';

interface PriceSuggestion {
  product_id: string;
  product_name: string;
  current_price: number;
  suggested_price: number;
  reason: string;
  current_margin: number;
  projected_margin: number;
  competitor_ref: { avg: number; min: number; max: number; count: number };
}

export default function PricingPage() {
  const [suggestions, setSuggestions] = useState<PriceSuggestion[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const res = await getPricingSuggestions();
      setSuggestions(res.data || []);
    } catch {}
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleApply = async () => {
    const changes = suggestions
      .filter(s => selected.has(s.product_id))
      .map(s => ({ product_id: s.product_id, new_price: s.suggested_price, reason: s.reason }));
    if (!changes.length) return;
    setLoading(true);
    try {
      const res = await applyPriceChanges(changes);
      setResult(res.data);
      load();
      setSelected(new Set());
    } catch {} finally { setLoading(false); }
  };

  const columns: Column<PriceSuggestion>[] = [
    {
      key: 'select', label: '', render: (r) => (
        <input type="checkbox" checked={selected.has(r.product_id)}
          onChange={() => toggleSelect(r.product_id)}
          className="accent-amber-500" />
      ),
    },
    { key: 'product_name', label: '商品', render: (r) => <span className="text-white">{r.product_name}</span> },
    {
      key: 'prices', label: '价格对比', render: (r) => {
        const diff = r.suggested_price - r.current_price;
        return (
          <div className="text-sm">
            <span className="text-gray-400">¥{r.current_price}</span>
            <span className="mx-2">→</span>
            <span className={diff < 0 ? 'text-green-400' : 'text-red-400'}>
              ¥{r.suggested_price} ({diff > 0 ? '+' : ''}{diff.toFixed(0)})
            </span>
          </div>
        );
      },
    },
    {
      key: 'competitor', label: '竞品价格', render: (r) => (
        <div className="text-xs text-gray-400">
          均价¥{r.competitor_ref.avg} · 最低¥{r.competitor_ref.min} · {r.competitor_ref.count}家
        </div>
      ),
    },
    {
      key: 'margin', label: '毛利率', render: (r) => (
        <div className="text-sm">
          <span className="text-gray-400">{(r.current_margin * 100).toFixed(0)}%</span>
          <span className="mx-1">→</span>
          <span className={r.projected_margin >= 0.2 ? 'text-green-400' : 'text-red-400'}>
            {(r.projected_margin * 100).toFixed(0)}%
          </span>
        </div>
      ),
    },
    { key: 'reason', label: '调价原因', className: 'max-w-xs text-xs text-gray-400' },
  ];

  return (
    <div>
      <Header title="定价管理" />
      <div className="p-6 space-y-4">
        <div className="grid grid-cols-3 gap-4">
          <StatsCard title="调价建议" value={suggestions.length} icon="💲" />
          <StatsCard title="建议降价" value={suggestions.filter(s => s.suggested_price < s.current_price).length} icon="📉" />
          <StatsCard title="建议涨价" value={suggestions.filter(s => s.suggested_price > s.current_price).length} icon="📈" />
        </div>

        <Card>
          <div className="p-4 border-b border-white/[0.08] flex justify-between items-center">
            <span className="text-sm text-gray-400">选中 {selected.size} 个商品</span>
            <button
              onClick={handleApply}
              disabled={!selected.size || loading}
              className="px-4 py-2 bg-amber-500 text-black text-sm font-medium rounded-lg hover:bg-amber-400 disabled:opacity-50"
            >
              {loading ? '应用中...' : `批量调价 (${selected.size})`}
            </button>
          </div>
          <Table columns={columns} data={suggestions} />
        </Card>

        {result && (
          <Card>
            <div className="p-4">
              <h3 className="text-white font-medium mb-2">✅ 调价完成</h3>
              <p className="text-sm text-gray-400">成功调整 {result.length} 个商品价格</p>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
