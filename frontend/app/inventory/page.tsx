'use client';

import { useEffect, useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AIInsightCard } from '@/components/ai-insight-card';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getInventoryList, getManualImportReview, lookupIssueActions, updateIssueAction, type InventoryListItem, type IssueActionRecord, type ManualImportReview } from '@/lib/api';

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
    case 'resolved': return '已修复';
    case 'ignored': return '已忽略';
    default: return '待处理';
  }
}

export default function InventoryPage() {
  const [items, setItems] = useState<InventoryListItem[]>([]);
  const [review, setReview] = useState<ManualImportReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'high' | 'stockout' | 'low_stock'>('all');
  const [issueView, setIssueView] = useState<'stockout_but_selling' | 'inventory_missing_cost' | null>('stockout_but_selling');
  const [issueStatuses, setIssueStatuses] = useState<Record<string, IssueActionRecord>>({});
  const [savingIssueKey, setSavingIssueKey] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const [data, reviewData] = await Promise.all([
          getInventoryList(200),
          getManualImportReview(20),
        ]);
        setItems(data);
        setReview(reviewData);
      } catch (err: unknown) {
        setError((err as Error).message || '加载库存失败');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      const matchedSearch =
        !search.trim() ||
        item.name.toLowerCase().includes(search.trim().toLowerCase()) ||
        (item.category || '').toLowerCase().includes(search.trim().toLowerCase());
      if (!matchedSearch) return false;
      if (filter === 'stockout') return item.stock === 0;
      if (filter === 'low_stock') return item.status === 'low_stock';
      if (filter === 'high') return item.risk_level === 'stockout_but_selling' || item.risk_level === 'high';
      return true;
    });
  }, [filter, items, search]);

  const stockoutIssueRows = useMemo(
    () => ((review?.tables?.stockout_but_selling as Array<Record<string, unknown>> | undefined) || []),
    [review]
  );
  const missingCostRows = useMemo(
    () => ((review?.tables?.inventory_missing_cost as Array<Record<string, unknown>> | undefined) || []),
    [review]
  );
  const issueRows = useMemo(
    () => (issueView === 'stockout_but_selling' ? stockoutIssueRows : issueView === 'inventory_missing_cost' ? missingCostRows : []),
    [issueView, stockoutIssueRows, missingCostRows]
  );
  const visibleIssueRows = issueRows.slice(0, 8);

  useEffect(() => {
    if (!issueView || visibleIssueRows.length === 0) return;
    lookupIssueActions(
      visibleIssueRows.map((row) => ({
        issue_type: issueView,
        issue_key: buildIssueKey(issueView, row),
      }))
    )
      .then((rows) => {
        setIssueStatuses((prev) => {
          const next = { ...prev };
          rows.forEach((item) => {
            next[`${item.issue_type}::${item.issue_key}`] = item;
          });
          return next;
        });
      })
      .catch(() => {});
  }, [issueView, visibleIssueRows]);

  const handleIssueStatusChange = async (
    row: Record<string, unknown>,
    status: 'acknowledged' | 'resolved' | 'ignored'
  ) => {
    if (!issueView) return;
    const issueKey = buildIssueKey(issueView, row);
    setSavingIssueKey(issueKey);
    try {
      const result = await updateIssueAction({
        issue_type: issueView,
        issue_key: issueKey,
        title: issueView === 'stockout_but_selling' ? '断货热销商品' : '库存缺成本价',
        status,
        metadata: row,
      });
      setIssueStatuses((prev) => ({
        ...prev,
        [`${result.issue_type}::${result.issue_key}`]: result,
      }));
      if (status === 'resolved' || status === 'ignored') {
        setReview((prev) => {
          if (!prev || !issueView) return prev;
          const nextOpenSummary = {
            ...(prev.open_summary || prev.summary),
            [issueView]: Math.max(0, Number((prev.open_summary || prev.summary)[issueView] || 0) - 1),
          };
          return {
            ...prev,
            open_summary: nextOpenSummary,
            tables: {
              ...prev.tables,
              [issueView]: (((prev.tables[issueView] as Array<Record<string, unknown>> | undefined) || []).filter(
                (item) => buildIssueKey(issueView, item) !== issueKey
              )),
            },
          };
        });
      }
    } finally {
      setSavingIssueKey(issueKey);
    }
  };

  const summary = useMemo(() => {
    const stockout = items.filter((item) => item.stock === 0).length;
    const stockoutButSelling = Number(review?.open_summary?.stockout_but_selling ?? review?.summary.stockout_but_selling ?? items.filter((item) => item.risk_level === 'stockout_but_selling').length);
    const lowStock = items.filter((item) => item.status === 'low_stock').length;
    const missingCost = Number(review?.open_summary?.inventory_missing_cost ?? review?.summary.inventory_missing_cost ?? 0);
    const monthlySales = items.reduce((sum, item) => sum + Number(item.monthly_sales || 0), 0);
    return { total: items.length, stockout, stockoutButSelling, lowStock, missingCost, monthlySales };
  }, [items, review]);

  const inventoryInsight = useMemo(() => {
    if (!items.length) return null;
    const totalValue = items.reduce((sum, i) => sum + (i.stock_value ?? 0), 0);
    const parts: string[] = [];
    if (summary.stockout > 0) parts.push(`${summary.stockout}个SKU断货`);
    if (summary.lowStock > 0) parts.push(`${summary.lowStock}个SKU低于安全库存`);
    if (parts.length === 0)
      return `库存健康，共${items.length}个SKU，总价值约¥${totalValue.toFixed(0)}。`;
    return `库存风险：${parts.join('，')}。总库存价值约¥${totalValue.toFixed(0)}。`;
  }, [items, summary]);

  const renderBadge = (item: InventoryListItem) => {
    if (item.risk_level === 'stockout_but_selling') {
      return <Badge variant="destructive">断货且仍有销量</Badge>;
    }
    if (item.stock === 0) {
      return <Badge variant="destructive">断货</Badge>;
    }
    if (item.status === 'low_stock') {
      return <Badge className="bg-amber-100 text-amber-800">低库存</Badge>;
    }
    return <Badge variant="outline">正常</Badge>;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight">库存管理</h1>
          <p className="text-muted-foreground">优先处理断货热销，再处理低库存高动销商品</p>
        </div>
        <button
          type="button"
          onClick={() => window.open('/api/export/inventory')}
          className="inline-flex items-center rounded-md border border-input bg-background px-4 py-2 min-h-[44px] text-sm font-medium hover:bg-accent"
        >
          导出 Excel
        </button>
      </div>

      <AIInsightCard insight={inventoryInsight} loading={loading && !items.length} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="p-5">
            <div className="text-xs text-muted-foreground">库存商品</div>
            <div className="mt-2 text-2xl font-semibold">{summary.total}</div>
          </CardContent>
        </Card>
        <Card className="border-red-200 bg-red-50">
          <CardContent className="p-5">
            <div className="text-xs text-red-600">断货且仍有销量</div>
            <div className="mt-2 text-2xl font-semibold text-red-800">{summary.stockoutButSelling}</div>
          </CardContent>
        </Card>
        <Card className="border-amber-200 bg-amber-50">
          <CardContent className="p-5">
            <div className="text-xs text-amber-700">低库存商品</div>
            <div className="mt-2 text-2xl font-semibold text-amber-900">{summary.lowStock}</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200 bg-slate-50">
          <CardContent className="p-5">
            <div className="text-xs text-slate-600">缺成本库存</div>
            <div className="mt-2 text-2xl font-semibold text-slate-900">{summary.missingCost}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">库存修复工作池</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              variant={issueView === 'stockout_but_selling' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setIssueView('stockout_but_selling')}
            >
              断货热销
            </Button>
            <Button
              variant={issueView === 'inventory_missing_cost' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setIssueView('inventory_missing_cost')}
            >
              缺成本价
            </Button>
          </div>
          {visibleIssueRows.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    {Object.keys(visibleIssueRows[0]).slice(0, 5).map((key) => (
                      <th key={key} className="px-4 py-3 text-left font-medium text-slate-500">
                        {key}
                      </th>
                    ))}
                    <th className="px-4 py-3 text-left font-medium text-slate-500">状态</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">处理</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {visibleIssueRows.map((row, index) => {
                    const issueKey = issueView ? buildIssueKey(issueView, row) : '';
                    const statusRecord = issueView ? issueStatuses[`${issueView}::${issueKey}`] : undefined;
                    return (
                      <tr key={`${issueView}-${index}`}>
                        {Object.keys(visibleIssueRows[0]).slice(0, 5).map((key) => (
                          <td key={`${issueView}-${index}-${key}`} className="px-4 py-3 text-slate-700">
                            {String(row[key] ?? '—')}
                          </td>
                        ))}
                        <td className="px-4 py-3">
                          <Badge variant={statusRecord?.status === 'resolved' ? 'default' : 'outline'}>
                            {getIssueStatusText(statusRecord?.status)}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-2">
                            <Button variant="outline" size="sm" disabled={savingIssueKey === issueKey} onClick={() => handleIssueStatusChange(row, 'acknowledged')}>
                              已知晓
                            </Button>
                            <Button variant="outline" size="sm" disabled={savingIssueKey === issueKey} onClick={() => handleIssueStatusChange(row, 'resolved')}>
                              已修复
                            </Button>
                            <Button variant="ghost" size="sm" disabled={savingIssueKey === issueKey} onClick={() => handleIssueStatusChange(row, 'ignored')}>
                              忽略
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">当前没有待处理的库存修复项。</div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <CardTitle>库存工作台</CardTitle>
          <div className="flex flex-col gap-3 lg:flex-row">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索商品名或品类"
              className="w-full lg:w-72"
            />
            <div className="flex flex-wrap gap-2">
              <Button variant={filter === 'all' ? 'default' : 'outline'} onClick={() => setFilter('all')}>全部</Button>
              <Button variant={filter === 'high' ? 'default' : 'outline'} onClick={() => setFilter('high')}>高风险</Button>
              <Button variant={filter === 'stockout' ? 'default' : 'outline'} onClick={() => setFilter('stockout')}>断货</Button>
              <Button variant={filter === 'low_stock' ? 'default' : 'outline'} onClick={() => setFilter('low_stock')}>低库存</Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading && <div className="text-sm text-muted-foreground">加载中...</div>}
          {error && <div className="text-sm text-red-600">{error}</div>}
          {!loading && !error && (
            <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>商品名</TableHead>
                  <TableHead>品类</TableHead>
                  <TableHead className="text-right">当前库存</TableHead>
                  <TableHead className="text-right">月销量</TableHead>
                  <TableHead className="text-right">可售天数</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredItems.map((item) => (
                  <TableRow
                    key={`${item.source}-${item.product_id}-${item.name}`}
                    className={
                      item.risk_level === 'stockout_but_selling'
                        ? 'bg-red-50'
                        : item.status === 'low_stock'
                          ? 'bg-amber-50'
                          : ''
                    }
                  >
                    <TableCell className="font-medium">{item.name}</TableCell>
                    <TableCell>{item.category || '未分类'}</TableCell>
                    <TableCell className="text-right">{item.stock}</TableCell>
                    <TableCell className="text-right">{Number(item.monthly_sales || 0).toLocaleString()}</TableCell>
                    <TableCell className="text-right">
                      {item.coverage_days != null ? `${item.coverage_days} 天` : '—'}
                    </TableCell>
                    <TableCell>{renderBadge(item)}</TableCell>
                    <TableCell className="text-right">
                      <a
                        href={item.stock === 0 ? '/alerts' : '/products'}
                        className="text-sm font-medium text-blue-600 hover:text-blue-700"
                      >
                        {item.stock === 0 ? '去处理' : '看商品'}
                      </a>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
