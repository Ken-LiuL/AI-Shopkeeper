'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { StatsCard } from '@/components/ui/stats-card';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { withErrorBoundary } from '@/components/error-boundary';
import { Tooltip as OnboardingTooltip } from '@/components/onboarding/guide';
import { getDashboardOverview, getSalesTrend, getAlerts, getDailyInsights } from '@/lib/api';
import type { DashboardOverview, SalesTrendData, Alert, DailyInsight } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function DashboardPage() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [trend, setTrend] = useState<SalesTrendData[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [insights, setInsights] = useState<DailyInsight | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const [overviewData, trendData, alertsData, insightsData] = await Promise.all([
          getDashboardOverview(),
          getSalesTrend(),
          getAlerts(),
          getDailyInsights(),
        ]);
        setOverview(overviewData);
        setTrend(trendData);
        setAlerts(alertsData.slice(0, 5)); // Show only latest 5 alerts
        setInsights(insightsData);
      } catch (error) {
        console.error('Error fetching dashboard data:', error);
        setError('加载数据失败，请稍后重试');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
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
        <div>
          <h1 className="text-3xl font-bold tracking-tight">仪表盘</h1>
          <p className="text-muted-foreground">欢迎回到 AI 店长智能管理后台</p>
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

  const stats = [
    {
      title: '今日订单',
      value: overview?.today_orders ? Number(overview.today_orders).toLocaleString() : '0',
      icon: '📋',
      tooltip: '今日新增订单数量（来源 qnh_orders_raw）'
    },
    {
      title: '今日营收',
      value: overview?.today_gmv ? `¥${Number(overview.today_gmv).toLocaleString()}` : '-',
      icon: '💰',
      tooltip: '今日营收（来源 qnh_orders_raw.total 汇总）'
    },
    {
      title: '评价评分',
      value: Number(overview?.avg_rating || 0).toFixed(2),
      icon: '⭐',
      tooltip: '今日平均评分（来源 qnh_reviews_raw）'
    },
    {
      title: '库存预警数',
      value: Number(overview?.pending_alerts || 0).toLocaleString(),
      icon: '📦',
      tooltip: '库存低于 10 的商品数（来源 qnh_inventory）'
    },
  ];

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'high': return 'destructive';
      case 'medium': return 'secondary';
      case 'low': return 'outline';
      default: return 'outline';
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">仪表盘</h1>
        <p className="text-muted-foreground">欢迎回到 AI 店长智能管理后台</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <OnboardingTooltip key={stat.title} text={stat.tooltip || ''}>
            <div>
              <StatsCard title={stat.title} value={stat.value} icon={stat.icon} />
            </div>
          </OnboardingTooltip>
        ))}
      </div>

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>🔔</span>
              最新预警
              {overview?.pending_alerts && (
                <Badge variant="secondary">{overview.pending_alerts}</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {alerts.length > 0 ? (
              <div className="space-y-3">
                {alerts.map((alert, index) => (
                  <div key={index} className="flex items-start justify-between p-3 bg-muted/50 rounded-lg">
                    <div className="space-y-1">
                      <p className="text-sm font-medium">{alert.title || alert.type}</p>
                      <p className="text-sm text-muted-foreground">{alert.description || alert.message}</p>
                    </div>
                    <Badge variant={getSeverityColor(alert.severity)}>
                      {alert.severity === 'high' ? '严重' : alert.severity === 'medium' ? '中等' : '轻微'}
                    </Badge>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                暂无预警信息
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>⚡</span>
              快速操作
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3">
              <button className="p-4 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors text-left">
                <div className="text-2xl mb-2">📦</div>
                <div className="text-sm font-medium">商品管理</div>
                <div className="text-xs text-muted-foreground">管理库存和价格</div>
              </button>
              <button className="p-4 bg-green-50 hover:bg-green-100 rounded-lg transition-colors text-left">
                <div className="text-2xl mb-2">💬</div>
                <div className="text-sm font-medium">AI 客服</div>
                <div className="text-xs text-muted-foreground">智能客户服务</div>
              </button>
              <button className="p-4 bg-purple-50 hover:bg-purple-100 rounded-lg transition-colors text-left">
                <div className="text-2xl mb-2">📊</div>
                <div className="text-sm font-medium">数据分析</div>
                <div className="text-xs text-muted-foreground">查看详细报表</div>
              </button>
              <button className="p-4 bg-orange-50 hover:bg-orange-100 rounded-lg transition-colors text-left">
                <div className="text-2xl mb-2">🏪</div>
                <div className="text-sm font-medium">竞品监控</div>
                <div className="text-xs text-muted-foreground">价格对比分析</div>
              </button>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* AI 经营洞察面板 */}
      {insights && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>🤖</span>
              AI 经营洞察
              <Badge variant="outline">每日更新</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-4">
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
                      📊 销售异常
                    </h4>
                    <div className="text-sm text-gray-700 bg-blue-50 p-3 rounded-lg">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {insights.sales_anomalies}
                      </ReactMarkdown>
                    </div>
                  </div>

                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
                      🔥 热销变化
                    </h4>
                    <div className="text-sm text-gray-700 bg-green-50 p-3 rounded-lg">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {insights.hot_products_changes}
                      </ReactMarkdown>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
                      🏪 竞品动态
                    </h4>
                    <div className="text-sm text-gray-700 bg-yellow-50 p-3 rounded-lg">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {insights.competitor_dynamics}
                      </ReactMarkdown>
                    </div>
                  </div>

                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
                      💡 可操作建议
                    </h4>
                    <div className="text-sm text-gray-700 bg-purple-50 p-3 rounded-lg">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {insights.actionable_suggestions}
                      </ReactMarkdown>
                    </div>
                  </div>
                </div>
              </div>

              <div className="text-xs text-gray-500 text-center border-t pt-4">
                📅 数据更新时间: {new Date(insights.date).toLocaleString('zh-CN')}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default withErrorBoundary(DashboardPage);
