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
import { withErrorBoundary } from '@/components/error-boundary';
import { fetchAPI, getAlerts } from '@/lib/api';
import type { Alert } from '@/lib/api';

function getAlertActionLink(alert: Alert) {
  const type = (alert.type || '').toLowerCase();
  if (type === 'stockout' || type === 'inventory') return '/inventory';
  if (type === 'catalog' || type === 'pricing') return '/products';
  if (type === 'orders') return '/orders';
  if (type === 'data_quality') return '/imports';
  return '/alerts';
}

function getAlertRecommendation(alert: Alert): string {
  if (alert.recommended_action) return alert.recommended_action;
  if (alert.action_suggestions && alert.action_suggestions.length > 0) {
    return alert.action_suggestions[0];
  }

  const type = (alert.type || '').toLowerCase();
  if (type.includes('stock') || type.includes('inventory')) return '建议立即补货，避免断货影响销售';
  if (type.includes('price')) return '建议结合销量、库存和成本复核当前价格';
  if (type.includes('review') || type.includes('rating')) return '建议主动联系客户了解问题并改进';
  return 'AI 正在分析最优处理方案，请稍后查看';
}

function getImpactText(alert: Alert): string {
  if (alert.expected_impact_amount != null && alert.impact_type) {
    const prefix = alert.impact_type === 'loss_avoid' ? '预计止损' : alert.impact_type === 'cost_save' ? '预计节省' : '预计增收';
    return `${prefix} ¥${Number(alert.expected_impact_amount).toFixed(0)}`;
  }
  return alert.impact_reason || '预计影响待补充';
}

function getConfidenceBadge(confidence?: number | null): { text: string; className: string } {
  const value = Number(confidence || 0);
  if (value >= 0.8) return { text: '高', className: 'bg-green-100 text-green-700' };
  if (value >= 0.6) return { text: '中', className: 'bg-amber-100 text-amber-700' };
  return { text: '低', className: 'bg-slate-100 text-slate-600' };
}

function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [severityFilter, setSeverityFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolvingIds, setResolvingIds] = useState<Set<string>>(new Set());
  const [resolvedIds, setResolvedIds] = useState<Set<string>>(new Set());
  const [dataStatus, setDataStatus] = useState<{has_sufficient_data: boolean; days_of_data: number; message: string} | null>(null);

  const fetchAlerts = async () => {
    try {
      setError(null);
      const data = await getAlerts();
      setAlerts(data);
    } catch (error) {
      console.error('Error fetching alerts:', error);
      setError('加载预警数据失败，请稍后重试');
    } finally {
      setLoading(false);
    }
    try {
      const statusData = await fetchAPI<{data: {has_sufficient_data: boolean; days_of_data: number; message: string}}>('/alerts/status');
      setDataStatus(statusData.data);
    } catch (_) { /* 不阻断主流程 */ }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  const handleResolve = async (alertId: string) => {
    setResolvingIds(prev => new Set(prev).add(alertId));
    try {
      await fetchAPI(`/alerts/${alertId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'resolved' }),
      });
      setResolvedIds(prev => new Set(prev).add(alertId));
      setAlerts(prev => prev.filter(a => (a.alert_id || '') !== alertId));
    } catch (err) {
      console.error('Error resolving alert:', err);
    } finally {
      setResolvingIds(prev => {
        const next = new Set(prev);
        next.delete(alertId);
        return next;
      });
    }
  };

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

  const getSeverityText = (severity: string) => {
    switch (severity) {
      case 'critical':
      case 'high': return '严重';
      case 'warning':
      case 'medium': return '中等';
      case 'info':
      case 'low': return '轻微';
      default: return severity;
    }
  };

  const getAlertIcon = (type: string) => {
    switch (type.toLowerCase()) {
      case 'inventory': return '📦';
      case 'catalog': return '🧾';
      case 'orders': return '🧮';
      case 'data_quality': return '🧹';
      case 'pricing': return '💰';
      case 'stockout': return '📦';
      case 'performance': return '📈';
      case 'system': return '⚙️';
      case 'customer': return '👥';
      default: return '⚠️';
    }
  };

  const getTypeText = (type: string) => {
    switch (type.toLowerCase()) {
      case 'inventory': return '库存';
      case 'catalog': return '主档';
      case 'orders': return '订单';
      case 'data_quality': return '数据质量';
      case 'pricing': return '价格';
      case 'stockout': return '缺货';
      case 'performance': return '性能';
      case 'system': return '系统';
      case 'customer': return '客户';
      default: return type;
    }
  };

  const filteredAlerts = severityFilter
    ? alerts.filter(alert => alert.severity === severityFilter)
    : alerts;

  const alertsByType = filteredAlerts.reduce((acc, alert) => {
    const type = alert.type || 'other';
    acc[type] = (acc[type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
  const priorityAlerts = filteredAlerts
    .filter((alert) => ['high', 'critical', 'medium'].includes(alert.severity || ''))
    .slice(0, 3);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">🔔 智能预警</h1>
            <p className="text-muted-foreground">先清掉今天最影响经营的风险，再处理次级问题。</p>
          </div>
          <a href="/imports" className="inline-flex items-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent">
            查看导入质量
          </a>
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
            <h1 className="text-3xl font-bold tracking-tight">🔔 智能预警</h1>
            <p className="text-muted-foreground">先清掉今天最影响经营的风险，再处理次级问题。</p>
          </div>
          <a href="/imports" className="inline-flex items-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent">
            查看导入质量
          </a>
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
          <h1 className="text-3xl font-bold tracking-tight">🔔 预警处理中心</h1>
          <p className="mt-1 text-sm text-muted-foreground">预警的价值不在“发现异常”，而在“让你今天知道先处理哪三件事”。</p>
        </div>
        <div className="flex gap-2">
          <a href="/imports" className="inline-flex items-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent">
            导入并复核数据
          </a>
          <Button variant="outline" onClick={fetchAlerts}>
            刷新预警
          </Button>
        </div>
      </div>

      {priorityAlerts.length > 0 && (
        <Card className="border-red-200 bg-red-50/70">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">今日优先动作</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {priorityAlerts.map((alert) => (
              <div key={alert.alert_id} className="flex flex-col gap-3 rounded-xl border border-red-200 bg-white p-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant={getSeverityColor(alert.severity)}>{getSeverityText(alert.severity)}</Badge>
                    <Badge variant="outline">{getTypeText(alert.type)}</Badge>
                  </div>
                  <div className="text-sm font-medium text-slate-900">{alert.title}</div>
                  <div className="text-sm text-slate-600">{alert.description}</div>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded bg-emerald-50 px-2 py-1 font-medium text-emerald-700">{getImpactText(alert)}</span>
                    <span className={`inline-flex rounded-full px-2 py-1 font-semibold ${getConfidenceBadge(alert.confidence).className}`}>
                      置信度 {getConfidenceBadge(alert.confidence).text}
                    </span>
                  </div>
                  <div className="text-xs text-red-700">
                    {getAlertRecommendation(alert)}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 lg:justify-end">
                  <a
                    href={getAlertActionLink(alert)}
                    className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
                  >
                    去处理
                  </a>
                  {alert.status === 'pending' ? (
                    <Button
                      variant="outline"
                      disabled={resolvingIds.has(alert.alert_id || '')}
                      onClick={() => handleResolve(alert.alert_id || '')}
                    >
                      {resolvingIds.has(alert.alert_id || '') ? '处理中...' : '标记已处理'}
                    </Button>
                  ) : null}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Alert Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">总预警</p>
                <p className="text-2xl font-bold">{alerts.length}</p>
              </div>
              <div className="text-3xl">🔔</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">严重预警</p>
                <p className="text-2xl font-bold text-red-600">
                  {alerts.filter(a => ['high', 'critical'].includes(a.severity)).length}
                </p>
              </div>
              <div className="text-3xl">🚨</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">中等预警</p>
                <p className="text-2xl font-bold text-orange-600">
                  {alerts.filter(a => a.severity === 'medium').length}
                </p>
              </div>
              <div className="text-3xl">⚠️</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">本次已处理</p>
                <p className="text-2xl font-bold text-green-600">
                  {resolvedIds.size}
                </p>
              </div>
              <div className="text-3xl">✅</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="border border-input bg-background px-3 py-2 text-sm rounded-md"
        >
          <option value="">全部严重度</option>
          <option value="high">严重</option>
          <option value="medium">中等</option>
          <option value="low">轻微</option>
        </select>
        <span className="text-sm text-muted-foreground">
          显示 {filteredAlerts.length} / {alerts.length} 条预警
        </span>
      </div>

      {/* Alerts Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>📋</span>
            预警列表
          </CardTitle>
        </CardHeader>
        <CardContent>
          {filteredAlerts.length > 0 ? (
            <Table>
              <TableCaption>系统预警信息</TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead>类型</TableHead>
                  <TableHead>严重度</TableHead>
                  <TableHead>标题</TableHead>
                  <TableHead>建议动作</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredAlerts.map((alert, index) => (
                  <TableRow key={alert.alert_id || index}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{getAlertIcon(alert.type)}</span>
                        <span className="capitalize">{getTypeText(alert.type)}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={getSeverityColor(alert.severity)}>
                        {getSeverityText(alert.severity)}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-xs">
                      <div className="font-medium">{alert.title}</div>
                    </TableCell>
                    <TableCell className="max-w-md">
                      <div className="text-sm text-slate-700">{getAlertRecommendation(alert)}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                        <span className="rounded bg-emerald-50 px-2 py-1 font-medium text-emerald-700">{getImpactText(alert)}</span>
                        <span className={`inline-flex rounded-full px-2 py-1 font-semibold ${getConfidenceBadge(alert.confidence).className}`}>
                          {getConfidenceBadge(alert.confidence).text}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">{alert.description}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={alert.status === 'resolved' ? 'default' : 'secondary'}>
                        {alert.status === 'pending' ? '待处理' : alert.status === 'resolved' ? '已解决' : alert.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex flex-col gap-2 items-end">
                        <a
                          href={getAlertActionLink(alert)}
                          className="text-sm font-medium text-blue-600 hover:text-blue-700"
                        >
                          去处理
                        </a>
                        {alert.status === 'pending' && (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={resolvingIds.has(alert.alert_id || '')}
                            onClick={() => handleResolve(alert.alert_id || '')}
                          >
                            {resolvingIds.has(alert.alert_id || '') ? '处理中...' : '标记已处理'}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-12">
              {severityFilter ? (
                <div className="text-muted-foreground">没有找到符合条件的预警</div>
              ) : dataStatus && !dataStatus.has_sufficient_data ? (
                <>
                  <div className="text-4xl mb-3">📊</div>
                  <div className="text-lg font-medium text-gray-700">数据积累中</div>
                  <div className="text-sm text-gray-500 mt-2">
                    {dataStatus.message || '需要更多历史数据才能分析异常'}<br />
                    请先完成数据导入，正常运营后预警将自动生成。
                  </div>
                  <div className="mt-4 flex justify-center gap-3">
                    <a
                      href="/settings/sync"
                      className="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                    >
                      去导入数据
                    </a>
                    <button
                      onClick={fetchAlerts}
                      className="inline-flex items-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                      刷新检查
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div className="text-4xl mb-3">✅</div>
                  <div className="text-lg font-medium text-gray-700">运营正常，暂无预警</div>
                  <div className="text-sm text-gray-500 mt-2">系统持续监控中，发现异常会第一时间通知你。</div>
                </>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {Object.keys(alertsByType).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>🏷️</span>
              预警分布
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {Object.entries(alertsByType).map(([type, count]) => (
                <div key={type} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
                    <span className="text-lg">{getAlertIcon(type)}</span>
                    {getTypeText(type)}
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-slate-900">{count}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default withErrorBoundary(AlertsPage);
