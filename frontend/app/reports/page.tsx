'use client';
import { useEffect, useState, useCallback } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { StatsCard } from '@/components/ui/stats-card';
import { LineChart } from '@/components/charts/line-chart';
import { getDailyReport, getWeeklyReport, getMonthlyReport, getSalesTrend } from '@/lib/api';

type Period = 'daily' | 'weekly' | 'monthly';

export default function ReportsPage() {
  const [period, setPeriod] = useState<Period>('daily');
  const [report, setReport] = useState<any>(null);
  const [trend, setTrend] = useState<any[]>([]);
  const [dateInput, setDateInput] = useState(new Date().toISOString().split('T')[0]);

  const load = useCallback(async () => {
    try {
      let res;
      if (period === 'daily') {
        res = await getDailyReport(dateInput);
      } else if (period === 'weekly') {
        res = await getWeeklyReport();
      } else {
        res = await getMonthlyReport();
      }
      setReport(res.data);
    } catch {}
    try {
      const t = await getSalesTrend();
      setTrend(t.data || []);
    } catch {}
  }, [period, dateInput]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <Header title="经营报表" />
      <div className="p-6 space-y-4">
        {/* Period switcher */}
        <div className="flex gap-2 items-center">
          {(['daily', 'weekly', 'monthly'] as Period[]).map(p => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`px-4 py-2 rounded-lg text-sm ${period === p ? 'bg-amber-500 text-black font-medium' : 'bg-white/5 text-gray-400 hover:text-white'}`}>
              {{ daily: '日报', weekly: '周报', monthly: '月报' }[p]}
            </button>
          ))}
          {period === 'daily' && (
            <input type="date" value={dateInput} onChange={e => setDateInput(e.target.value)}
              className="ml-4 bg-white/5 border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-gray-300 outline-none" />
          )}
        </div>

        {/* KPI Cards */}
        {report && (
          <div className="grid grid-cols-4 gap-4">
            <StatsCard label="销售额" value={`¥${(report.revenue ?? report.total_revenue ?? 0).toLocaleString()}`} icon="💰" />
            <StatsCard label="订单数" value={report.order_count ?? 0} icon="📋" />
            <StatsCard label="客单价" value={`¥${(report.avg_order_value ?? report.avg_order_value ?? 0).toLocaleString()}`} icon="🛒" />
            <StatsCard
              label={period === 'daily' ? '环比昨日' : '退款率'}
              value={period === 'daily' ? `${report.revenue_vs_yesterday > 0 ? '+' : ''}${report.revenue_vs_yesterday?.toFixed(1) ?? 0}%` : `${((report.refund_rate ?? 0) * 100).toFixed(1)}%`}
              icon={period === 'daily' ? '📊' : '↩️'}
            />
          </div>
        )}

        {/* Trend Chart */}
        {trend.length > 0 && (
          <Card>
            <div className="p-4">
              <h3 className="text-white font-medium mb-4">销售趋势 (近30天)</h3>
              <LineChart data={trend.map(t => ({ name: t.date?.slice(5), value: Number(t.revenue) }))} />
            </div>
          </Card>
        )}

        {/* Daily report details */}
        {period === 'daily' && report?.top_products && (
          <div className="grid grid-cols-2 gap-4">
            <Card>
              <div className="p-4">
                <h3 className="text-white font-medium mb-3">🔥 热销 Top 3</h3>
                {report.top_products.map((p: any, i: number) => (
                  <div key={i} className="flex justify-between py-2 border-b border-white/[0.04] text-sm">
                    <span className="text-gray-300">{i + 1}. {p.name}</span>
                    <span className="text-amber-400">销量{p.qty} · ¥{Number(p.revenue).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </Card>
            <Card>
              <div className="p-4">
                <h3 className="text-white font-medium mb-3">🐌 滞销 Top 3</h3>
                {report.slow_products?.map((p: any, i: number) => (
                  <div key={i} className="flex justify-between py-2 border-b border-white/[0.04] text-sm">
                    <span className="text-gray-300">{i + 1}. {p.name}</span>
                    <span className="text-red-400">库存{p.stock} · 7日售{p.daily_sales}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        )}

        {/* Todo items */}
        {period === 'daily' && report?.todo_items?.length > 0 && (
          <Card>
            <div className="p-4">
              <h3 className="text-white font-medium mb-3">📋 明日待办</h3>
              {report.todo_items.map((item: string, i: number) => (
                <div key={i} className="py-1.5 text-sm text-gray-300">• {item}</div>
              ))}
            </div>
          </Card>
        )}

        {/* CS Stats */}
        {period === 'daily' && report?.cs_total !== undefined && (
          <Card>
            <div className="p-4">
              <h3 className="text-white font-medium mb-3">💬 客服统计</h3>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">总咨询</span>
                  <p className="text-white text-lg">{report.cs_total}</p>
                </div>
                <div>
                  <span className="text-gray-500">AI处理率</span>
                  <p className="text-white text-lg">{(report.cs_ai_ratio * 100).toFixed(0)}%</p>
                </div>
                <div>
                  <span className="text-gray-500">转人工</span>
                  <p className="text-white text-lg">{report.cs_human_transfer}</p>
                </div>
              </div>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
