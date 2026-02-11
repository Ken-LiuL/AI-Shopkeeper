'use client';
import { useEffect, useState, useCallback } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { Table, Column } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { StatsCard } from '@/components/ui/stats-card';
import { getReplenishmentSuggestions, getReplenishmentSafetyStock, createPurchaseOrder } from '@/lib/api';

interface Suggestion {
  product_id: string;
  product_name: string;
  current_stock: number;
  safety_stock: number;
  suggested_qty: number;
  cost_price: number;
  estimated_cost: number;
  supplier_link: string;
}

export default function ReplenishmentPage() {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [poResult, setPoResult] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const res = await getReplenishmentSuggestions();
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

  const selectAll = () => {
    if (selected.size === suggestions.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(suggestions.map(s => s.product_id)));
    }
  };

  const handleCreatePO = async () => {
    const items = suggestions.filter(s => selected.has(s.product_id));
    if (!items.length) return;
    setLoading(true);
    try {
      const res = await createPurchaseOrder(items);
      setPoResult(res.data);
    } catch {} finally { setLoading(false); }
  };

  const totalCost = suggestions
    .filter(s => selected.has(s.product_id))
    .reduce((sum, s) => sum + s.estimated_cost, 0);

  const columns: Column<Suggestion>[] = [
    {
      key: 'select', label: '', render: (r) => (
        <input type="checkbox" checked={selected.has(r.product_id)}
          onChange={() => toggleSelect(r.product_id)}
          className="accent-amber-500" />
      ),
    },
    { key: 'product_name', label: '商品', render: (r) => <span className="text-white">{r.product_name}</span> },
    {
      key: 'stock_bar', label: '库存状态', render: (r) => {
        const pct = Math.min(r.current_stock / Math.max(r.safety_stock, 1) * 100, 100);
        return (
          <div className="w-32">
            <div className="flex justify-between text-xs mb-1">
              <span>{r.current_stock}</span>
              <span className="text-gray-500">/ {r.safety_stock}</span>
            </div>
            <div className="h-2 bg-white/10 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${pct < 30 ? 'bg-red-500' : pct < 60 ? 'bg-amber-500' : 'bg-green-500'}`}
                style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      },
    },
    { key: 'suggested_qty', label: '建议补货', render: (r) => <span className="text-amber-400 font-medium">+{r.suggested_qty}</span> },
    { key: 'estimated_cost', label: '预估成本', render: (r) => `¥${r.estimated_cost.toLocaleString()}` },
    {
      key: 'supplier', label: '供应商', render: (r) => (
        <a href={r.supplier_link} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 text-xs">
          1688搜索 →
        </a>
      ),
    },
  ];

  return (
    <div>
      <Header title="补货管理" />
      <div className="p-6 space-y-4">
        <div className="grid grid-cols-3 gap-4">
          <StatsCard label="需补货商品" value={suggestions.length} icon="📦" />
          <StatsCard label="已选中" value={selected.size} icon="✅" />
          <StatsCard label="预估总成本" value={`¥${totalCost.toLocaleString()}`} icon="💰" />
        </div>

        <Card>
          <div className="p-4 border-b border-white/[0.08] flex justify-between items-center">
            <div className="flex gap-3 items-center">
              <button onClick={selectAll} className="text-xs text-gray-400 hover:text-white">
                {selected.size === suggestions.length ? '取消全选' : '全选'}
              </button>
            </div>
            <button
              onClick={handleCreatePO}
              disabled={!selected.size || loading}
              className="px-4 py-2 bg-amber-500 text-black text-sm font-medium rounded-lg hover:bg-amber-400 disabled:opacity-50"
            >
              {loading ? '生成中...' : `生成采购单 (${selected.size})`}
            </button>
          </div>
          <Table columns={columns} data={suggestions} />
        </Card>

        {poResult && (
          <Card>
            <div className="p-4">
              <h3 className="text-white font-medium mb-2">✅ 采购单已生成</h3>
              <p className="text-sm text-gray-400">单号: {poResult.order_id}</p>
              <p className="text-sm text-gray-400">总金额: ¥{poResult.total_cost?.toLocaleString()}</p>
              <p className="text-sm text-gray-400">商品数: {poResult.items?.length}</p>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
