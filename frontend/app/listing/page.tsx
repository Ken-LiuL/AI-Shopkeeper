'use client';
import { useEffect, useState, useCallback } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { Table, Column } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Modal } from '@/components/ui/modal';
import { Loading } from '@/components/ui/loading';
import { EmptyState } from '@/components/ui/empty-state';
import { getListings, generateListing, getListing, publishListing } from '@/lib/api';
import type { Listing } from '@/lib/types';

const statusMap: Record<string, string> = {
  draft: '草稿',
  reviewing: '审核中',
  published: '已上架',
  failed: '失败',
};

export default function ListingPage() {
  const [listings, setListings] = useState<Listing[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [sourceUrl, setSourceUrl] = useState('');
  const [generating, setGenerating] = useState(false);
  const [detail, setDetail] = useState<Listing | null>(null);
  const pageSize = 20;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getListings({ status: statusFilter || undefined, page, page_size: pageSize });
      setListings(res.data || []);
      setTotal(res.total || 0);
    } catch {} finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const handleGenerate = async () => {
    if (!sourceUrl.trim()) return;
    setGenerating(true);
    try {
      await generateListing(sourceUrl.trim());
      setShowCreate(false);
      setSourceUrl('');
      setTimeout(load, 1500);
    } catch {
      alert('生成失败，请检查链接是否正确');
    } finally {
      setGenerating(false);
    }
  };

  const handleRowClick = async (row: Listing) => {
    try {
      const res = await getListing(row.listing_id);
      setDetail(res.data || row);
    } catch {
      setDetail(row);
    }
  };

  const handlePublish = async (id: string) => {
    try {
      await publishListing(id);
      setDetail(null);
      load();
    } catch {}
  };

  const columns: Column<Listing>[] = [
    { key: 'title', label: '标题', className: 'font-medium text-white max-w-xs truncate' },
    { key: 'platform', label: '来源平台' },
    {
      key: 'status', label: '状态', render: (r) => {
        const badgeMap: Record<string, string> = { draft: 'pending', reviewing: 'running', published: 'active', failed: 'failed' };
        return <Badge value={badgeMap[r.status] || r.status} />;
      },
    },
    { key: 'seo_keywords', label: '关键词', render: (r) => (
      <div className="flex flex-wrap gap-1">
        {(r.seo_keywords || []).slice(0, 3).map((k, i) => (
          <span key={i} className="text-[10px] bg-white/5 text-gray-400 px-1.5 py-0.5 rounded">{k}</span>
        ))}
        {(r.seo_keywords || []).length > 3 && <span className="text-[10px] text-gray-600">+{r.seo_keywords.length - 3}</span>}
      </div>
    )},
    { key: 'price', label: '价格', render: (r) => r.price ? `¥${r.price}` : '-' },
    { key: 'created_at', label: '创建时间', render: (r) => new Date(r.created_at).toLocaleString('zh-CN') },
  ];

  return (
    <div>
      <Header title="上架管理" />
      <div className="p-6 space-y-4">
        <div className="flex flex-wrap gap-3 items-center">
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="bg-white/5 border border-white/[0.08] rounded-lg px-4 py-2 text-sm text-gray-300 outline-none"
          >
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="reviewing">审核中</option>
            <option value="published">已上架</option>
            <option value="failed">失败</option>
          </select>
          <span className="text-sm text-gray-500">共 {total} 条记录</span>
          <Button className="ml-auto" onClick={() => setShowCreate(true)}>🚀 新建上架</Button>
        </div>

        <Card>
          {loading ? (
            <Loading />
          ) : listings.length === 0 ? (
            <EmptyState
              icon="🚀"
              title="暂无上架记录"
              description="点击"新建上架"，输入 1688 或拼多多商品链接，AI 将自动生成标题、描述和 SEO 关键词"
              action={<Button onClick={() => setShowCreate(true)}>新建上架</Button>}
            />
          ) : (
            <Table
              columns={columns}
              data={listings}
              onRowClick={handleRowClick}
              page={page}
              totalPages={Math.ceil(total / pageSize)}
              onPageChange={setPage}
            />
          )}
        </Card>
      </div>

      {/* Create Modal */}
      <Modal open={showCreate} onClose={() => { setShowCreate(false); setSourceUrl(''); }} title="新建上架">
        <div className="space-y-4">
          <div>
            <label className="text-sm text-gray-400 block mb-1.5">商品链接</label>
            <input
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="输入 1688 或拼多多商品链接..."
              className="w-full bg-white/5 border border-white/[0.08] rounded-lg px-4 py-2.5 text-white text-sm outline-none focus:border-amber-500/50 placeholder-gray-500"
            />
            <p className="text-xs text-gray-600 mt-1.5">支持 1688.com、pinduoduo.com 链接，AI 将自动抓取商品信息并生成优化内容</p>
          </div>
          <Button onClick={handleGenerate} disabled={!sourceUrl.trim() || generating} className="w-full">
            {generating ? '生成中...' : '开始生成'}
          </Button>
        </div>
      </Modal>

      {/* Detail Modal */}
      <Modal open={!!detail} onClose={() => setDetail(null)} title="上架详情">
        {detail && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-gray-500">状态</label>
              <div className="mt-1"><Badge value={detail.status} /></div>
            </div>
            <div>
              <label className="text-xs text-gray-500">生成标题</label>
              <p className="text-white text-sm mt-1">{detail.title}</p>
            </div>
            <div>
              <label className="text-xs text-gray-500">商品描述</label>
              <p className="text-gray-300 text-sm mt-1 whitespace-pre-wrap">{detail.description}</p>
            </div>
            <div>
              <label className="text-xs text-gray-500">SEO 关键词</label>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {(detail.seo_keywords || []).map((k, i) => (
                  <span key={i} className="bg-amber-500/10 text-amber-400 text-xs px-2 py-0.5 rounded-full">{k}</span>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500">来源链接</label>
              <a href={detail.source_url} target="_blank" rel="noopener noreferrer" className="text-blue-400 text-sm hover:underline block mt-1 truncate">{detail.source_url}</a>
            </div>
            {detail.price && (
              <div>
                <label className="text-xs text-gray-500">建议售价</label>
                <p className="text-amber-400 font-bold mt-1">¥{detail.price}</p>
              </div>
            )}
            {detail.status === 'draft' && (
              <Button onClick={() => handlePublish(detail.listing_id)} className="w-full">🚀 提交上架</Button>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
