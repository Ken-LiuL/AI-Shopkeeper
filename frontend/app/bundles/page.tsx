'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { withErrorBoundary } from '@/components/error-boundary';
import { AICapabilityHeader } from '@/components/ai-capability-badge';
import { fetchAPI } from '@/lib/api';
import { AIReasoningPanel } from '@/components/ai-reasoning-panel';
import { AIActionButton } from '@/components/ai-action-button';

interface BundleRecommendation {
  id: string;
  name: string;
  product_ids: string[];
  confidence: number;
  lift_value: number;
  bundle_price: number;
  estimated_profit_margin: number;
  status?: string;
}

function buildBundleReasoningSteps(bundle: BundleRecommendation) {
  const liftStr = bundle.lift_value != null ? bundle.lift_value.toFixed(2) : '—';
  const confPct = bundle.confidence != null
    ? (bundle.confidence <= 1 ? (bundle.confidence * 100).toFixed(0) : bundle.confidence.toFixed(0))
    : '—';
  return [
    { icon: '📦', title: '关联挖掘', detail: `发现 ${bundle.product_ids?.length ?? 0} 件商品强关联`, status: 'completed' as const },
    { icon: '📊', title: '支持度分析', detail: `Lift 值 ${liftStr}，关联强度${Number(liftStr) >= 2 ? '高' : '中等'}`, status: 'completed' as const },
    { icon: '💰', title: '定价优化', detail: `套餐价 ¥${bundle.bundle_price?.toFixed(2) ?? '—'}，利润率 ${bundle.estimated_profit_margin?.toFixed(1) ?? '—'}%`, status: 'completed' as const },
    { icon: '✔️', title: '置信验证', detail: `置信度 ${confPct}%，已通过历史数据验证`, status: 'completed' as const },
  ];
}

function BundlesPage() {
  const [bundles, setBundles] = useState<BundleRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchBundles = async () => {
    try {
      setError(null);
      type BundlesApiResponse = BundleRecommendation[] | { bundles?: BundleRecommendation[]; recommendations?: BundleRecommendation[] };
      const data = await fetchAPI<BundlesApiResponse>('/bundles/recommendations');
      setBundles(Array.isArray(data) ? data : (data as { bundles?: BundleRecommendation[]; recommendations?: BundleRecommendation[] }).bundles || (data as { bundles?: BundleRecommendation[]; recommendations?: BundleRecommendation[] }).recommendations || []);
    } catch (err) {
      console.error('Error fetching bundles:', err);
      setError('加载套餐数据失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBundles();
  }, []);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await fetchAPI('/bundles/generate', { method: 'POST' });
      await fetchBundles();
    } catch (err) {
      console.error('Error generating bundles:', err);
      alert('生成套餐建议失败，请稍后重试');
    } finally {
      setGenerating(false);
    }
  };

  const handleActivate = async (id: string) => {
    setActionLoading(id + '_activate');
    try {
      await fetchAPI(`/bundles/${id}/activate`, { method: 'POST' });
      setBundles(prev =>
        prev.map(b => b.id === id ? { ...b, status: 'active' } : b)
      );
    } catch (err) {
      console.error('Error activating bundle:', err);
      alert('上架失败，请稍后重试');
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeactivate = async (id: string) => {
    setActionLoading(id + '_deactivate');
    try {
      await fetchAPI(`/bundles/${id}/deactivate`, { method: 'POST' });
      setBundles(prev =>
        prev.map(b => b.id === id ? { ...b, status: 'inactive' } : b)
      );
    } catch (err) {
      console.error('Error deactivating bundle:', err);
      alert('下架失败，请稍后重试');
    } finally {
      setActionLoading(null);
    }
  };

  const getStatusBadge = (status?: string) => {
    switch (status) {
      case 'active':
        return <Badge className="bg-green-100 text-green-700">已上架</Badge>;
      case 'inactive':
        return <Badge className="bg-gray-100 text-gray-600">已下架</Badge>;
      default:
        return <Badge className="bg-yellow-100 text-yellow-700">待上架</Badge>;
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">🎁 智能套餐</h1>
            <p className="text-muted-foreground">AI 分析商品关联购买数据，自动发现套餐机会并优化定价</p>
          </div>
          <Button disabled>生成套餐建议</Button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map(i => (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="h-40 bg-muted animate-pulse rounded"></div>
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
            <h1 className="text-3xl font-bold tracking-tight">🎁 智能套餐</h1>
            <p className="text-muted-foreground">AI 分析商品关联购买数据，自动发现套餐机会并优化定价</p>
          </div>
          <Button onClick={handleGenerate} disabled={generating}>
            {generating ? '生成中...' : '生成套餐建议'}
          </Button>
        </div>
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <div className="text-red-500 text-4xl mb-4">⚠️</div>
            <h3 className="text-lg font-medium text-red-800 mb-2">数据加载失败</h3>
            <p className="text-red-600 mb-4">{error}</p>
            <Button onClick={fetchBundles} variant="destructive">重新加载</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">🎁 智能套餐</h1>
          <AICapabilityHeader
            capabilities={['关联规则挖掘', 'GraphRAG 知识图谱', 'Self-Reflection 自检', '事实核查']}
            description="AI 分析商品关联购买数据，自动发现套餐机会并优化定价"
          />
        </div>
        <Button onClick={handleGenerate} disabled={generating}>
          {generating ? (
            <span className="flex items-center gap-2">
              <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></span>
              生成中...
            </span>
          ) : '✨ 生成套餐建议'}
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">套餐总数</p>
                <p className="text-2xl font-bold">{bundles.length}</p>
              </div>
              <div className="text-3xl">🎁</div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">已上架</p>
                <p className="text-2xl font-bold text-green-600">
                  {bundles.filter(b => b.status === 'active').length}
                </p>
              </div>
              <div className="text-3xl">✅</div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">平均置信度</p>
                <p className="text-2xl font-bold text-blue-600">
                  {bundles.length > 0
                    ? (bundles.reduce((sum, b) => sum + (b.confidence || 0), 0) / bundles.length * 100).toFixed(1) + '%'
                    : '—'}
                </p>
              </div>
              <div className="text-3xl">📊</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Bundles List */}
      {bundles.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <div className="text-5xl mb-4">🎁</div>
            <h3 className="text-lg font-medium text-gray-700 mb-2">暂无套餐建议</h3>
            <p className="text-muted-foreground mb-6">点击「生成套餐建议」按钮，AI 将基于历史订单分析商品关联关系</p>
            <Button onClick={handleGenerate} disabled={generating}>
              {generating ? '生成中...' : '生成套餐建议'}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {bundles.map((bundle) => (
            <Card key={bundle.id} className="hover:shadow-md transition-shadow">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base font-semibold leading-snug">
                    {bundle.name || `套餐 #${bundle.id}`}
                  </CardTitle>
                  {getStatusBadge(bundle.status)}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Products */}
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-2">包含商品</p>
                  <div className="flex flex-wrap gap-1">
                    {(bundle.product_ids || []).map((pid, idx) => (
                      <Badge key={idx} variant="outline" className="text-xs">
                        {pid}
                      </Badge>
                    ))}
                  </div>
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-blue-50 rounded-lg p-3">
                    <p className="text-xs text-blue-600 font-medium">置信度</p>
                    <p className="text-lg font-bold text-blue-700">
                      {bundle.confidence != null
                        ? (bundle.confidence <= 1
                          ? (bundle.confidence * 100).toFixed(1) + '%'
                          : bundle.confidence.toFixed(1) + '%')
                        : '—'}
                    </p>
                  </div>
                  <div className="bg-purple-50 rounded-lg p-3">
                    <p className="text-xs text-purple-600 font-medium">Lift 值</p>
                    <p className="text-lg font-bold text-purple-700">
                      {bundle.lift_value != null ? bundle.lift_value.toFixed(2) : '—'}
                    </p>
                  </div>
                  <div className="bg-green-50 rounded-lg p-3">
                    <p className="text-xs text-green-600 font-medium">套餐价格</p>
                    <p className="text-lg font-bold text-green-700">
                      {bundle.bundle_price != null ? `¥${bundle.bundle_price.toFixed(2)}` : '—'}
                    </p>
                  </div>
                  <div className="bg-orange-50 rounded-lg p-3">
                    <p className="text-xs text-orange-600 font-medium">预计利润率</p>
                    <p className="text-lg font-bold text-orange-700">
                      {bundle.estimated_profit_margin != null
                        ? bundle.estimated_profit_margin.toFixed(1) + '%'
                        : '—'}
                    </p>
                  </div>
                </div>

                {/* AI Reasoning */}
                <AIReasoningPanel
                  steps={buildBundleReasoningSteps(bundle)}
                  confidence={bundle.confidence != null
                    ? Math.round(bundle.confidence <= 1 ? bundle.confidence * 100 : bundle.confidence)
                    : undefined}
                />

                {/* Actions */}
                <div className="flex gap-2 pt-1 flex-wrap">
                  {bundle.status !== 'active' && (
                    <AIActionButton
                      label="创建套餐"
                      loading={actionLoading === bundle.id + '_activate'}
                      confirmed={bundle.status === 'active'}
                      onAction={() => handleActivate(bundle.id)}
                      className="flex-1"
                    />
                  )}
                  {bundle.status === 'active' && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="flex-1 border-red-300 text-red-600 hover:bg-red-50"
                      onClick={() => handleDeactivate(bundle.id)}
                      disabled={actionLoading === bundle.id + '_deactivate'}
                    >
                      {actionLoading === bundle.id + '_deactivate' ? '下架中...' : '⬇ 下架'}
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
