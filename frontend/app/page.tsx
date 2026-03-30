'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { withErrorBoundary } from '@/components/error-boundary';
import { fetchAPI, getDashboardOverview, getAlerts, getDailyInsights, getAIWorkStats } from '@/lib/api';
import type { DashboardOverview, Alert, DailyInsight, AIWorkStats } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function DashboardPage() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [insights, setInsights] = useState<DailyInsight | null>(null);
  const [aiStats, setAiStats] = useState<AIWorkStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [insightsTime] = useState(() => {
    const now = new Date();
    return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
  });

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const [overviewData, alertsData, insightsData] = await Promise.all([
          getDashboardOverview(),
          getAlerts(),
          getDailyInsights(),
        ]);
        setOverview(overviewData);
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
            dataImports: 0,
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
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {[1, 2, 3, 4, 5].map((i) => (
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
          <h1 className="text-3xl font-bold tracking-tight">AI 指挥台</h1>
          <p className="text-muted-foreground">今天先处理最关键的问题，再让 AI 帮你补齐数据、客服和经营动作。</p>
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

  const todayGMV = Number(overview?.today_gmv || 0);
  const yesterdayGMV = Number(overview?.yesterday_gmv || 0);
  const todayOrders = Number(overview?.today_orders || 0);
  const yesterdayOrders = Number(overview?.yesterday_orders || 0);
  const avgOrderValue = Number(overview?.avg_order_value || 0);

  const commandStats = [
    {
      title: '今日 GMV',
      value: `¥${todayGMV.toLocaleString()}`,
      hint: yesterdayGMV > 0
        ? `昨日 ¥${yesterdayGMV.toLocaleString()}，${todayGMV >= yesterdayGMV ? '▲' : '▼'} ${yesterdayGMV > 0 ? Math.abs(Math.round((todayGMV - yesterdayGMV) / yesterdayGMV * 100)) : 0}%`
        : '今日真实订单 GMV',
    },
    {
      title: '今日订单数',
      value: todayOrders.toLocaleString(),
      hint: yesterdayOrders > 0
        ? `昨日 ${yesterdayOrders} 单，${todayOrders >= yesterdayOrders ? '▲' : '▼'} ${yesterdayOrders > 0 ? Math.abs(Math.round((todayOrders - yesterdayOrders) / yesterdayOrders * 100)) : 0}%`
        : '基于真实订单数据',
    },
    {
      title: '客单价',
      value: avgOrderValue > 0 ? `¥${avgOrderValue.toFixed(2)}` : '—',
      hint: '今日平均每单金额',
    },
    {
      title: '低库存商品',
      value: Number(overview?.low_stock_count || 0).toLocaleString(),
      hint: '库存 < 10 件，建议及时补货',
    },
    {
      title: '待处理预警',
      value: Number(overview?.pending_alerts || 0).toLocaleString(),
      hint: '优先处理断货、主档缺口和严重异常',
    },
  ];

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
      case 'high': return 'destructive';
      case 'warning':
      case 'medium': return 'secondary';
      case 'info':
      case 'low': return 'outline';
      default: return 'outline';
    }
  };

  const getPriorityBadge = (priority: string) => {
    switch (priority) {
      case 'high':
        return { label: '优先处理', className: 'bg-red-100 text-red-700 border-red-200' };
      case 'medium':
        return { label: '本日完成', className: 'bg-amber-100 text-amber-700 border-amber-200' };
      default:
        return { label: '持续优化', className: 'bg-slate-100 text-slate-700 border-slate-200' };
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
    if (type.includes('price')) return '建议结合销量、库存和成本复核当前价格';
    if (type.includes('review') || type.includes('rating')) return '建议主动联系客户了解问题并改进';
    return 'AI 正在分析最优处理方案，请稍后查看';
  };

  const formatOutcomeTime = (value?: string) => {
    if (!value) return '刚刚';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '刚刚';
    return date.toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const handleResolveAlert = async (alertId: string) => {
    if (!alertId) return;
    setResolvingId(alertId);
    try {
      await fetchAPI(`/alerts/${alertId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'resolved' }),
      });
      setAlerts((prev) => prev.filter((alert) => alert.alert_id !== alertId));
      setOverview((prev) => (
        prev
          ? { ...prev, pending_alerts: Math.max(0, Number(prev.pending_alerts || 0) - 1) }
          : prev
      ));
    } finally {
      setResolvingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">AI 指挥台</h1>
        <p className="text-muted-foreground">让系统把数据翻译成动作，而不是让你自己读图表。</p>
      </div>

      {aiStats && (
        <Card className="border-none bg-gradient-to-r from-slate-950 via-slate-900 to-blue-900 text-white shadow-lg">
          <CardContent className="p-6">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <div className="inline-flex items-center rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs text-blue-100">
                  AI 驱动的日常经营操作系统
                </div>
                <h2 className="mt-3 text-2xl font-bold">今天最值得处理的动作，应该直接在这里开始。</h2>
                <p className="mt-2 max-w-2xl text-sm text-blue-100">
                  当前 AI 已基于商品、订单、库存三条真实数据链产出待办、预警和知识底座。先处理高风险问题，再补齐缺口数据。
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 lg:min-w-[360px]">
                <div className="rounded-xl bg-white/10 p-4">
                  <div className="text-3xl font-bold">{aiStats.totalActions}</div>
                  <div className="text-xs text-blue-100">今日 AI 动作总数</div>
                </div>
                <div className="rounded-xl bg-white/10 p-4">
                  <div className="text-3xl font-bold">{overview?.pending_alerts || 0}</div>
                  <div className="text-xs text-blue-100">待处理预警</div>
                </div>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="rounded-lg bg-white/10 p-3">
                <div className="text-2xl font-bold">{aiStats.alertsHandled}</div>
                <div className="text-sm text-blue-100">🔔 已关闭预警</div>
              </div>
              <div className="rounded-lg bg-white/10 p-3">
                <div className="text-2xl font-bold">{aiStats.csReplies}</div>
                <div className="text-sm text-blue-100">💬 客服会话</div>
              </div>
              <div className="rounded-lg bg-white/10 p-3">
                <div className="text-2xl font-bold">{aiStats.dataImports}</div>
                <div className="text-sm text-blue-100">📥 今日导入批次</div>
              </div>
              <div className="rounded-lg bg-white/10 p-3">
                <div className="text-2xl font-bold">{aiStats.pricingAdj}</div>
                <div className="text-sm text-blue-100">💰 价格调整</div>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap gap-3">
              <a href="/alerts">
                <Button variant="secondary" className="bg-white text-slate-900 hover:bg-slate-100">
                  先处理预警
                </Button>
              </a>
              <a href="/imports">
                <Button variant="outline" className="border-white/30 bg-transparent text-white hover:bg-white/10">
                  导入今天的数据
                </Button>
              </a>
              <a href="/inventory">
                <Button variant="outline" className="border-white/30 bg-transparent text-white hover:bg-white/10">
                  查看补货风险
                </Button>
              </a>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {commandStats.map((stat) => (
          <Card key={stat.title} className="border-slate-200">
            <CardContent className="p-5">
              <div className="text-sm text-slate-500">{stat.title}</div>
              <div className="mt-2 text-3xl font-semibold text-slate-900">{stat.value}</div>
              <div className="mt-2 text-xs text-slate-500">{stat.hint}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.15fr,0.85fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>⚡</span>
              今日最该处理
              <Badge variant="outline">按优先级排序</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {overview?.action_items && overview.action_items.length > 0 ? (
              <div className="space-y-3">
                {overview.action_items.map((item, index) => {
                  const badge = getPriorityBadge(item.priority);
                  return (
                    <a
                      key={`${item.action}-${index}`}
                      href={item.link}
                      className="block rounded-xl border border-slate-200 p-4 transition-colors hover:bg-slate-50"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-1">
                          <div className="text-sm font-medium text-slate-900">{item.action}</div>
                          <div className="text-sm text-muted-foreground">{item.detail}</div>
                        </div>
                        <Badge className={badge.className}>{badge.label}</Badge>
                      </div>
                    </a>
                  );
                })}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">当前没有待处理动作。</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>🔔</span>
              最新高风险预警
              {overview?.pending_alerts ? (
                <Badge variant="secondary">{overview.pending_alerts}</Badge>
              ) : null}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {alerts.length > 0 ? (
              <div className="space-y-3">
                {alerts.map((alert, index) => (
                  <div key={index} className="rounded-xl border border-slate-200 p-4 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <p className="text-sm font-medium">{alert.title || alert.type}</p>
                        <p className="text-sm text-muted-foreground">{alert.description || alert.message}</p>
                      </div>
                      <Badge variant={getSeverityColor(alert.severity)}>
                        {alert.severity === 'critical'
                          ? '严重'
                          : alert.severity === 'high'
                            ? '高优先级'
                            : alert.severity === 'medium'
                              ? '中等'
                              : '一般'}
                      </Badge>
                    </div>
                    <div className="rounded-lg bg-blue-50 p-3">
                      <div className="text-xs font-medium text-blue-700">AI 建议</div>
                      <p className="mt-1 text-xs text-blue-700">{getAlertRecommendation(alert)}</p>
                    </div>
                    <div className="flex justify-end">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={resolvingId === alert.alert_id}
                        onClick={() => handleResolveAlert(alert.alert_id)}
                      >
                        {resolvingId === alert.alert_id ? '处理中...' : '采纳建议'}
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
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>✅</span>
            最近已执行动作
            <Badge variant="outline">闭环回看</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {overview?.recent_outcomes && overview.recent_outcomes.length > 0 ? (
            <div className="space-y-3">
              {overview.recent_outcomes.map((item, index) => (
                <a
                  key={`${item.title}-${index}`}
                  href={item.link}
                  className="block rounded-xl border border-slate-200 p-4 transition-colors hover:bg-slate-50"
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-slate-900">{item.title}</span>
                        <Badge variant="outline">{item.category}</Badge>
                      </div>
                      <div className="text-sm text-muted-foreground">{item.detail}</div>
                      <div className="text-xs text-slate-500">下一步验证：{item.next_check}</div>
                    </div>
                    <div className="text-xs text-slate-500">{formatOutcomeTime(item.happened_at)}</div>
                  </div>
                </a>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              当前还没有最近执行动作记录。完成一次修复、导入或价格调整后，这里会显示最新结果。
            </div>
          )}
        </CardContent>
      </Card>

      {insights && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>🧠</span>
              AI 每日判断
              <Badge variant="outline">每日更新</Badge>
              <span className="ml-auto text-xs font-normal text-muted-foreground">
                AI 于 {insightsTime} 分析完成
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-900">销售异常</h4>
                  <a href="/alerts" className="text-xs font-medium text-blue-600 hover:text-blue-700">
                    去处理
                  </a>
                </div>
                <div className="text-sm text-slate-700">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {insights.sales_anomalies}
                  </ReactMarkdown>
                </div>
              </div>

              <div className="rounded-xl border border-emerald-100 bg-emerald-50 p-4">
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-900">热销变化</h4>
                  <a href="/products" className="text-xs font-medium text-emerald-700 hover:text-emerald-800">
                    看商品
                  </a>
                </div>
                <div className="text-sm text-slate-700">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {insights.hot_products_changes}
                  </ReactMarkdown>
                </div>
              </div>

              <div className="rounded-xl border border-violet-100 bg-violet-50 p-4">
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-900">可执行建议</h4>
                  <a href="/alerts" className="text-xs font-medium text-violet-700 hover:text-violet-800">
                    去执行
                  </a>
                </div>
                <div className="text-sm text-slate-700">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {insights.actionable_suggestions}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default withErrorBoundary(DashboardPage);
