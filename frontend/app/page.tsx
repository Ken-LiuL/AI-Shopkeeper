'use client';
import { useEffect, useState } from 'react';
import { Header } from '@/components/layout/header';
import { StatsCard } from '@/components/ui/stats-card';
import { Card } from '@/components/ui/card';
import { Table, Column } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { LineChart } from '@/components/charts/line-chart';
import { getDashboardOverview, getSalesTrend, getTopProducts, getAlerts } from '@/lib/api';
import type { DashboardOverview, SalesTrendPoint, TopProduct, Alert } from '@/lib/types';

export default function DashboardPage() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [trend, setTrend] = useState<SalesTrendPoint[]>([]);
  const [topProducts, setTopProducts] = useState<TopProduct[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);

  useEffect(() => {
    getDashboardOverview().then((r) => setOverview(r.data)).catch(() => {});
    getSalesTrend().then((r) => setTrend(r.data || [])).catch(() => {});
    getTopProducts().then((r) => setTopProducts(r.data || [])).catch(() => {});
    getAlerts({ status: 'pending' }).then((r) => setAlerts((r.data || []).slice(0, 5))).catch(() => {});
  }, []);

  const stats = [
    { title: '商品总数', value: overview?.total_products ?? '-', icon: '📦' },
    { title: '今日订单', value: overview?.today_orders ?? '-', icon: '🛒' },
    { title: '活跃预警', value: overview?.pending_alerts ?? '-', icon: '🔔' },
    { title: '待处理任务', value: overview?.pending_tasks ?? '-', icon: '⏳' },
  ];

  const topColsWithIndex: Column<TopProduct & { _idx: number }>[] = [
    { key: 'rank', label: '#', render: (r) => <span className="text-gray-500">{r._idx + 1}</span> },
    { key: 'name', label: '商品' },
    { key: 'total_sales', label: '销量', render: (r) => <span className="text-amber-400">{r.total_sales}</span> },
    { key: 'revenue', label: '营收', render: (r) => <span>¥{Number(r.revenue).toLocaleString()}</span> },
  ];

  const alertCols: Column<Alert>[] = [
    { key: 'alert_type', label: '类型' },
    { key: 'message', label: '内容' },
    { key: 'severity', label: '严重度', render: (r) => <Badge value={r.severity} /> },
    { key: 'created_at', label: '时间', render: (r) => new Date(r.created_at).toLocaleString('zh-CN') },
  ];

  return (
    <div>
      <Header title="总览" />
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {stats.map((s) => (
            <StatsCard key={s.title} title={s.title} value={s.value} icon={s.icon} />
          ))}
        </div>

        <Card>
          <h3 className="text-white font-semibold mb-4">30 天销量趋势</h3>
          {trend.length > 0 ? (
            <LineChart data={trend} xKey="date" yKey="quantity" label="销量" />
          ) : (
            <div className="h-[300px] flex items-center justify-center text-gray-500">暂无数据</div>
          )}
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <h3 className="text-white font-semibold mb-4">TOP 10 热销商品</h3>
            <Table columns={topColsWithIndex} data={topProducts.map((p, i) => ({ ...p, _idx: i }))} />
          </Card>

          <Card>
            <h3 className="text-white font-semibold mb-4">最新预警</h3>
            <Table columns={alertCols} data={alerts} />
          </Card>
        </div>
      </div>
    </div>
  );
}
