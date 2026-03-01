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
import { getAlerts } from '@/lib/api';
import type { Alert } from '@/lib/api';

function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [severityFilter, setSeverityFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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
    };

    fetchAlerts();
  }, []);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'high': return 'destructive';
      case 'medium': return 'secondary';
      case 'low': return 'outline';
      default: return 'outline';
    }
  };

  const getSeverityText = (severity: string) => {
    switch (severity) {
      case 'high': return '严重';
      case 'medium': return '中等';
      case 'low': return '轻微';
      default: return severity;
    }
  };

  const getAlertIcon = (type: string) => {
    switch (type.toLowerCase()) {
      case 'inventory': return '📦';
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

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">预警中心</h1>
            <p className="text-muted-foreground">监控系统异常和重要提醒</p>
          </div>
          <Button disabled>设置预警规则</Button>
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
            <h1 className="text-3xl font-bold tracking-tight">预警中心</h1>
            <p className="text-muted-foreground">监控系统异常和重要提醒</p>
          </div>
          <Button disabled>设置预警规则</Button>
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
          <h1 className="text-3xl font-bold tracking-tight">预警中心</h1>
          <p className="text-muted-foreground">监控系统异常和重要提醒</p>
        </div>
        <Button>设置预警规则</Button>
      </div>

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
                  {alerts.filter(a => a.severity === 'high').length}
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
                <p className="text-sm font-medium text-muted-foreground">轻微预警</p>
                <p className="text-2xl font-bold text-yellow-600">
                  {alerts.filter(a => a.severity === 'low').length}
                </p>
              </div>
              <div className="text-3xl">💡</div>
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
                  <TableHead>描述</TableHead>
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
                      <div className="text-sm text-muted-foreground truncate">{alert.description}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={alert.status === 'resolved' ? 'default' : 'secondary'}>
                        {alert.status === 'pending' ? '待处理' : alert.status === 'resolved' ? '已解决' : alert.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex gap-2 justify-end">
                        <Button variant="ghost" size="sm">
                          查看详情
                        </Button>
                        {alert.status === 'pending' && (
                          <Button variant="outline" size="sm">
                            标记已解决
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              {severityFilter ? '没有找到符合条件的预警' : '暂无预警信息'}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Alert Categories Overview */}
      {Object.keys(alertsByType).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>📊</span>
              预警类型分布
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {Object.entries(alertsByType).map(([type, count]) => (
                <div key={type} className="text-center p-4 bg-muted/50 rounded-lg">
                  <div className="text-2xl mb-2">{getAlertIcon(type)}</div>
                  <div className="font-semibold">{count}</div>
                  <div className="text-sm text-muted-foreground capitalize">{type}</div>
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
