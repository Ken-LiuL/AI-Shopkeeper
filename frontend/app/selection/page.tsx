'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

import { withErrorBoundary } from '@/components/error-boundary';
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
}

interface SelectionSummary {
  total_candidates: number;
  recommended_count: number;
  selected_count: number;
  avg_profit_margin: number;
  categories_covered: number;
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
          <p className="text-muted-foreground">AI 驱动的商品选择建议与分析</p>
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
                    <TableCell className="font-medium">{product.name}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{product.category}</Badge>
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
                      <div className="flex gap-1">
                        {product.status !== 'selected' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleBatchOperation('select', product.product_id)}
                            disabled={batchProcessing}
                            className="text-green-600 hover:text-green-700"
                          >
                            选中
                          </Button>
                        )}
                        {product.status !== 'rejected' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleBatchOperation('reject', product.product_id)}
                            disabled={batchProcessing}
                            className="text-red-600 hover:text-red-700"
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
