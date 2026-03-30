'use client';

import { useEffect, useState } from 'react';
import { withErrorBoundary } from '@/components/error-boundary';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchAPI, lookupIssueActions, updateIssueAction, type IssueActionRecord } from '@/lib/api';

interface BundleProduct {
  product_id: string;
  name: string;
  unit_price: number;
  monthly_sales?: number;
}

interface BundleRecommendation {
  id: string;
  name: string;
  product_ids: string[];
  products?: BundleProduct[];
  confidence: number;
  lift_value: number;
  bundle_price: number;
  estimated_profit_margin?: number | null;
  pair_orders?: number;
  reason?: string;
  data_source?: string;
  status?: string;
}

function getBundleStatus(bundle: BundleRecommendation, action?: IssueActionRecord | null) {
  if (!action) {
    return bundle.status || 'pending';
  }
  if (action.status === 'resolved') {
    return 'active';
  }
  if (action.status === 'ignored') {
    return 'inactive';
  }
  return 'pending';
}

function statusBadge(status: string) {
  switch (status) {
    case 'active':
      return <Badge className="bg-green-100 text-green-700">已纳入执行</Badge>;
    case 'inactive':
      return <Badge className="bg-slate-100 text-slate-600">暂不执行</Badge>;
    default:
      return <Badge className="bg-amber-100 text-amber-700">待复核</Badge>;
  }
}

function BundlesPage() {
  const [bundles, setBundles] = useState<BundleRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    void loadBundles();
  }, []);

  async function loadBundles() {
    try {
      setLoading(true);
      setError(null);
      const raw = await fetchAPI<BundleRecommendation[]>('/bundles/recommendations');
      const issues = raw.length > 0
        ? await lookupIssueActions(
            raw.map((item) => ({
              issue_type: 'bundle_candidate',
              issue_key: item.id,
            })),
          )
        : [];
      const issueMap = new Map(issues.map((item) => [item.issue_key, item]));
      setBundles(raw.map((item) => ({ ...item, status: getBundleStatus(item, issueMap.get(item.id)) })));
      setMessage(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载套餐建议失败');
    } finally {
      setLoading(false);
    }
  }

  async function applyBundleDecision(bundle: BundleRecommendation, action: 'activate' | 'deactivate') {
    const status = action === 'activate' ? 'resolved' : 'ignored';
    setActionLoading(`${bundle.id}:${action}`);
    try {
      await updateIssueAction({
        issue_type: 'bundle_candidate',
        issue_key: bundle.id,
        title: bundle.name,
        status,
        metadata: {
          bundle_id: bundle.id,
          decision: action,
          product_ids: bundle.product_ids,
          pair_orders: bundle.pair_orders || 0,
        },
      });
      setBundles((prev) =>
        prev.map((item) =>
          item.id === bundle.id ? { ...item, status: action === 'activate' ? 'active' : 'inactive' } : item,
        ),
      );
      setMessage(action === 'activate' ? '套餐已纳入执行' : '套餐已标记为暂不执行');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '操作失败');
    } finally {
      setActionLoading(null);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">套餐候选池</h1>
          <p className="text-muted-foreground">优先基于真实订单共购关系推荐套餐。</p>
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
          <h1 className="text-3xl font-bold tracking-tight">套餐候选池</h1>
          <p className="text-muted-foreground">优先基于真实订单共购关系推荐套餐。</p>
        </div>
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <div className="text-lg text-red-700">加载失败</div>
            <p className="mt-2 text-sm text-red-600">{error}</p>
            <Button className="mt-4" onClick={() => void loadBundles()}>重试</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const activeCount = bundles.filter((bundle) => bundle.status === 'active').length;
  const avgConfidence =
    bundles.length > 0
      ? ((bundles.reduce((sum, bundle) => sum + (bundle.confidence || 0), 0) / bundles.length) * 100).toFixed(1)
      : '0.0';

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">套餐候选池</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            套餐建议优先基于近 30 天真实订单共购，不再只靠品类规则做展示。
          </p>
        </div>
        <Button variant="outline" onClick={() => void loadBundles()}>
          重新计算
        </Button>
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
            <div className="mt-1 text-sm text-slate-700">仅基于近 30 天订单共购，不做竞品或外部流量推断。</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">套餐候选</div>
            <div className="mt-1 text-2xl font-bold">{bundles.length}</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">已纳入执行</div>
            <div className="mt-1 text-2xl font-bold text-green-600">{activeCount}</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">平均置信度</div>
            <div className="mt-1 text-2xl font-bold">{avgConfidence}%</div>
          </div>
        </CardContent>
      </Card>

      {bundles.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center text-sm text-muted-foreground">
            近 30 天订单共购数据不足，暂时无法生成可信套餐。
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          {bundles.map((bundle) => (
            <Card key={bundle.id} className="border-slate-200">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base leading-snug">{bundle.name}</CardTitle>
                    <p className="mt-1 text-xs text-muted-foreground">{bundle.data_source || '真实订单共购'}</p>
                  </div>
                  {statusBadge(bundle.status || 'pending')}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  {(bundle.products || []).map((product) => (
                    <div key={product.product_id} className="rounded-lg border bg-slate-50 p-3">
                      <div className="font-medium text-slate-900">{product.name}</div>
                      <div className="mt-1 text-xs text-slate-500">
                        单价 ¥{product.unit_price.toFixed(2)}
                        {product.monthly_sales != null ? ` / 月销 ${product.monthly_sales}` : ''}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-blue-50 p-3">
                    <div className="text-xs text-blue-600">同单共购</div>
                    <div className="text-lg font-bold text-blue-700">{bundle.pair_orders || 0} 单</div>
                  </div>
                  <div className="rounded-lg bg-purple-50 p-3">
                    <div className="text-xs text-purple-600">Lift 值</div>
                    <div className="text-lg font-bold text-purple-700">{bundle.lift_value.toFixed(2)}</div>
                  </div>
                  <div className="rounded-lg bg-green-50 p-3">
                    <div className="text-xs text-green-600">套餐价</div>
                    <div className="text-lg font-bold text-green-700">¥{bundle.bundle_price.toFixed(2)}</div>
                  </div>
                  <div className="rounded-lg bg-orange-50 p-3">
                    <div className="text-xs text-orange-600">预计利润率</div>
                    <div className="text-lg font-bold text-orange-700">
                      {bundle.estimated_profit_margin != null ? `${bundle.estimated_profit_margin.toFixed(1)}%` : '—'}
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                  {bundle.reason || '订单共购关系明显，值得做套餐试卖。'}
                </div>

                <div className="flex gap-2">
                  {bundle.status !== 'active' ? (
                    <Button
                      className="flex-1"
                      disabled={actionLoading === `${bundle.id}:activate`}
                      onClick={() => void applyBundleDecision(bundle, 'activate')}
                    >
                      {actionLoading === `${bundle.id}:activate` ? '处理中...' : '纳入执行'}
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      className="flex-1"
                      disabled={actionLoading === `${bundle.id}:deactivate`}
                      onClick={() => void applyBundleDecision(bundle, 'deactivate')}
                    >
                      {actionLoading === `${bundle.id}:deactivate` ? '处理中...' : '暂不执行'}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default withErrorBoundary(BundlesPage);
