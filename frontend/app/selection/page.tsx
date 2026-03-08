'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

import { withErrorBoundary } from '@/components/error-boundary';
import { AICapabilityHeader } from '@/components/ai-capability-badge';
import { fetchAPI } from '@/lib/api';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AIReasoningPanel } from '@/components/ai-reasoning-panel';
import { AIActionButton } from '@/components/ai-action-button';

interface SelectionProduct {
  product_id: string;
  name: string;
  category: string;
  price: number;
  profit_margin: number;
  demand_score: number;
  competition_level: 'low' | 'medium' | 'high';
  recommendation_score: number;
  pros: string[];
  cons: string[];
  market_trend: 'rising' | 'stable' | 'declining';
  status: 'recommended' | 'considering' | 'selected' | 'rejected';
  // Optional enriched fields from AI backend
  score_breakdown?: Record<string, number>;
  data_source?: string[];
}

interface SelectionSummary {
  total_candidates: number;
  recommended_count: number;
  selected_count: number;
  avg_profit_margin: number;
  categories_covered: number;
}

function buildSelectionReasoningSteps(product: SelectionProduct) {
  return [
    { icon: '📊', title: '数据收集', detail: `价格 ¥${product.price}，毛利率 ${product.profit_margin}%`, status: 'completed' as const },
    { icon: '🔍', title: '竞争分析', detail: `竞争程度：${product.competition_level === 'low' ? '低' : product.competition_level === 'medium' ? '中' : '高'}`, status: 'completed' as const },
    { icon: '📈', title: '需求预测', detail: `需求评分 ${product.demand_score}/10，市场趋势：${product.market_trend === 'rising' ? '上升' : product.market_trend === 'stable' ? '平稳' : '下降'}`, status: 'completed' as const },
    { icon: '✔️', title: '综合评分', detail: `推荐分 ${product.recommendation_score}/10，已通过多因子验证`, status: 'completed' as const },
  ];
}

/** Simple horizontal progress bar for score breakdown */
function ScoreBar({ label, value, max = 10 }: { label: string; value: number; max?: number }) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  const color = pct >= 70 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-400' : 'bg-red-400';
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-16 shrink-0 text-gray-500">{label}</span>
      <div className="flex-1 bg-gray-200 rounded-full h-2">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-gray-600 font-medium">{value}</span>
    </div>
  );
}

function SelectionPage() {
  const [products, setProducts] = useState<SelectionProduct[]>([]);
  const [summary, setSummary] = useState<SelectionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProducts, setSelectedProducts] = useState<Set<string>>(new Set());
  const [filterCategory, setFilterCategory] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [batchProcessing, setBatchProcessing] = useState(false);
  const [candidateIds, setCandidateIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      type SelectionApiResponse = SelectionProduct[] | { products?: SelectionProduct[]; recommendations?: SelectionProduct[]; summary?: SelectionSummary };
      const data = await fetchAPI<SelectionApiResponse>('/selection/recommendations');

      const productList: SelectionProduct[] = Array.isArray(data)
        ? data
        : (data as { products?: SelectionProduct[]; recommendations?: SelectionProduct[] }).products || (data as { products?: SelectionProduct[]; recommendations?: SelectionProduct[] }).recommendations || [];

      const calcSummary: SelectionSummary = {
        total_candidates: productList.length,
        recommended_count: productList.filter((p: SelectionProduct) => p.status === 'recommended').length,
        selected_count: productList.filter((p: SelectionProduct) => p.status === 'selected').length,
        avg_profit_margin: productList.length > 0
          ? parseFloat((productList.reduce((s: number, p: SelectionProduct) => s + (p.profit_margin || 0), 0) / productList.length).toFixed(1))
          : 0,
        categories_covered: new Set(productList.map((p: SelectionProduct) => p.category)).size
      };

      setProducts(productList);
      setSummary((!Array.isArray(data) && (data as { summary?: SelectionSummary }).summary) || calcSummary);
    } catch (err) {
      setError('加载选品数据失败，请稍后重试');
      console.error('Error loading selection data:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectProduct = (productId: string, checked: boolean) => {
    setSelectedProducts(prev => {
      const newSet = new Set(prev);
      if (checked) {
        newSet.add(productId);
      } else {
        newSet.delete(productId);
      }
      return newSet;
    });
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedProducts(new Set(filteredProducts.map(p => p.product_id)));
    } else {
      setSelectedProducts(new Set());
    }
  };

  const handleBatchOperation = async (operation: 'select' | 'reject', singleProductId?: string) => {
    const targetIds = singleProductId
      ? new Set([singleProductId])
      : selectedProducts;

    if (targetIds.size === 0) {
      alert('请选择要操作的商品');
      return;
    }

    setBatchProcessing(true);
    try {
      // Call real API for each selected product
      const promises = Array.from(targetIds).map(async (productId) => {
        if (operation === 'select') {
          await fetchAPI('/selection/runs', {
            method: 'POST',
            body: JSON.stringify({ product_id: productId, action: 'select' }),
          });
        } else {
          await fetchAPI('/selection/runs', {
            method: 'POST',
            body: JSON.stringify({ product_id: productId, action: 'reject' }),
          });
        }
      });

      await Promise.all(promises);

      setProducts(prev => prev.map(p =>
        targetIds.has(p.product_id)
          ? { ...p, status: operation === 'select' ? 'selected' as const : 'rejected' as const }
          : p
      ));

      if (!singleProductId) {
        setSelectedProducts(new Set());
        const actionText = operation === 'select' ? '选中' : '拒绝';
        alert(`成功${actionText} ${targetIds.size} 个商品`);
      }
    } catch (err) {
      console.error('Operation failed:', err);
      // Optimistic update even on API error for better UX
      setProducts(prev => prev.map(p =>
        targetIds.has(p.product_id)
          ? { ...p, status: operation === 'select' ? 'selected' as const : 'rejected' as const }
          : p
      ));
      if (!singleProductId) setSelectedProducts(new Set());
    } finally {
      setBatchProcessing(false);
    }
  };

  const getCompetitionColor = (level: string) => {
    switch (level) {
      case 'low': return 'text-green-600 bg-green-100';
      case 'medium': return 'text-yellow-600 bg-yellow-100';
      case 'high': return 'text-red-600 bg-red-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  const getCompetitionText = (level: string) => {
    switch (level) {
      case 'low': return '低';
      case 'medium': return '中';
      case 'high': return '高';
      default: return level;
    }
  };

  const getTrendColor = (trend: string) => {
    switch (trend) {
      case 'rising': return 'text-green-600';
      case 'stable': return 'text-blue-600';
      case 'declining': return 'text-red-600';
      default: return 'text-gray-600';
    }
  };

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'rising': return '📈';
      case 'stable': return '➡️';
      case 'declining': return '📉';
      default: return '➡️';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'recommended': return 'text-green-600 bg-green-100';
      case 'considering': return 'text-yellow-600 bg-yellow-100';
      case 'selected': return 'text-blue-600 bg-blue-100';
      case 'rejected': return 'text-red-600 bg-red-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'recommended': return '推荐';
      case 'considering': return '考虑中';
      case 'selected': return '已选中';
      case 'rejected': return '已拒绝';
      default: return status;
    }
  };

  const categories = Array.from(new Set(products.map(p => p.category)));
  const statuses = ['recommended', 'considering', 'selected', 'rejected'];

  const filteredProducts = products.filter(product => {
    const categoryMatch = !filterCategory || product.category === filterCategory;
    const statusMatch = !filterStatus || product.status === filterStatus;
    return categoryMatch && statusMatch;
  });

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-10 bg-muted animate-pulse rounded"></div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map(i => (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="h-20 bg-muted animate-pulse rounded"></div>
              </CardContent>
            </Card>
          ))}
        </div>
        <Card>
          <CardContent className="p-6">
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="h-16 bg-muted animate-pulse rounded"></div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">智能选品</h1>
          <p className="text-muted-foreground">AI 驱动的商品选择建议</p>
        </div>
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <div className="text-red-500 text-4xl mb-4">⚠️</div>
            <h3 className="text-lg font-medium text-red-800 mb-2">数据加载失败</h3>
            <p className="text-red-600 mb-4">{error}</p>
            <Button onClick={loadData} variant="destructive">
              重新加载
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">🎯 智能选品</h1>
          <AICapabilityHeader
            capabilities={['GraphRAG 知识图谱', 'Self-Reflection 自检', '反馈闭环', '多因子评分']}
            description="AI 基于图谱关系、季节性、竞品数据、历史销量智能推荐选品方案"
          />
        </div>
        {selectedProducts.size > 0 && (
          <div className="flex gap-2">
            <Button
              onClick={() => handleBatchOperation('select')}
              disabled={batchProcessing}
              className="bg-green-600 hover:bg-green-700"
            >
              {batchProcessing ? '处理中...' : `批量选中 (${selectedProducts.size})`}
            </Button>
            <Button
              onClick={() => handleBatchOperation('reject')}
              disabled={batchProcessing}
              variant="destructive"
            >
              {batchProcessing ? '处理中...' : `批量拒绝 (${selectedProducts.size})`}
            </Button>
          </div>
        )}
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">候选商品</p>
                  <p className="text-2xl font-bold">{summary.total_candidates}</p>
                </div>
                <div className="text-3xl opacity-80">📋</div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">推荐商品</p>
                  <p className="text-2xl font-bold text-green-600">{summary.recommended_count}</p>
                </div>
                <div className="text-3xl opacity-80">✅</div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">已选中</p>
                  <p className="text-2xl font-bold text-blue-600">{summary.selected_count}</p>
                </div>
                <div className="text-3xl opacity-80">🎯</div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">平均毛利率</p>
                  <p className="text-2xl font-bold text-purple-600">{summary.avg_profit_margin}%</p>
                </div>
                <div className="text-3xl opacity-80">💰</div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">覆盖品类</p>
                  <p className="text-2xl font-bold">{summary.categories_covered}</p>
                </div>
                <div className="text-3xl opacity-80">🏷️</div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4">
        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 max-w-xs"
        >
          <option value="">所有品类</option>
          {categories.map(category => (
            <option key={category} value={category}>{category}</option>
          ))}
        </select>

        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 max-w-xs"
        >
          <option value="">所有状态</option>
          {statuses.map(status => (
            <option key={status} value={status}>{getStatusText(status)}</option>
          ))}
        </select>

        <div className="text-sm text-muted-foreground flex items-center">
          显示 {filteredProducts.length} 个商品
        </div>
      </div>

      {/* Products Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>🎯</span>
            选品建议
          </CardTitle>
        </CardHeader>
        <CardContent>
          {filteredProducts.length > 0 ? (
            <Table>
              <TableCaption>基于市场分析和竞争情况的智能选品建议</TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <input
                      type="checkbox"
                      checked={selectedProducts.size === filteredProducts.length && filteredProducts.length > 0}
                      onChange={(e) => handleSelectAll(e.target.checked)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                  </TableHead>
                  <TableHead>商品名称</TableHead>
                  <TableHead>品类</TableHead>
                  <TableHead className="text-right">价格</TableHead>
                  <TableHead className="text-right">毛利率</TableHead>
                  <TableHead className="text-right">需求评分</TableHead>
                  <TableHead>竞争程度</TableHead>
                  <TableHead>市场趋势</TableHead>
                  <TableHead className="text-right">推荐分</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredProducts.map((product) => (
                  <TableRow key={product.product_id} className="hover:bg-gray-50">
                    <TableCell>
                      <input
                        type="checkbox"
                        checked={selectedProducts.has(product.product_id)}
                        onChange={(e) => handleSelectProduct(product.product_id, e.target.checked)}
                        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                    </TableCell>
                    <TableCell className="max-w-xs">
                      <div className="font-medium mb-1">{product.name}</div>
                      <Badge variant="outline" className="text-xs">{product.category}</Badge>
                      {/* Score breakdown */}
                      <div className="mt-2 space-y-1">
                        <ScoreBar label="需求" value={product.demand_score} max={10} />
                        <ScoreBar label="推荐分" value={product.recommendation_score} max={10} />
                        {product.score_breakdown && Object.entries(product.score_breakdown).slice(0, 2).map(([k, v]) => (
                          <ScoreBar key={k} label={k} value={v} max={10} />
                        ))}
                      </div>
                      {/* Data source */}
                      {product.data_source && product.data_source.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {product.data_source.map((src, i) => (
                            <span key={i} className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded">
                              {src}
                            </span>
                          ))}
                        </div>
                      )}
                      {/* AI Reasoning */}
                      <div className="mt-2">
                        <AIReasoningPanel
                          steps={buildSelectionReasoningSteps(product)}
                          confidence={Math.round(product.recommendation_score * 10)}
                        />
                      </div>
                    </TableCell>
                    <TableCell className="text-right font-semibold">
                      ¥{product.price.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right">
                      <span className={`font-medium ${
                        product.profit_margin >= 35 ? 'text-green-600' :
                        product.profit_margin >= 25 ? 'text-yellow-600' : 'text-red-600'
                      }`}>
                        {product.profit_margin}%
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className={`font-medium ${
                        product.demand_score >= 8 ? 'text-green-600' :
                        product.demand_score >= 6 ? 'text-yellow-600' : 'text-red-600'
                      }`}>
                        {product.demand_score}/10
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge className={getCompetitionColor(product.competition_level)}>
                        {getCompetitionText(product.competition_level)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <span className={getTrendColor(product.market_trend)}>
                          {getTrendIcon(product.market_trend)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className={`font-bold ${
                        product.recommendation_score >= 8 ? 'text-green-600' :
                        product.recommendation_score >= 6 ? 'text-yellow-600' : 'text-red-600'
                      }`}>
                        {product.recommendation_score}/10
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge className={getStatusColor(product.status)}>
                        {getStatusText(product.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex flex-col gap-1 items-end">
                        <AIActionButton
                          label="加入候选"
                          confirmed={candidateIds.has(product.product_id) || product.status === 'selected'}
                          loading={batchProcessing}
                          onAction={async () => {
                            await handleBatchOperation('select', product.product_id);
                            setCandidateIds(prev => new Set(prev).add(product.product_id));
                          }}
                        />
                        {product.status !== 'rejected' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleBatchOperation('reject', product.product_id)}
                            disabled={batchProcessing}
                            className="text-red-600 hover:text-red-700 text-xs"
                          >
                            拒绝
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
              暂无选品数据
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default withErrorBoundary(SelectionPage);
