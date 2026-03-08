'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { StatsCard } from '@/components/ui/stats-card';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { withErrorBoundary } from '@/components/error-boundary';
import { Tooltip as OnboardingTooltip } from '@/components/onboarding/guide';
import { getDashboardOverview, getSalesTrend, getAlerts, getDailyInsights, getAIWorkStats } from '@/lib/api';
import type { DashboardOverview, SalesTrendData, Alert, DailyInsight, AIWorkStats } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function DashboardPage() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [trend, setTrend] = useState<SalesTrendData[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [insights, setInsights] = useState<DailyInsight | null>(null);
  const [aiStats, setAiStats] = useState<AIWorkStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [insightsTime] = useState(() => {
    const now = new Date();
    return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
  });

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

        // AI stats — non-blocking, fallback gracefully
        try {
          const aiData = await getAIWorkStats();
          setAiStats(aiData);
        } catch {
          // fallback: show zeros
          setAiStats({
            totalActions: 0,
            alertsHandled: 0,
            csReplies: 0,
            pricingAdj: 0,
            selectionRuns: 0,
            bundlesCreated: 0,
            listingsOptimized: 0,
            estimatedSaved: '0',
            reflectionRounds: 0,
            factChecks: 0,
          });
        }
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

  const getAlertRecommendation = (alert: Alert): string => {
    if (alert.recommended_action) return alert.recommended_action;
    if (alert.action_suggestions && alert.action_suggestions.length > 0) {
      return alert.action_suggestions[0];
    }
    // Generate smart fallback based on alert type
    const type = (alert.type || '').toLowerCase();
    if (type.includes('stock') || type.includes('inventory')) return '建议立即补货，避免断货影响销售';
    if (type.includes('price')) return '建议参考竞品调整定价策略';
    if (type.includes('review') || type.includes('rating')) return '建议主动联系客户了解问题并改进';
    return 'AI 正在分析最优处理方案，请稍后查看';
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">仪表盘</h1>
        <p className="text-muted-foreground">欢迎回到 AI 店长智能管理后台</p>
      </div>

      {/* ── AI 价值横幅 ── */}
      {aiStats && (
        <Card className="bg-gradient-to-r from-blue-600 to-purple-600 text-white border-none shadow-lg">
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold">🤖 AI 店长今日工作汇报</h2>
                <p className="text-blue-100 mt-1">AI 24小时不间断为您的店铺保驾护航</p>
              </div>
              <div className="text-right">
                <div className="text-4xl font-bold">{aiStats.totalActions}</div>
                <div className="text-blue-100 text-sm">今日 AI 操作次数</div>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
              <div className="bg-white/10 rounded-lg p-3">
                <div className="text-2xl font-bold">{aiStats.alertsHandled}</div>
                <div className="text-sm text-blue-100">🔔 处理预警</div>
              </div>
              <div className="bg-white/10 rounded-lg p-3">
                <div className="text-2xl font-bold">{aiStats.csReplies}</div>
                <div className="text-sm text-blue-100">💬 自动回复客户</div>
              </div>
              <div className="bg-white/10 rounded-lg p-3">
                <div className="text-2xl font-bold">{aiStats.pricingAdj}</div>
                <div className="text-sm text-blue-100">💰 定价建议</div>
              </div>
              <div className="bg-white/10 rounded-lg p-3">
                <div className="text-2xl font-bold">¥{aiStats.estimatedSaved}</div>
                <div className="text-sm text-blue-100">📈 预估增收</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Stats 卡片 ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <OnboardingTooltip key={stat.title} text={stat.tooltip || ''}>
            <div>
              <StatsCard title={stat.title} value={stat.value} icon={stat.icon} />
            </div>
          </OnboardingTooltip>
        ))}
      </div>

      {/* ── AI 经营洞察（移到 stats 正下方） ── */}
      {insights && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>🤖</span>
              AI 经营洞察
              <Badge variant="outline">每日更新</Badge>
              <span className="ml-auto text-xs font-normal text-muted-foreground">
                AI 于 {insightsTime} 分析完成
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-4">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                        📊 销售异常
                      </h4>
                      <Button size="sm" variant="outline" className="h-7 text-xs">
                        一键采纳
                      </Button>
                    </div>
                    <div className="text-sm text-gray-700 bg-blue-50 p-3 rounded-lg">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {insights.sales_anomalies}
                      </ReactMarkdown>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                        🔥 热销变化
                      </h4>
                      <Button size="sm" variant="outline" className="h-7 text-xs">
                        一键采纳
                      </Button>
                    </div>
                    <div className="text-sm text-gray-700 bg-green-50 p-3 rounded-lg">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {insights.hot_products_changes}
                      </ReactMarkdown>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                        🏪 竞品动态
                      </h4>
                      <Button size="sm" variant="outline" className="h-7 text-xs">
                        一键采纳
                      </Button>
                    </div>
                    <div className="text-sm text-gray-700 bg-yellow-50 p-3 rounded-lg">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {insights.competitor_dynamics}
                      </ReactMarkdown>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                        💡 可操作建议
                      </h4>
                      <Button size="sm" variant="outline" className="h-7 text-xs">
                        一键采纳
                      </Button>
                    </div>
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

      {/* ── 销售趋势图 ── */}
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
        {/* ── 最新预警（增强版） ── */}
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
                  <div key={index} className="p-3 bg-muted/50 rounded-lg space-y-2">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1 flex-1 mr-3">
                        <p className="text-sm font-medium">{alert.title || alert.type}</p>
                        <p className="text-sm text-muted-foreground">{alert.description || alert.message}</p>
                      </div>
                      <Badge variant={getSeverityColor(alert.severity)}>
                        {alert.severity === 'high' ? '严重' : alert.severity === 'medium' ? '中等' : '轻微'}
                      </Badge>
                    </div>
                    {/* AI 处理建议 */}
                    <div className="flex items-start gap-2 bg-blue-50 rounded p-2">
                      <span className="text-blue-500 text-xs mt-0.5 shrink-0">🤖 AI建议：</span>
                      <p className="text-xs text-blue-700 flex-1">{getAlertRecommendation(alert)}</p>
                      <Button size="sm" variant="outline" className="h-6 text-xs shrink-0 border-blue-300 text-blue-700 hover:bg-blue-100">
                        采纳建议
                      </Button>
                    </div>
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

        {/* ── 快速操作（加 AI 标识） ── */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>⚡</span>
              快速操作
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3">
              <button className="p-4 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors text-left relative">
                <span className="absolute top-2 right-2 text-[10px] bg-blue-500 text-white px-1.5 py-0.5 rounded-full font-medium">AI 驱动</span>
                <div className="text-2xl mb-2">📦</div>
                <div className="text-sm font-medium">商品管理</div>
                <div className="text-xs text-muted-foreground">管理库存和价格</div>
              </button>
              <button className="p-4 bg-green-50 hover:bg-green-100 rounded-lg transition-colors text-left relative">
                <span className="absolute top-2 right-2 text-[10px] bg-green-500 text-white px-1.5 py-0.5 rounded-full font-medium">AI 驱动</span>
                <div className="text-2xl mb-2">💬</div>
                <div className="text-sm font-medium">AI 客服</div>
                <div className="text-xs text-muted-foreground">智能客户服务</div>
              </button>
              <button className="p-4 bg-purple-50 hover:bg-purple-100 rounded-lg transition-colors text-left relative">
                <span className="absolute top-2 right-2 text-[10px] bg-purple-500 text-white px-1.5 py-0.5 rounded-full font-medium">AI 驱动</span>
                <div className="text-2xl mb-2">📊</div>
                <div className="text-sm font-medium">数据分析</div>
                <div className="text-xs text-muted-foreground">查看详细报表</div>
              </button>
              <button className="p-4 bg-orange-50 hover:bg-orange-100 rounded-lg transition-colors text-left relative">
                <span className="absolute top-2 right-2 text-[10px] bg-orange-500 text-white px-1.5 py-0.5 rounded-full font-medium">AI 驱动</span>
                <div className="text-2xl mb-2">🏪</div>
                <div className="text-sm font-medium">竞品监控</div>
                <div className="text-xs text-muted-foreground">价格对比分析</div>
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default withErrorBoundary(DashboardPage);
