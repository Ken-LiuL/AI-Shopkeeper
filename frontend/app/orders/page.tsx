'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { getManualImportReview, getOrders, getOrderStats, lookupIssueActions, updateIssueAction, type IssueActionRecord, type ManualImportReview, type Order, type OrderStats } from '@/lib/api';


const statusOptions = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待处理' },
  { value: 'processing', label: '配送中' },
  { value: 'completed', label: '已完成' },
  { value: 'refunded', label: '已退单' },
  { value: 'cancelled', label: '已取消' },
];

const statusLabels: Record<string, string> = {
  pending: '待处理',
  processing: '配送中',
  completed: '已完成',
  refunded: '已退单',
  cancelled: '已取消',
};

const statusColors: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  processing: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  refunded: 'bg-red-100 text-red-800',
  cancelled: 'bg-slate-200 text-slate-800',
};

function buildIssueKey(prefix: string, row: Record<string, unknown>) {
  const normalized = Object.keys(row)
    .sort()
    .reduce<Record<string, unknown>>((acc, key) => {
      acc[key] = row[key];
      return acc;
    }, {});
  return `${prefix}:${JSON.stringify(normalized)}`;
}

function getIssueStatusText(status?: string) {
  switch (status) {
    case 'acknowledged': return '已知晓';
    case 'resolved': return '已复核';
    case 'ignored': return '已忽略';
    default: return '待处理';
  }
}

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [stats, setStats] = useState<OrderStats | null>(null);
  const [review, setReview] = useState<ManualImportReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedStatus, setSelectedStatus] = useState('all');
  const [selectedDate, setSelectedDate] = useState('');
  const [showMismatchList, setShowMismatchList] = useState(false);
  const [mismatchStatuses, setMismatchStatuses] = useState<Record<string, IssueActionRecord>>({});
  const [savingIssueKey, setSavingIssueKey] = useState<string | null>(null);
  const [activeReviewKey, setActiveReviewKey] = useState<string | null>(null);
  const [reviewDraft, setReviewDraft] = useState<{
    row: Record<string, unknown>;
    issueKey: string;
    note: string;
    decision: 'acknowledged' | 'resolved' | 'ignored';
  } | null>(null);
  const [reviewMessage, setReviewMessage] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  const limit = 20;
  const totalPages = Math.ceil(total / limit);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [ordersResponse, statsData, reviewData] = await Promise.all([
        getOrders(currentPage, limit, selectedStatus, selectedDate || undefined),
        getOrderStats(),
        getManualImportReview(12),
      ]);

      setOrders(ordersResponse.orders);
      setTotal(ordersResponse.total);
      setStats(statsData);
      setReview(reviewData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [currentPage, selectedStatus, selectedDate]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const formatTime = (timeStr: string) => {
    return new Date(timeStr).toLocaleString('zh-CN');
  };

  const formatCurrency = (amount: number) => {
    return `¥${Number(amount).toFixed(2)}`;
  };

  const mismatchCount = Number(review?.open_summary?.order_amount_mismatch ?? review?.summary.order_amount_mismatch ?? 0);
  const refundRate = Number(stats?.refund_rate || 0);
  const completionRate = Number(stats?.completion_rate || 0);
  const mismatchRows = useMemo(
    () => ((review?.tables?.order_amount_mismatch as Array<Record<string, unknown>> | undefined) || []),
    [review]
  );
  const visibleMismatchRows = mismatchRows.slice(0, 8);

  const removeMismatchFromReview = useCallback((issueKey: string) => {
    setReview((prev) => {
      if (!prev) return prev;
      const nextOpenSummary = {
        ...(prev.open_summary || prev.summary),
        order_amount_mismatch: Math.max(0, Number((prev.open_summary || prev.summary).order_amount_mismatch || 0) - 1),
      };
      return {
        ...prev,
        open_summary: nextOpenSummary,
        tables: {
          ...prev.tables,
          order_amount_mismatch: ((prev.tables.order_amount_mismatch as Array<Record<string, unknown>> | undefined) || []).filter(
            (item) => buildIssueKey('order_amount_mismatch', item) !== issueKey
          ),
        },
      };
    });
  }, []);

  useEffect(() => {
    const targetRows = mismatchRows.slice(0, 8);
    if (targetRows.length === 0) return;
    lookupIssueActions(
      targetRows.map((row) => ({
        issue_type: 'order_amount_mismatch',
        issue_key: buildIssueKey('order_amount_mismatch', row),
      }))
    )
      .then((rows) => {
        setMismatchStatuses((prev) => {
          const next = { ...prev };
          rows.forEach((item) => {
            next[`${item.issue_type}::${item.issue_key}`] = item;
          });
          return next;
        });
      })
      .catch(() => {});
  }, [mismatchRows]);

  const handleMismatchStatusChange = async (
    row: Record<string, unknown>,
    status: 'acknowledged' | 'resolved' | 'ignored',
    notes?: string,
  ) => {
    const issueKey = buildIssueKey('order_amount_mismatch', row);
    setSavingIssueKey(issueKey);
    setReviewMessage(null);
    try {
      const result = await updateIssueAction({
        issue_type: 'order_amount_mismatch',
        issue_key: issueKey,
        title: '金额异常订单',
        status,
        notes,
        metadata: row,
      });
      setMismatchStatuses((prev) => ({
        ...prev,
        [`${result.issue_type}::${result.issue_key}`]: result,
      }));
      if (status === 'resolved' || status === 'ignored') {
        removeMismatchFromReview(issueKey);
      }
    } finally {
      setSavingIssueKey(issueKey);
    }
  };

  const openMismatchReview = (row: Record<string, unknown>) => {
    const issueKey = buildIssueKey('order_amount_mismatch', row);
    const statusRecord = mismatchStatuses[`order_amount_mismatch::${issueKey}`];
    setActiveReviewKey(issueKey);
    setReviewMessage(null);
    setReviewDraft({
      row,
      issueKey,
      note: statusRecord?.notes || '',
      decision: statusRecord?.status || 'acknowledged',
    });
  };

  const handleSaveReviewDraft = async () => {
    if (!reviewDraft) return;
    await handleMismatchStatusChange(
      reviewDraft.row,
      reviewDraft.decision,
      reviewDraft.note.trim() || undefined,
    );
    setReviewMessage(
      reviewDraft.decision === 'resolved'
        ? '已复核并移出异常订单池'
        : reviewDraft.decision === 'ignored'
          ? '已忽略并移出异常订单池'
          : '复核备注已保存'
    );
    if (reviewDraft.decision !== 'acknowledged') {
      setReviewDraft(null);
      setActiveReviewKey(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">加载中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <p className="text-red-600 text-lg">❌ 加载失败</p>
          <p className="text-gray-600 mt-2">{error}</p>
          <button
            onClick={loadData}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">📋 异常订单工作池</h1>
          <p className="mt-1 text-sm text-gray-500">优先看金额异常、退款和处理中订单，不再把订单页当作纯流水列表。</p>
        </div>
        <div className="text-sm text-gray-500">共 {total} 条订单</div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <button
          type="button"
          onClick={() => setShowMismatchList(true)}
          className="block rounded-xl border border-amber-200 bg-amber-50 p-4 text-left transition-colors hover:bg-amber-100"
        >
          <div className="text-xs text-amber-700">金额异常订单</div>
          <div className="mt-1 text-3xl font-semibold text-amber-900">{mismatchCount}</div>
          <div className="mt-2 text-xs text-amber-700">这部分不应直接参与利润判断</div>
        </button>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">今日订单</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{Number(stats?.today_orders || 0)}</div>
            <div className="mt-2 text-xs text-slate-500">真实导入订单口径</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">完成率</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{completionRate.toFixed(1)}%</div>
            <div className="mt-2 text-xs text-slate-500">低完成率需要排查履约或取消原因</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">退款/取消率</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{refundRate.toFixed(1)}%</div>
            <div className="mt-2 text-xs text-slate-500">高于预期时优先看退款与取消订单</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">处理建议</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <button
            onClick={() => {
              setSelectedStatus('refunded');
              setCurrentPage(1);
            }}
            className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
          >
            只看退款订单
          </button>
          <button
            onClick={() => {
              setSelectedStatus('cancelled');
              setCurrentPage(1);
            }}
            className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            只看取消订单
          </button>
          <a href="/imports" className="inline-flex items-center rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-700 hover:bg-amber-100">
            重新核对导入批次
          </a>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">金额异常订单清单</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {reviewDraft && (
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">订单复核面板</div>
                  <div className="text-xs text-slate-600">
                    订单 {String(reviewDraft.row.order_id ?? '—')}，差额 ¥{Number(reviewDraft.row.diff || 0).toFixed(2)}
                  </div>
                </div>
                <Badge variant="outline">页内闭环复核</Badge>
              </div>

              {reviewMessage ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                  {reviewMessage}
                </div>
              ) : null}

              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
                  <div className="text-xs text-slate-500">支付金额</div>
                  <div className="mt-1 font-medium">¥{Number(reviewDraft.row.customer_paid || 0).toFixed(2)}</div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
                  <div className="text-xs text-slate-500">明细金额</div>
                  <div className="mt-1 font-medium">¥{Number(reviewDraft.row.line_total || 0).toFixed(2)}</div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
                  <div className="text-xs text-slate-500">差额</div>
                  <div className="mt-1 font-medium text-amber-700">¥{Number(reviewDraft.row.diff || 0).toFixed(2)}</div>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-[180px,1fr]">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700">处理结论</label>
                  <select
                    value={reviewDraft.decision}
                    onChange={(event) => setReviewDraft((prev) => prev ? { ...prev, decision: event.target.value as 'acknowledged' | 'resolved' | 'ignored' } : prev)}
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-slate-400"
                  >
                    <option value="acknowledged">已知晓，继续跟进</option>
                    <option value="resolved">已复核，移出工作池</option>
                    <option value="ignored">忽略，不参与后续分析</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700">复核备注</label>
                  <textarea
                    value={reviewDraft.note}
                    onChange={(event) => setReviewDraft((prev) => prev ? { ...prev, note: event.target.value } : prev)}
                    rows={3}
                    placeholder="例如：已确认平台补贴、配送费、拆单或优惠分摊导致差额，不再参与利润精算。"
                    className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-slate-400"
                  />
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={handleSaveReviewDraft}
                  disabled={savingIssueKey === reviewDraft.issueKey}
                  className="inline-flex items-center rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
                >
                  {savingIssueKey === reviewDraft.issueKey ? '保存中...' : '保存复核'}
                </button>
                <button
                  onClick={() => {
                    setReviewDraft(null);
                    setActiveReviewKey(null);
                    setReviewMessage(null);
                  }}
                  className="inline-flex items-center rounded-md border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  关闭
                </button>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setShowMismatchList(true)}
              className={`inline-flex items-center rounded-md px-4 py-2 text-sm font-medium ${
                showMismatchList
                  ? 'bg-amber-600 text-white'
                  : 'border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
              }`}
            >
              展开异常清单
            </button>
            <button
              onClick={() => setShowMismatchList(false)}
              className="inline-flex items-center rounded-md border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              收起
            </button>
          </div>
          {showMismatchList && mismatchRows.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    {Object.keys(mismatchRows[0]).slice(0, 5).map((key) => (
                      <th key={key} className="px-4 py-3 text-left font-medium text-slate-500">
                        {key}
                      </th>
                    ))}
                    <th className="px-4 py-3 text-left font-medium text-slate-500">状态</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">处理</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {visibleMismatchRows.map((row, index) => {
                    const issueKey = buildIssueKey('order_amount_mismatch', row);
                    const statusRecord = mismatchStatuses[`order_amount_mismatch::${issueKey}`];
                    return (
                    <tr key={`mismatch-${index}`}>
                      {Object.keys(mismatchRows[0]).slice(0, 5).map((key) => (
                        <td key={`mismatch-${index}-${key}`} className="px-4 py-3 text-slate-700">
                          {String(row[key] ?? '—')}
                        </td>
                      ))}
                      <td className="px-4 py-3">
                        <Badge variant={statusRecord?.status === 'resolved' ? 'default' : 'outline'}>
                          {getIssueStatusText(statusRecord?.status)}
                        </Badge>
                        {statusRecord?.notes ? (
                          <div className="mt-2 max-w-xs text-xs text-slate-500">{statusRecord.notes}</div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => openMismatchReview(row)}
                            className={`inline-flex items-center rounded-md px-3 py-1 text-xs font-medium ${
                              activeReviewKey === issueKey
                                ? 'bg-slate-900 text-white'
                                : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                            }`}
                          >
                            复核备注
                          </button>
                          <button
                            onClick={() => handleMismatchStatusChange(row, 'acknowledged', statusRecord?.notes)}
                            disabled={savingIssueKey === issueKey}
                            className="inline-flex items-center rounded-md border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                          >
                            已知晓
                          </button>
                          <button
                            onClick={() => handleMismatchStatusChange(row, 'resolved', statusRecord?.notes)}
                            disabled={savingIssueKey === issueKey}
                            className="inline-flex items-center rounded-md border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-60"
                          >
                            已复核
                          </button>
                          <button
                            onClick={() => handleMismatchStatusChange(row, 'ignored', statusRecord?.notes)}
                            disabled={savingIssueKey === issueKey}
                            className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-60"
                          >
                            忽略
                          </button>
                        </div>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : showMismatchList ? (
            <div className="text-sm text-muted-foreground">当前没有金额异常订单明细。</div>
          ) : (
            <div className="text-sm text-muted-foreground">展开后可直接查看导入 review 识别出的异常订单样本。</div>
          )}
        </CardContent>
      </Card>

      {/* 订单统计卡片 */}
      {stats && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
          <div className="bg-white p-6 rounded-lg shadow-sm border">
            <div className="flex items-center">
              <div className="p-3 rounded-full bg-blue-100">
                <span className="text-2xl">📊</span>
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-500">今日订单数</p>
                <p className="text-2xl font-bold text-gray-900">{Number(stats.today_orders)}</p>
              </div>
            </div>
          </div>

          <div className="bg-white p-6 rounded-lg shadow-sm border">
            <div className="flex items-center">
              <div className="p-3 rounded-full bg-green-100">
                <span className="text-2xl">✅</span>
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-500">完成率</p>
                <p className="text-2xl font-bold text-gray-900">{Number(stats.completion_rate).toFixed(1)}%</p>
              </div>
            </div>
          </div>

          <div className="bg-white p-6 rounded-lg shadow-sm border">
            <div className="flex items-center">
              <div className="p-3 rounded-full bg-red-100">
                <span className="text-2xl">↩️</span>
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-500">退单率</p>
                <p className="text-2xl font-bold text-gray-900">{Number(stats.refund_rate).toFixed(1)}%</p>
              </div>
            </div>
          </div>

          <div className="bg-white p-6 rounded-lg shadow-sm border">
            <div className="flex items-center">
              <div className="p-3 rounded-full bg-yellow-100">
                <span className="text-2xl">🚚</span>
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-500">平均配送时间</p>
                <p className="text-2xl font-bold text-gray-900">{Number(stats.avg_delivery_time)}分钟</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 筛选控件 */}
        <div className="bg-white p-4 rounded-lg shadow-sm border">
        <div className="flex flex-wrap gap-4 items-center">
          <div className="flex gap-2">
            <label className="text-sm font-medium text-gray-700">状态:</label>
            <select
              value={selectedStatus}
              onChange={(e) => {
                setSelectedStatus(e.target.value);
                setCurrentPage(1);
              }}
              className="px-3 py-1 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {statusOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex gap-2">
            <label className="text-sm font-medium text-gray-700">日期:</label>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => {
                setSelectedDate(e.target.value);
                setCurrentPage(1);
              }}
              className="px-3 py-1 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          {selectedStatus !== 'all' && (
            <Badge variant="outline">当前筛选：{statusOptions.find((item) => item.value === selectedStatus)?.label || selectedStatus}</Badge>
          )}
        </div>
      </div>

      {/* 订单列表 */}
      <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  订单号
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  商品
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  金额
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  状态
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  时间
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {orders.map((order) => (
                <tr key={order.order_id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                    {order.order_id}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {order.product_name}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {formatCurrency(order.amount)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${statusColors[order.status]}`}>
                      {statusLabels[order.status]}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {formatTime(order.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between">
            <div className="text-sm text-gray-700">
              第 {currentPage} 页，共 {totalPages} 页，共 {total} 条记录
            </div>
            <div className="flex space-x-2">
              <button
                onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                disabled={currentPage === 1}
                className="px-3 py-1 border border-gray-300 rounded-md text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                上一页
              </button>
              <button
                onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                disabled={currentPage === totalPages}
                className="px-3 py-1 border border-gray-300 rounded-md text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
