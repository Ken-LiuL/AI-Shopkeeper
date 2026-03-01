'use client';
import { useEffect, useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
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
import { getProducts, getRestockSuggestions } from '@/lib/api';
import type { Product, ProductsResponse, RestockSuggestion } from '@/lib/api';

function ProductsPage() {
  const [data, setData] = useState<ProductsResponse | null>(null);
  const [restockSuggestions, setRestockSuggestions] = useState<RestockSuggestion[]>([]);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'inventory' | 'restock'>('inventory');
  const pageSize = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [productsRes, restockRes] = await Promise.all([
        getProducts(page, pageSize),
        getRestockSuggestions(),
      ]);
      setData(productsRes);
      setRestockSuggestions(restockRes);
    } catch (error) {
      console.error('Error fetching products:', error);
      setError('加载商品数据失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    load();
  }, [load]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'default';
      case 'inactive': return 'secondary';
      case 'out_of_stock': return 'destructive';
      default: return 'outline';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'active': return '在售';
      case 'inactive': return '下架';
      case 'out_of_stock': return '缺货';
      default: return status;
    }
  };

  const getUrgencyColor = (urgency: string) => {
    switch (urgency) {
      case 'urgent': return 'text-red-600 bg-red-100';
      case 'warning': return 'text-yellow-600 bg-yellow-100';
      case 'normal': return 'text-green-600 bg-green-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  const getUrgencyIcon = (urgency: string) => {
    switch (urgency) {
      case 'urgent': return '🔴';
      case 'warning': return '🟡';
      case 'normal': return '🟢';
      default: return '⚪';
    }
  };

  const getUrgencyText = (urgency: string) => {
    switch (urgency) {
      case 'urgent': return '紧急';
      case 'warning': return '警告';
      case 'normal': return '正常';
      default: return urgency;
    }
  };

  // Use low_stock_items as the main products data if products array is not available
  const products = data?.products || data?.low_stock_items || [];
  const filteredProducts = products.filter(product =>
    search === '' || product.name.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-10 bg-muted animate-pulse rounded"></div>
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
          <h1 className="text-3xl font-bold tracking-tight">商品管理</h1>
          <p className="text-muted-foreground">管理您的商品库存和价格信息</p>
        </div>
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <div className="text-red-500 text-4xl mb-4">⚠️</div>
            <h3 className="text-lg font-medium text-red-800 mb-2">数据加载失败</h3>
            <p className="text-red-600 mb-4">{error}</p>
            <Button onClick={() => load()} variant="destructive">
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
          <h1 className="text-3xl font-bold tracking-tight">📦 商品管理</h1>
          <p className="text-muted-foreground">管理您的商品库存和补货建议</p>
        </div>
        <Button>添加商品</Button>
      </div>

      {/* Tab 导航 */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-8">
          <button
            onClick={() => setActiveTab('inventory')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'inventory'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            库存管理
          </button>
          <button
            onClick={() => setActiveTab('restock')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'restock'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            补货建议
          </button>
        </nav>
      </div>

      {/* 库存管理 Tab */}
      {activeTab === 'inventory' && (
        <>
          {/* Summary Cards */}
          {data?.summary && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">商品总数</p>
                      <p className="text-2xl font-bold">{Number(data.summary.total_products).toLocaleString()}</p>
                    </div>
                    <div className="text-3xl opacity-80">📦</div>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">在售商品</p>
                      <p className="text-2xl font-bold">{Number(data.summary.active_products).toLocaleString()}</p>
                    </div>
                    <div className="text-3xl opacity-80">✅</div>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">停售商品</p>
                      <p className="text-2xl font-bold">{Number(data.summary.inactive_products).toLocaleString()}</p>
                    </div>
                    <div className="text-3xl opacity-80">❌</div>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">低库存商品</p>
                      <p className="text-2xl font-bold text-red-600">{Number(data.summary.low_stock_count).toLocaleString()}</p>
                    </div>
                    <div className="text-3xl opacity-80">⚠️</div>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

      <div className="flex flex-col sm:flex-row gap-4">
        <Input
          placeholder="搜索商品名称..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <div className="text-sm text-muted-foreground flex items-center">
          当前显示 {filteredProducts.length} 件商品
          {data?.summary && ` (共 ${Number(data.summary.total_products).toLocaleString()} 件)`}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>📦</span>
            商品列表
          </CardTitle>
        </CardHeader>
        <CardContent>
          {filteredProducts.length > 0 ? (
            <Table>
              <TableCaption>商品库存管理</TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead>商品名称</TableHead>
                  <TableHead>品类</TableHead>
                  <TableHead className="text-right">价格</TableHead>
                  <TableHead className="text-right">库存</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredProducts.map((product) => (
                  <TableRow key={product.product_id || product.id}>
                    <TableCell className="font-medium">{product.name}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{product.category}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-semibold">
                      ¥{Number(product.retail_price || product.price || 0).toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right">
                      <span className={Number(product.estimated_stock || product.inventory || 0) < 10 ? 'text-red-600 font-medium' : ''}>
                        {Number(product.estimated_stock || product.inventory || 0).toLocaleString()}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={getStatusColor(product.status || 'active')}>
                        {getStatusText(product.status || 'active')}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm">
                        编辑
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              暂无商品数据
            </div>
          )}
        </CardContent>
      </Card>

          {/* Pagination */}
          {data?.summary && Number(data.summary.total_products) > pageSize && (
            <div className="flex justify-center gap-2">
              <Button
                variant="outline"
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page === 1}
              >
                上一页
              </Button>
              <div className="flex items-center px-4 py-2 text-sm text-muted-foreground">
                第 {page} 页，共 {Math.ceil(Number(data.summary.total_products) / pageSize)} 页
              </div>
              <Button
                variant="outline"
                onClick={() => setPage(page + 1)}
                disabled={page >= Math.ceil(Number(data.summary.total_products) / pageSize)}
              >
                下一页
              </Button>
            </div>
          )}
        </>
      )}

      {/* 补货建议 Tab */}
      {activeTab === 'restock' && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <span>📦</span>
                补货建议
                <Badge variant="outline">{restockSuggestions.length} 个商品</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {restockSuggestions.length > 0 ? (
                <Table>
                  <TableCaption>基于销量和库存分析的智能补货建议</TableCaption>
                  <TableHeader>
                    <TableRow>
                      <TableHead>商品名称</TableHead>
                      <TableHead className="text-right">当前库存</TableHead>
                      <TableHead className="text-right">日均销量</TableHead>
                      <TableHead className="text-right">剩余天数</TableHead>
                      <TableHead className="text-right">建议补货量</TableHead>
                      <TableHead>紧急度</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {restockSuggestions.map((suggestion) => (
                      <TableRow key={suggestion.product_id}>
                        <TableCell className="font-medium">{suggestion.product_name}</TableCell>
                        <TableCell className="text-right">
                          <span className={Number(suggestion.current_stock) < 10 ? 'text-red-600 font-medium' : ''}>
                            {Number(suggestion.current_stock).toLocaleString()}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">
                          {Number(suggestion.daily_avg_sales).toFixed(1)}
                        </TableCell>
                        <TableCell className="text-right">
                          <span className={Number(suggestion.remaining_days) < 3 ? 'text-red-600 font-medium' : ''}>
                            {Number(suggestion.remaining_days)}天
                          </span>
                        </TableCell>
                        <TableCell className="text-right font-semibold text-blue-600">
                          {Number(suggestion.suggested_restock).toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="text-lg">{getUrgencyIcon(suggestion.urgency)}</span>
                            <Badge variant="outline" className={getUrgencyColor(suggestion.urgency)}>
                              {getUrgencyText(suggestion.urgency)}
                            </Badge>
                          </div>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="sm">
                            执行补货
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  暂无补货建议
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

export default withErrorBoundary(ProductsPage);
