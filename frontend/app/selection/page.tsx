'use client';
import { useEffect, useState } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { Table, Column } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { triggerSelection, getSelectionRuns, getRecommendations } from '@/lib/api';
import type { SelectionRunSummary, Recommendation } from '@/lib/types';

function ScoreBar({ label, value, max = 100 }: { label: string; value: number; max?: number }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-500 w-16 shrink-0 truncate">{label}</span>
      <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
        <div className="h-full bg-amber-500 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-400 w-8 text-right">{value.toFixed(1)}</span>
    </div>
  );
}

export default function SelectionPage() {
  const [runs, setRuns] = useState<SelectionRunSummary[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    try {
      const [runsRes, recsRes] = await Promise.all([getSelectionRuns(), getRecommendations()]);
      setRuns(runsRes.data || []);
      setRecs(recsRes.data || []);
    } catch {}
  };

  useEffect(() => { load(); }, []);

  const handleRun = async () => {
    setLoading(true);
    try {
      await triggerSelection();
      setTimeout(load, 2000);
    } catch {} finally {
      setLoading(false);
    }
  };

  const runCols: Column<SelectionRunSummary>[] = [
    { key: 'run_id', label: 'ID', render: (r) => <span className="text-gray-500 font-mono text-xs">{r.run_id.slice(0, 12)}</span> },
    { key: 'status', label: '状态', render: (r) => <Badge value={r.status} /> },
    { key: 'result_count', label: '推荐数', render: (r) => <span className="text-amber-400">{r.result_count}</span> },
    { key: 'created_at', label: '时间', render: (r) => r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : '-' },
  ];

  return (
    <div>
      <Header title="选品推荐" />
      <div className="p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h3 className="text-white font-semibold">选品推荐</h3>
          <Button onClick={handleRun} disabled={loading}>
            {loading ? '运行中...' : '🎯 开始选品'}
          </Button>
        </div>

        <Card>
          <h4 className="text-white font-medium mb-3">运行历史</h4>
          <Table columns={runCols} data={runs.slice(0, 10)} />
        </Card>

        <Card>
          <h4 className="text-white font-medium mb-4">最新推荐列表</h4>
          {recs.length === 0 ? (
            <p className="text-gray-500 text-sm py-8 text-center">暂无推荐数据，点击"开始选品"生成</p>
          ) : (
            <div className="space-y-4">
              {recs.map((rec, i) => {
                const score = rec.score ?? rec.total_score ?? 0;
                const breakdown = rec.breakdown || {};
                return (
                  <div key={i} className="border border-white/[0.06] rounded-lg p-4 hover:border-amber-500/20 transition-colors">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <span className="text-amber-500 font-bold text-lg">#{rec.rank ?? i + 1}</span>
                        <div>
                          <div className="text-white font-medium">{rec.product_name || rec.name || '未知商品'}</div>
                          {rec.suggestion && <div className="text-gray-500 text-xs mt-0.5">{rec.suggestion}</div>}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-2xl font-bold text-amber-400">{score.toFixed(1)}</div>
                        <div className="text-xs text-gray-500">综合分</div>
                      </div>
                    </div>
                    {Object.keys(breakdown).length > 0 && (
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1.5">
                        {Object.entries(breakdown).map(([k, v]) => (
                          <ScoreBar key={k} label={k} value={Number(v)} />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
