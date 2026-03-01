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
import { getAlerts } from '@/lib/api';
import type { Alert } from '@/lib/api';

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [severityFilter, setSeverityFilter] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAlerts = async () => {
      try {
        const data = await getAlerts();
        setAlerts(data);
      } catch (error) {
        console.error('Error fetching alerts:', error);
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
      case 'price': return '💰';
      case 'sales': return '📈';
      case 'customer': return '👥';
      default: return '⚠️';
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
                  <TableHead>消息</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredAlerts.map((alert, index) => (
                  <TableRow key={index}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{getAlertIcon(alert.type)}</span>
                        <span className="capitalize">{alert.type}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={getSeverityColor(alert.severity)}>
                        {getSeverityText(alert.severity)}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-md">
                      <div className="truncate">{alert.message}</div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex gap-2 justify-end">
                        <Button variant="ghost" size="sm">
                          查看详情
                        </Button>
                        <Button variant="outline" size="sm">
                          标记已读
                        </Button>
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
