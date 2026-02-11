'use client';
import { useEffect, useState } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Modal } from '@/components/ui/modal';
import { getBundles, generateBundles, updateBundle, deleteBundle } from '@/lib/api';
import type { Bundle } from '@/lib/types';

export default function BundlesPage() {
  const [bundles, setBundles] = useState<Bundle[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<Bundle | null>(null);
  const [editPrice, setEditPrice] = useState('');
  const [editName, setEditName] = useState('');

  const load = async () => {
    try {
      const res = await getBundles();
      setBundles(res.data || []);
    } catch {}
  };

  useEffect(() => { load(); }, []);

  const handleGenerate = async () => {
    setLoading(true);
    try {
      await generateBundles();
      setTimeout(load, 3000);
    } catch {} finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('确定删除此套餐？')) return;
    try {
      await deleteBundle(id);
      load();
    } catch {}
  };

  const handleEdit = (b: Bundle) => {
    setEditing(b);
    setEditName(b.name);
    setEditPrice(String(b.bundle_price));
  };

  const handleSave = async () => {
    if (!editing) return;
    try {
      await updateBundle(editing.bundle_id, { name: editName, bundle_price: Number(editPrice) });
      setEditing(null);
      load();
    } catch {}
  };

  return (
    <div>
      <Header title="套餐管理" />
      <div className="p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h3 className="text-white font-semibold">套餐列表</h3>
          <Button onClick={handleGenerate} disabled={loading}>
            {loading ? '生成中...' : '🎁 生成套餐'}
          </Button>
        </div>

        {bundles.length === 0 ? (
          <Card><p className="text-gray-500 text-center py-8">暂无套餐，点击"生成套餐"自动创建</p></Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {bundles.map((b) => {
              const discount = b.original_price > 0 ? Math.round((1 - b.bundle_price / b.original_price) * 100) : 0;
              return (
                <Card key={b.bundle_id}>
                  <div className="space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <h4 className="text-white font-semibold">{b.name}</h4>
                        {b.tagline && <p className="text-gray-500 text-xs mt-1">{b.tagline}</p>}
                      </div>
                      {discount > 0 && (
                        <span className="bg-red-500/20 text-red-400 text-xs font-bold px-2 py-0.5 rounded">-{discount}%</span>
                      )}
                    </div>

                    <div className="space-y-1">
                      {(b.products || []).map((item: { name: string; unit_price: number }, i: number) => (
                        <div key={i} className="text-sm text-gray-400 flex justify-between">
                          <span>{item.name}</span>
                          <span className="text-gray-600">¥{item.unit_price}</span>
                        </div>
                      ))}
                    </div>

                    <div className="flex items-baseline gap-2 pt-2 border-t border-white/[0.06]">
                      <span className="text-gray-500 line-through text-sm">¥{b.original_price}</span>
                      <span className="text-amber-400 font-bold text-lg">¥{b.bundle_price}</span>
                    </div>

                    <div className="flex gap-2 pt-1">
                      <Button variant="secondary" className="flex-1 text-xs" onClick={() => handleEdit(b)}>编辑</Button>
                      <Button variant="danger" className="text-xs" onClick={() => handleDelete(b.bundle_id)}>删除</Button>
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title="编辑套餐">
        {editing && (
          <div className="space-y-4">
            <div>
              <label className="text-sm text-gray-400 block mb-1">套餐名称</label>
              <input value={editName} onChange={(e) => setEditName(e.target.value)} className="w-full bg-white/5 border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm outline-none focus:border-amber-500/50" />
            </div>
            <div>
              <label className="text-sm text-gray-400 block mb-1">套餐价格</label>
              <input type="number" value={editPrice} onChange={(e) => setEditPrice(e.target.value)} className="w-full bg-white/5 border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm outline-none focus:border-amber-500/50" />
            </div>
            <Button onClick={handleSave} className="w-full">保存</Button>
          </div>
        )}
      </Modal>
    </div>
  );
}
