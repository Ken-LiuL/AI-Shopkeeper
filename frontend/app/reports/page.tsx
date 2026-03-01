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
import { getDailyReport, getSalesTrend } from '@/lib/api';
import type { ReportData, SalesTrendData } from '@/lib/api';

type Period = 'daily' | 'weekly' | 'monthly';

export default function ReportsPage() {
  const [period, setPeriod] = useState<Period>('daily');
  const [report, setReport] = useState<ReportData | null>(null);
  const [trend, setTrend] = useState<SalesTrendData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [reportData, trendData] = await Promise.all([
          getDailyReport(),
          getSalesTrend(),
        ]);
        setReport(reportData);
        setTrend(trendData);
      } catch (error) {
        console.error('Error fetching report data:', error);
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
          {Object.entries(report.metrics).map(([key, value]) => (
            <Card key={key}>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground capitalize">
                      {key.replace('_', ' ')}
                    </p>
                    <p className="text-2xl font-bold">
                      {typeof value === 'number' && key.includes('revenue')
                        ? `¥${value.toLocaleString()}`
                        : String(value)}
                    </p>
                  </div>
                  <div className="text-3xl opacity-80">
                    {key.includes('revenue') ? '💰' : key.includes('order') ? '📋' : '📊'}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
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
              <LineChart data={trend}>
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

      {/* Top Products */}
      {report?.top_products && report.top_products.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>🏆</span>
              热销商品排行
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableCaption>本期热销商品排行榜</TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[100px]">排名</TableHead>
                  <TableHead>商品名称</TableHead>
                  <TableHead className="text-right">销售额/数量</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {report.top_products.map((product, index) => (
                  <TableRow key={index}>
                    <TableCell>
                      <Badge variant={index < 3 ? "default" : "secondary"}>
                        #{index + 1}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-medium">{product.name}</TableCell>
                    <TableCell className="text-right font-semibold">
                      {typeof product.value === 'number' && product.value > 1000
                        ? `¥${product.value.toLocaleString()}`
                        : product.value}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

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
                <Badge variant="outline">{report.period}</Badge>
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
