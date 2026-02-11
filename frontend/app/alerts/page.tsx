'use client';
import { useEffect, useState, useCallback } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { Table, Column } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { getAlerts, updateAlertStatus } from '@/lib/api';
import type { Alert } from '@/lib/types';

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [severity, setSeverity] = useState('');
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await getAlerts({ severity: severity || undefined, status: status || undefined });
      setAlerts(res.data || []);
    } catch {}
  }, [severity, status]);

  useEffect(() => { load(); }, [load]);

  const handleStatus = async (alertId: string, newStatus: string) => {
    try {
      await updateAlertStatus(alertId, newStatus);
      load();
    } catch {}
  };

  const columns: Column<Alert>[] = [
    { key: 'product_name', label: '商品', render: (r) => <span className="text-white">{r.product_name || r.product_id}</span> },
    { key: 'alert_type', label: '类型' },
    { key: 'severity', label: '严重度', render: (r) => <Badge value={r.severity} /> },
    { key: 'status', label: '状态', render: (r) => <Badge value={r.status} /> },
    { key: 'message', label: '内容', className: 'max-w-xs truncate' },
    { key: 'created_at', label: '时间', render: (r) => new Date(r.created_at).toLocaleString('zh-CN') },
    {
      key: 'actions', label: '操作', render: (r) => r.status === 'pending' ? (
        <div className="flex gap-1">
          <button onClick={(e) => { e.stopPropagation(); handleStatus(r.alert_id, 'acknowledged'); }} className="text-xs text-blue-400 hover:text-blue-300">确认</button>
          <button onClick={(e) => { e.stopPropagation(); handleStatus(r.alert_id, 'resolved'); }} className="text-xs text-green-400 hover:text-green-300 ml-2">解决</button>
          <button onClick={(e) => { e.stopPropagation(); handleStatus(r.alert_id, 'ignored'); }} className="text-xs text-gray-400 hover:text-gray-300 ml-2">忽略</button>
        </div>
      ) : r.status === 'acknowledged' ? (
        <button onClick={(e) => { e.stopPropagation(); handleStatus(r.alert_id, 'resolved'); }} className="text-xs text-green-400 hover:text-green-300">解决</button>
      ) : null,
    },
  ];

  return (
    <div>
      <Header title="预警中心" />
      <div className="p-6 space-y-4">
        <div className="flex flex-wrap gap-3">
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="bg-white/5 border border-white/[0.08] rounded-lg px-4 py-2 text-sm text-gray-300 outline-none">
            <option value="">全部严重度</option>
            <option value="critical">严重</option>
            <option value="warning">警告</option>
            <option value="info">信息</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="bg-white/5 border border-white/[0.08] rounded-lg px-4 py-2 text-sm text-gray-300 outline-none">
            <option value="">全部状态</option>
            <option value="pending">待处理</option>
            <option value="acknowledged">已确认</option>
            <option value="resolved">已解决</option>
            <option value="ignored">已忽略</option>
          </select>
          <span className="text-sm text-gray-500 ml-auto self-center">共 {alerts.length} 条预警</span>
        </div>

        <Card>
          <Table columns={columns} data={alerts} />
        </Card>
      </div>
    </div>
  );
}
