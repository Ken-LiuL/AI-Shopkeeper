'use client';
import { useEffect, useState, useCallback } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { Table, Column } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Modal } from '@/components/ui/modal';
import { getProducts, getProduct } from '@/lib/api';
import type { Product } from '@/lib/types';

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [selected, setSelected] = useState<Product | null>(null);
  const pageSize = 20;

  const load = useCallback(async () => {
    try {
      const res = await getProducts({ page, page_size: pageSize, search: search || undefined, status: statusFilter || undefined });
      setProducts(res.data || []);
      setTotal(res.total || 0);
    } catch {}
  }, [page, search, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const columns: Column<Product>[] = [
    { key: 'name', label: '名称', className: 'font-medium text-white' },
    { key: 'category', label: '品类' },
    { key: 'brand', label: '品牌' },
    { key: 'cost_price', label: '成本价', render: (r) => r.cost_price != null ? `¥${r.cost_price}` : '-' },
    { key: 'retail_price', label: '零售价', render: (r) => r.retail_price != null ? `¥${r.retail_price}` : '-' },
    { key: 'stock', label: '库存', render: (r) => <span className={r.stock < 10 ? 'text-red-400' : ''}>{r.stock}</span> },
    { key: 'status', label: '状态', render: (r) => <Badge value={r.status} /> },
  ];

  const handleRowClick = async (row: Product) => {
    try {
      const res = await getProduct(row.product_id);
      setSelected(res.data);
    } catch {
      setSelected(row);
    }
  };

  return (
    <div>
      <Header title="商品管理" />
      <div className="p-6 space-y-4">
        <div className="flex flex-wrap gap-3 items-center">
          <input
            type="text"
            placeholder="搜索商品名称或条码..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="bg-white/5 border border-white/[0.08] rounded-lg px-4 py-2 text-sm text-white placeholder-gray-500 outline-none focus:border-amber-500/50 w-72"
          />
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="bg-white/5 border border-white/[0.08] rounded-lg px-4 py-2 text-sm text-gray-300 outline-none"
          >
            <option value="">全部状态</option>
            <option value="active">在售</option>
            <option value="inactive">下架</option>
            <option value="delisted">淘汰</option>
          </select>
          <span className="text-sm text-gray-500 ml-auto">共 {total} 件商品</span>
        </div>

        <Card>
          <Table
            columns={columns}
            data={products}
            onRowClick={handleRowClick}
            page={page}
            totalPages={Math.ceil(total / pageSize)}
            onPageChange={setPage}
          />
        </Card>
      </div>

      <Modal open={!!selected} onClose={() => setSelected(null)} title="商品详情">
        {selected && (
          <div className="space-y-3 text-sm">
            {[
              ['名称', selected.name],
              ['品类', selected.category],
              ['品牌', selected.brand],
              ['条码', selected.barcode],
              ['成本价', selected.cost_price != null ? `¥${selected.cost_price}` : '-'],
              ['零售价', selected.retail_price != null ? `¥${selected.retail_price}` : '-'],
              ['库存', selected.stock],
              ['状态', selected.status],
              ['描述', selected.description || '-'],
            ].map(([label, value]) => (
              <div key={label as string} className="flex">
                <span className="text-gray-500 w-20 shrink-0">{label}</span>
                <span className="text-gray-200">{String(value || '-')}</span>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}
