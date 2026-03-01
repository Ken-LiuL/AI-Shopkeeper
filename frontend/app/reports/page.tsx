'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { withErrorBoundary } from '@/components/error-boundary';
import { getDailyReport, getWeeklyReport, getMonthlyReport, getSalesTrend } from '@/lib/api';
import type { ReportData, SalesTrendData } from '@/lib/api';

type Period = 'daily' | 'weekly' | 'monthly';

function ReportsPage() {
  const [period, setPeriod] = useState<Period>('daily');
  const [report, setReport] = useState<ReportData | null>(null);
  const [trend, setTrend] = useState<SalesTrendData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        let reportPromise;
        if (period === 'weekly') {
          reportPromise = getWeeklyReport();
        } else if (period === 'monthly') {
          reportPromise = getMonthlyReport();
        } else {
          reportPromise = getDailyReport();
        }

        const [reportData, trendData] = await Promise.all([
          reportPromise,
          getSalesTrend(),
        ]);
        setReport(reportData);
        setTrend(trendData);
      } catch (error) {
        console.error('Error fetching report data:', error);
        setError('加载报表数据失败，请稍后重试');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [period]);

  const tabs = [
    { key: 'daily' as const, label: '日报', icon: '📅' },
    { key: 'weekly' as const, label: '周报', icon: '📊' },
    { key: 'monthly' as const, label: '月报', icon: '📈' },
  ];

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">经营报表</h1>
            <p className="text-muted-foreground">查看详细的业务数据和表现指标</p>
          </div>
          <Button disabled>导出报表</Button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="h-20 bg-muted animate-pulse rounded"></div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">经营报表</h1>
            <p className="text-muted-foreground">查看详细的业务数据和表现指标</p>
          </div>
          <Button disabled>导出报表</Button>
        </div>
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <div className="text-red-500 text-4xl mb-4">⚠️</div>
            <h3 className="text-lg font-medium text-red-800 mb-2">数据加载失败</h3>
            <p className="text-red-600 mb-4">{error}</p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600"
            >
              重新加载
            </button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">经营报表</h1>
          <p className="text-muted-foreground">查看详细的业务数据和表现指标</p>
        </div>
        <Button>导出报表</Button>
      </div>

      {/* Period Tabs */}
      <div className="flex gap-2">
        {tabs.map((tab) => (
          <Button
            key={tab.key}
            variant={period === tab.key ? "default" : "outline"}
            onClick={() => setPeriod(tab.key)}
            className="flex items-center gap-2"
          >
            <span>{tab.icon}</span>
            {tab.label}
          </Button>
        ))}
      </div>

      {/* Metrics Cards */}
      {report && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">订单数</p>
                  <p className="text-2xl font-bold">{Number(report.order_count).toLocaleString()}</p>
                </div>
                <div className="text-3xl opacity-80">📋</div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">总收入</p>
                  <p className="text-2xl font-bold">¥{Number(report.total_revenue).toLocaleString()}</p>
                </div>
                <div className="text-3xl opacity-80">💰</div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">平均客单价</p>
                  <p className="text-2xl font-bold">¥{Number(report.avg_order_value).toFixed(2)}</p>
                </div>
                <div className="text-3xl opacity-80">🛒</div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Sales Trend Chart */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>📈</span>
            销售趋势
          </CardTitle>
        </CardHeader>
        <CardContent>
          {trend.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={trend.map(item => ({
                date: item.date,
                gmv: Number(item.revenue || 0),
                orders: Number(item.quantity || 0)
              }))}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => new Date(value).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })}
                />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(value: number, name: string) => [
                    name === 'gmv' ? `¥${value.toLocaleString()}` : value,
                    name === 'gmv' ? 'GMV' : '订单数'
                  ]}
                  labelFormatter={(value) => new Date(value).toLocaleDateString('zh-CN')}
                />
                <Line
                  type="monotone"
                  dataKey="gmv"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  name="gmv"
                />
                <Line
                  type="monotone"
                  dataKey="orders"
                  stroke="#10b981"
                  strokeWidth={2}
                  name="orders"
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-muted-foreground">
              暂无数据
            </div>
          )}
        </CardContent>
      </Card>

      {/* Additional Metrics */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>📊</span>
            详细指标
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">退款率</p>
              <p className="text-lg font-semibold">{Number(report?.refund_rate || 0).toFixed(2)}%</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">退款订单</p>
              <p className="text-lg font-semibold">{Number(report?.refund_count || 0).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">客服响应</p>
              <p className="text-lg font-semibold">{Number(report?.cs_responses || 0).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">实际客单价</p>
              <p className="text-lg font-semibold">¥{Number(report?.avg_order_value_paid || 0).toFixed(2)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Report Summary */}
      {report && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>📋</span>
              报表总结
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="font-medium">报表周期</span>
                <Badge variant="outline">{report.data_period || `${period}报表`}</Badge>
              </div>
              <div className="text-sm text-muted-foreground">
                本报表反映了{period === 'daily' ? '当日' : period === 'weekly' ? '本周' : '本月'}的经营状况。
                通过分析销售趋势和商品表现，帮助您制定更好的经营策略。
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default withErrorBoundary(ReportsPage);
