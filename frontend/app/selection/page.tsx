'use client';

import { useEffect, useState } from 'react';
import { withErrorBoundary } from '@/components/error-boundary';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { fetchAPI, lookupIssueActions, updateIssueAction, type IssueActionRecord } from '@/lib/api';

interface SelectionProduct {
  product_id: string;
  name: string;
  category: string;
  brand?: string;
  price: number;
  profit_margin: number;
  demand_score: number;
  recommendation_score: number;
  monthly_sales: number;
  stock: number;
  stock_days?: number | null;
  knowledge_count: number;
  knowledge_ready: boolean;
  status: 'recommended' | 'considering' | 'selected' | 'rejected';
  reason: string;
  risk_warning?: string;
  score_breakdown?: Record<string, number>;
  data_source?: string[];
}

function getUiStatus(product: SelectionProduct, action?: IssueActionRecord | null) {
  if (!action) {
    return product.status;
  }
  if (action.status === 'resolved') {
    return 'selected';
  }
  if (action.status === 'ignored') {
    return 'rejected';
  }
  return 'considering';
}

function statusBadge(status: string) {
  switch (status) {
    case 'recommended':
      return 'bg-green-100 text-green-700';
    case 'considering':
      return 'bg-amber-100 text-amber-700';
    case 'selected':
      return 'bg-blue-100 text-blue-700';
    case 'rejected':
      return 'bg-slate-100 text-slate-600';
    default:
      return 'bg-slate-100 text-slate-600';
  }
}

function statusText(status: string) {
  switch (status) {
    case 'recommended':
      return '优先运营';
    case 'considering':
      return '继续观察';
    case 'selected':
      return '已纳入重点';
    case 'rejected':
      return '暂不考虑';
    default:
      return status;
  }
}

function scoreColor(score: number) {
  if (score >= 8) {
    return 'text-green-600';
  }
  if (score >= 6) {
    return 'text-amber-600';
  }
  return 'text-slate-500';
}

function SelectionPage() {
  const [products, setProducts] = useState<SelectionProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProducts, setSelectedProducts] = useState<Set<string>>(new Set());
  const [filterCategory, setFilterCategory] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [processingKey, setProcessingKey] = useState<string | null>(null);

  useEffect(() => {
    void loadData();
  }, []);

  async function loadData() {
    try {
      setLoading(true);
      setError(null);
      const raw = await fetchAPI<SelectionProduct[]>('/selection/recommendations');
      const issues = raw.length > 0
        ? await lookupIssueActions(
            raw.map((item) => ({
              issue_type: 'selection_candidate',
              issue_key: item.product_id,
            })),
          )
        : [];
      const issueMap = new Map(issues.map((item) => [item.issue_key, item]));
      setProducts(
        raw.map((item) => ({
          ...item,
          status: getUiStatus(item, issueMap.get(item.product_id)),
        })),
      );
      setMessage(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载重点候选商品失败');
    } finally {
      setLoading(false);
    }
  }

  async function applySelectionAction(
    productIds: string[],
    action: 'select' | 'reject',
  ) {
    if (productIds.length === 0) {
      setMessage('请先选择要处理的商品。');
      return;
    }

    const nextStatus = action === 'select' ? 'resolved' : 'ignored';
    setProcessingKey(action);
    try {
      await Promise.all(
        productIds.map((productId) => {
          const product = products.find((item) => item.product_id === productId);
          return updateIssueAction({
            issue_type: 'selection_candidate',
            issue_key: productId,
            title: product?.name || '重点运营候选',
            status: nextStatus,
            metadata: {
              product_id: productId,
              category: product?.category || '',
              decision: action,
            },
          });
        }),
      );

      setProducts((prev) =>
        prev.map((item) =>
          productIds.includes(item.product_id)
            ? { ...item, status: action === 'select' ? 'selected' : 'rejected' }
            : item,
        ),
      );
      setSelectedProducts(new Set());
      setMessage(action === 'select' ? `已纳入 ${productIds.length} 个重点运营商品` : `已标记 ${productIds.length} 个商品为暂不考虑`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '操作失败');
    } finally {
      setProcessingKey(null);
    }
  }

  const categories = Array.from(new Set(products.map((product) => product.category).filter(Boolean)));
  const statuses = ['recommended', 'considering', 'selected', 'rejected'];

  const filteredProducts = products.filter((product) => {
    const categoryMatch = !filterCategory || product.category === filterCategory;
    const statusMatch = !filterStatus || product.status === filterStatus;
    return categoryMatch && statusMatch;
  });

  const summary = {
    total: products.length,
    recommended: products.filter((item) => item.status === 'recommended').length,
    selected: products.filter((item) => item.status === 'selected').length,
    avgScore:
      products.length > 0
        ? (products.reduce((sum, item) => sum + item.recommendation_score, 0) / products.length).toFixed(1)
        : '0.0',
    avgMargin:
      products.length > 0
        ? (products.reduce((sum, item) => sum + item.profit_margin, 0) / products.length).toFixed(1)
        : '0.0',
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">重点运营候选池</h1>
          <p className="text-muted-foreground">基于当前商品、订单、库存和知识完整度给出优先运营候选。</p>
        </div>
        <Card>
          <CardContent className="p-6">
            <div className="h-40 animate-pulse rounded bg-muted" />
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">重点运营候选池</h1>
          <p className="text-muted-foreground">基于当前商品、订单、库存和知识完整度给出优先运营候选。</p>
        </div>
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <div className="text-lg text-red-700">加载失败</div>
            <p className="mt-2 text-sm text-red-600">{error}</p>
            <Button className="mt-4" onClick={() => void loadData()}>重试</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">重点运营候选池</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            这里不是“选新品”，而是从现有商品里找出更值得重点运营的对象。
          </p>
        </div>
        <a href="/imports">
          <Button variant="outline">刷新数据基础</Button>
        </a>
      </div>

      {message && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
          {message}
        </div>
      )}

      <Card className="border-slate-200 bg-slate-50">
        <CardContent className="grid gap-4 p-5 md:grid-cols-4">
          <div>
            <div className="text-sm text-muted-foreground">数据边界</div>
            <div className="mt-1 text-sm text-slate-700">只基于现有商品、订单、库存和知识完整度，不做外部市场判断。</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">候选总数</div>
            <div className="mt-1 text-2xl font-bold">{summary.total}</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">优先运营</div>
            <div className="mt-1 text-2xl font-bold text-green-600">{summary.recommended}</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">已纳入重点</div>
            <div className="mt-1 text-2xl font-bold text-blue-600">{summary.selected}</div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-5">
        <Card><CardContent className="p-5"><div className="text-sm text-muted-foreground">平均推荐分</div><div className="mt-2 text-3xl font-bold">{summary.avgScore}</div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="text-sm text-muted-foreground">平均毛利率</div><div className="mt-2 text-3xl font-bold">{summary.avgMargin}%</div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="text-sm text-muted-foreground">有知识支撑</div><div className="mt-2 text-3xl font-bold">{products.filter((item) => item.knowledge_ready).length}</div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="text-sm text-muted-foreground">库存为 0</div><div className="mt-2 text-3xl font-bold">{products.filter((item) => item.stock === 0).length}</div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="text-sm text-muted-foreground">高销量商品</div><div className="mt-2 text-3xl font-bold">{products.filter((item) => item.monthly_sales >= 30).length}</div></CardContent></Card>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-4 sm:flex-row">
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className="max-w-xs rounded-md border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">所有品类</option>
            {categories.map((category) => (
              <option key={category} value={category}>{category}</option>
            ))}
          </select>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="max-w-xs rounded-md border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">所有状态</option>
            {statuses.map((status) => (
              <option key={status} value={status}>{statusText(status)}</option>
            ))}
          </select>
        </div>
        {selectedProducts.size > 0 && (
          <div className="flex gap-2">
            <Button
              disabled={processingKey !== null}
              onClick={() => void applySelectionAction(Array.from(selectedProducts), 'select')}
            >
              {processingKey === 'select' ? '处理中...' : `纳入重点 (${selectedProducts.size})`}
            </Button>
            <Button
              variant="outline"
              disabled={processingKey !== null}
              onClick={() => void applySelectionAction(Array.from(selectedProducts), 'reject')}
            >
              {processingKey === 'reject' ? '处理中...' : `暂不考虑 (${selectedProducts.size})`}
            </Button>
          </div>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>候选商品工作池</CardTitle>
        </CardHeader>
        <CardContent>
          {filteredProducts.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              当前筛选条件下没有候选商品。
            </div>
          ) : (
            <div className="space-y-4">
              {filteredProducts.map((product) => (
                <div key={product.product_id} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          type="checkbox"
                          checked={selectedProducts.has(product.product_id)}
                          onChange={(e) => {
                            setSelectedProducts((prev) => {
                              const next = new Set(prev);
                              if (e.target.checked) {
                                next.add(product.product_id);
                              } else {
                                next.delete(product.product_id);
                              }
                              return next;
                            });
                          }}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                        <div className="font-medium text-slate-900">{product.name}</div>
                        <Badge variant="outline">{product.category || '未分类'}</Badge>
                        <span className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${statusBadge(product.status)}`}>
                          {statusText(product.status)}
                        </span>
                      </div>

                      <div className="mt-3 grid gap-3 text-sm md:grid-cols-5">
                        <div>
                          <div className="text-muted-foreground">售价</div>
                          <div className="font-medium">¥{product.price.toFixed(2)}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">近 30 天销量</div>
                          <div className="font-medium">{product.monthly_sales}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">当前库存</div>
                          <div className="font-medium">
                            {product.stock}
                            {product.stock_days != null ? ` / ${product.stock_days} 天` : ''}
                          </div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">毛利率</div>
                          <div className="font-medium">{product.profit_margin}%</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">推荐分</div>
                          <div className={`font-bold ${scoreColor(product.recommendation_score)}`}>
                            {product.recommendation_score} / 10
                          </div>
                        </div>
                      </div>

                      <div className="mt-3 text-sm text-slate-700">{product.reason}</div>
                      {product.risk_warning ? (
                        <div className="mt-2 text-sm text-amber-700">{product.risk_warning}</div>
                      ) : null}

                      <div className="mt-3 flex flex-wrap gap-2">
                        {(product.data_source || []).map((item) => (
                          <span key={item} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">
                            {item}
                          </span>
                        ))}
                        <span className={`rounded px-2 py-1 text-xs ${product.knowledge_ready ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
                          {product.knowledge_ready ? `知识条目 ${product.knowledge_count}` : '缺少知识支撑'}
                        </span>
                      </div>
                    </div>

                    <div className="flex gap-2 lg:w-[220px] lg:flex-col">
                      <Button
                        disabled={processingKey === product.product_id}
                        onClick={() => void applySelectionAction([product.product_id], 'select')}
                      >
                        {processingKey === product.product_id ? '处理中...' : '纳入重点'}
                      </Button>
                      <Button
                        variant="outline"
                        disabled={processingKey === product.product_id}
                        onClick={() => void applySelectionAction([product.product_id], 'reject')}
                      >
                        暂不考虑
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default withErrorBoundary(SelectionPage);
