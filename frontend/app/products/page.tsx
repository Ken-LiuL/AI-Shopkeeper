'use client';
import { useEffect, useState, useCallback, useMemo } from 'react';
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
import { getManualImportReview, getProduct, getProducts, getRestockSuggestions, lookupIssueActions, updateIssueAction, updateProduct } from '@/lib/api';
import type { IssueActionRecord, ManualImportReview, Product, ProductDetail, ProductsResponse, RestockSuggestion } from '@/lib/api';

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

type ProductIssueType = 'product_catalog_gap' | 'product_missing_price';

type ProductEditorValues = {
  name: string;
  category: string;
  brand: string;
  retail_price: string;
  cost_price: string;
  stock: string;
  description: string;
};

function createEditorValues(product: Partial<ProductDetail> | Partial<Product>): ProductEditorValues {
  return {
    name: String(product.name || ''),
    category: String(product.category || ''),
    brand: String(product.brand || ''),
    retail_price: product.retail_price || product.price ? String(product.retail_price || product.price || '') : '',
    cost_price: product.cost_price ? String(product.cost_price) : '',
    stock: product.stock !== undefined
      ? String(product.stock)
      : product.estimated_stock !== undefined
        ? String(product.estimated_stock)
        : product.inventory !== undefined
          ? String(product.inventory)
          : '',
    description: String(('description' in product && product.description) || ''),
  };
}

function formatEditorMessage(variant: 'success' | 'error', text: string) {
  return { variant, text };
}

function ProductsPage() {
  const [data, setData] = useState<ProductsResponse | null>(null);
  const [restockSuggestions, setRestockSuggestions] = useState<RestockSuggestion[]>([]);
  const [review, setReview] = useState<ManualImportReview | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [issueView, setIssueView] = useState<'catalog_gaps' | 'missing_price' | null>(null);
  const [issueStatuses, setIssueStatuses] = useState<Record<string, IssueActionRecord>>({});
  const [savingIssueKey, setSavingIssueKey] = useState<string | null>(null);
  const [editorProductId, setEditorProductId] = useState<string | null>(null);
  const [editorIssue, setEditorIssue] = useState<{
    issueType: ProductIssueType | null;
    issueKey?: string;
    row?: Record<string, unknown>;
  } | null>(null);
  const [editorValues, setEditorValues] = useState<ProductEditorValues | null>(null);
  const [editorLoading, setEditorLoading] = useState(false);
  const [editorSaving, setEditorSaving] = useState(false);
  const [editorMessage, setEditorMessage] = useState<{ variant: 'success' | 'error'; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'inventory' | 'restock'>('inventory');
  const pageSize = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [productsRes, restockRes, reviewRes] = await Promise.all([
        getProducts(page, pageSize, search),
        getRestockSuggestions(),
        getManualImportReview(12),
      ]);
      setData(productsRes);
      setRestockSuggestions(restockRes);
      setReview(reviewRes);
    } catch (error) {
      console.error('Error fetching products:', error);
      setError('加载商品数据失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [search]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'default';
      case 'inactive': return 'secondary';
      case 'low_stock': return 'secondary';
      case 'out_of_stock': return 'destructive';
      default: return 'outline';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'active': return '在售';
      case 'inactive': return '下架';
      case 'low_stock': return '低库存';
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
  const products = data?.products || [];
  const filteredProducts = products;
  const stockoutButSelling = Number(review?.open_summary?.stockout_but_selling ?? review?.summary.stockout_but_selling ?? 0);
  const catalogGaps = Number(review?.open_summary?.catalog_gaps ?? review?.summary.catalog_gaps ?? 0);
  const missingPrice = Number(review?.open_summary?.products_missing_price ?? review?.summary.products_missing_price ?? 0);
  const lowStockCount = Number(data?.summary.low_stock_count || 0);
  const catalogGapRows = useMemo(
    () => ((review?.tables?.catalog_gaps as Array<Record<string, unknown>> | undefined) || []),
    [review]
  );
  const missingPriceRows = useMemo(
    () => (
      (review?.tables?.products_missing_price as Array<Record<string, unknown>> | undefined)
      || (review?.tables?.missing_price as Array<Record<string, unknown>> | undefined)
      || []
    ),
    [review]
  );
  const issueRows = useMemo(
    () => (issueView === 'catalog_gaps' ? catalogGapRows : issueView === 'missing_price' ? missingPriceRows : []),
    [issueView, catalogGapRows, missingPriceRows]
  );
  const issueTitle = issueView === 'catalog_gaps' ? '主档缺口商品' : '缺售价商品';
  const issueType = issueView === 'catalog_gaps' ? 'product_catalog_gap' : issueView === 'missing_price' ? 'product_missing_price' : null;
  const visibleIssueRows = issueRows.slice(0, 8);

  const applyUpdatedProduct = useCallback((updated: ProductDetail) => {
    setData((prev) => {
      if (!prev?.products) return prev;
      return {
        ...prev,
        products: prev.products.map((item) => (
          item.product_id === updated.product_id
            ? {
                ...item,
                ...updated,
                retail_price: updated.retail_price,
                price: updated.retail_price,
                cost_price: updated.cost_price,
                estimated_stock: updated.stock ?? updated.estimated_stock ?? 0,
                inventory: updated.stock ?? updated.estimated_stock ?? 0,
                category: updated.category,
                brand: updated.brand,
                name: updated.name,
                status: updated.status,
              }
            : item
        )),
      };
    });
  }, []);

  const removeIssueFromReview = useCallback((targetIssueType: ProductIssueType, issueKey: string) => {
    setReview((prev) => {
      if (!prev) return prev;
      const nextOpenSummary = {
        ...(prev.open_summary || prev.summary),
      };
      const summaryKey = targetIssueType === 'product_catalog_gap' ? 'catalog_gaps' : 'products_missing_price';
      nextOpenSummary[summaryKey] = Math.max(0, Number(nextOpenSummary[summaryKey] || 0) - 1);
      const filterByIssue = (row: Record<string, unknown>) => buildIssueKey(targetIssueType, row) !== issueKey;
      return {
        ...prev,
        open_summary: nextOpenSummary,
        tables: {
          ...prev.tables,
          catalog_gaps: ((prev.tables.catalog_gaps as Array<Record<string, unknown>> | undefined) || []).filter(filterByIssue),
          missing_price: ((prev.tables.missing_price as Array<Record<string, unknown>> | undefined) || []).filter(filterByIssue),
          products_missing_price: ((prev.tables.products_missing_price as Array<Record<string, unknown>> | undefined) || []).filter(filterByIssue),
        },
      };
    });
  }, []);

  useEffect(() => {
    const targetRows = issueRows.slice(0, 8);
    if (!issueType || targetRows.length === 0) return;
    const issues = targetRows.map((row) => ({
      issue_type: issueType,
      issue_key: buildIssueKey(issueType, row),
    }));
    lookupIssueActions(issues)
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
  }, [issueType, issueRows]);

  const handleIssueStatusChange = async (
    row: Record<string, unknown>,
    status: 'acknowledged' | 'resolved' | 'ignored'
  ) => {
    if (!issueType) return;
    const issueKey = buildIssueKey(issueType, row);
    setSavingIssueKey(issueKey);
    try {
      const result = await updateIssueAction({
        issue_type: issueType,
        issue_key: issueKey,
        title: issueTitle,
        status,
        metadata: row,
      });
      setIssueStatuses((prev) => ({
        ...prev,
        [`${result.issue_type}::${result.issue_key}`]: result,
      }));
      if (status === 'resolved' || status === 'ignored') {
        removeIssueFromReview(issueType, issueKey);
      }
    } finally {
      setSavingIssueKey(issueKey);
    }
  };

  const openProductEditor = useCallback(async (
    productId: string,
    context?: {
      issueType: ProductIssueType | null;
      issueKey?: string;
      row?: Record<string, unknown>;
    },
  ) => {
    if (!productId) {
      setEditorMessage(formatEditorMessage('error', '缺少商品 ID，暂时无法直接修复'));
      return;
    }
    setEditorProductId(productId);
    setEditorIssue(context || null);
    setEditorMessage(null);
    setEditorLoading(true);

    const fallback = data?.products?.find((item) => item.product_id === productId);
    if (fallback) {
      setEditorValues(createEditorValues(fallback));
    }

    try {
      const detail = await getProduct(productId);
      setEditorValues(createEditorValues(detail));
    } catch (err) {
      console.error('Error loading product detail:', err);
      setEditorMessage(formatEditorMessage('error', '加载商品详情失败，请稍后重试'));
    } finally {
      setEditorLoading(false);
    }
  }, [data?.products]);

  const closeEditor = useCallback(() => {
    setEditorProductId(null);
    setEditorIssue(null);
    setEditorValues(null);
    setEditorMessage(null);
    setEditorLoading(false);
  }, []);

  const handleEditorFieldChange = (field: keyof ProductEditorValues, value: string) => {
    setEditorValues((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const handleSaveEditor = async () => {
    if (!editorProductId || !editorValues) return;

    if (!editorValues.name.trim()) {
      setEditorMessage(formatEditorMessage('error', '商品名不能为空'));
      return;
    }
    if (editorIssue?.issueType === 'product_missing_price' && Number(editorValues.retail_price || 0) <= 0) {
      setEditorMessage(formatEditorMessage('error', '缺售价商品必须补齐有效零售价'));
      return;
    }
    if (
      Number(editorValues.retail_price || 0) < 0
      || Number(editorValues.cost_price || 0) < 0
      || Number(editorValues.stock || 0) < 0
    ) {
      setEditorMessage(formatEditorMessage('error', '价格和库存不能为负数'));
      return;
    }

    setEditorSaving(true);
    setEditorMessage(null);

    try {
      const payload = {
        name: editorValues.name.trim(),
        category: editorValues.category.trim() || null,
        brand: editorValues.brand.trim() || null,
        description: editorValues.description.trim() || null,
        retail_price: editorValues.retail_price.trim() ? Number(editorValues.retail_price) : null,
        cost_price: editorValues.cost_price.trim() ? Number(editorValues.cost_price) : null,
        stock: editorValues.stock.trim() ? Number(editorValues.stock) : null,
      };
      const updated = await updateProduct(editorProductId, payload);
      applyUpdatedProduct(updated);

      if (editorIssue?.issueType && editorIssue.issueKey) {
        const result = await updateIssueAction({
          issue_type: editorIssue.issueType,
          issue_key: editorIssue.issueKey,
          title: editorIssue.issueType === 'product_catalog_gap' ? '主档缺口商品' : '缺售价商品',
          status: 'resolved',
          metadata: editorIssue.row || {},
          notes: '在商品修复工作台内直接补齐',
        });
        setIssueStatuses((prev) => ({
          ...prev,
          [`${result.issue_type}::${result.issue_key}`]: result,
        }));
        removeIssueFromReview(editorIssue.issueType, editorIssue.issueKey);
      }

      setEditorValues(createEditorValues(updated));
      setEditorMessage(formatEditorMessage('success', editorIssue?.issueType
        ? '已保存并从待补齐清单移除'
        : '商品信息已保存'));
    } catch (err) {
      console.error('Error updating product:', err);
      setEditorMessage(formatEditorMessage('error', err instanceof Error ? err.message : '保存失败，请稍后重试'));
    } finally {
      setEditorSaving(false);
    }
  };

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
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight">📦 商品修复工作台</h1>
          <p className="text-muted-foreground">先补齐主档和价格缺口，再处理断货和补货动作，商品数据才足够支撑 AI。</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => window.open('/api/export/products')}
            className="inline-flex items-center rounded-md border border-input bg-background px-4 py-2 min-h-[44px] text-sm font-medium hover:bg-accent"
          >
            导出 Excel
          </button>
          <a href="/imports" className="inline-flex items-center rounded-md bg-primary px-4 py-2 min-h-[44px] text-sm font-medium text-primary-foreground hover:bg-primary/90">
            导入商品
          </a>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <a href="/inventory" className="block rounded-xl border border-red-200 bg-red-50 p-4 transition-colors hover:bg-red-100">
          <div className="text-xs text-red-700">断货但仍有销量</div>
          <div className="mt-1 text-3xl font-semibold text-red-900">{stockoutButSelling}</div>
          <div className="mt-2 text-xs text-red-700">优先核对库存并补货</div>
        </a>
        <button
          type="button"
          onClick={() => {
            setIssueView('catalog_gaps');
            setActiveTab('inventory');
          }}
          className="block rounded-xl border border-amber-200 bg-amber-50 p-4 text-left transition-colors hover:bg-amber-100"
        >
          <div className="text-xs text-amber-700">主档缺口</div>
          <div className="mt-1 text-3xl font-semibold text-amber-900">{catalogGaps}</div>
          <div className="mt-2 text-xs text-amber-700">这些商品只在订单或库存中出现</div>
        </button>
        <button
          type="button"
          onClick={() => {
            setIssueView('missing_price');
            setActiveTab('inventory');
          }}
          className="block rounded-xl border border-amber-200 bg-amber-50 p-4 text-left transition-colors hover:bg-amber-100"
        >
          <div className="text-xs text-amber-700">缺售价商品</div>
          <div className="mt-1 text-3xl font-semibold text-amber-900">{missingPrice}</div>
          <div className="mt-2 text-xs text-amber-700">不补齐会影响推荐、利润和客服</div>
        </button>
        <a href="/inventory" className="block rounded-xl border border-slate-200 bg-slate-50 p-4 transition-colors hover:bg-slate-100">
          <div className="text-xs text-slate-600">低库存商品</div>
          <div className="mt-1 text-3xl font-semibold text-slate-900">{lowStockCount}</div>
          <div className="mt-2 text-xs text-slate-600">优先查看补货动作</div>
        </a>
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
            主档与库存
          </button>
          <button
            onClick={() => setActiveTab('restock')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'restock'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            补货动作
          </button>
        </nav>
      </div>

      {/* 库存管理 Tab */}
      {activeTab === 'inventory' && (
        <>
          {(editorProductId || editorLoading) && (
            <Card className="border-blue-200 bg-blue-50/60">
              <CardHeader className="pb-3">
                <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                  <span>✍️</span>
                  商品修复编辑器
                  {editorIssue?.issueType === 'product_catalog_gap' ? <Badge variant="outline">补齐主档</Badge> : null}
                  {editorIssue?.issueType === 'product_missing_price' ? <Badge variant="outline">补齐售价</Badge> : null}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {editorMessage ? (
                  <div className={`rounded-lg px-3 py-2 text-sm ${
                    editorMessage.variant === 'success'
                      ? 'border border-emerald-200 bg-emerald-50 text-emerald-700'
                      : 'border border-red-200 bg-red-50 text-red-700'
                  }`}>
                    {editorMessage.text}
                  </div>
                ) : null}

                {editorLoading || !editorValues ? (
                  <div className="text-sm text-muted-foreground">正在加载商品详情...</div>
                ) : (
                  <>
                    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-slate-600">商品名</div>
                        <Input value={editorValues.name} onChange={(e) => handleEditorFieldChange('name', e.target.value)} />
                      </div>
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-slate-600">品类</div>
                        <Input value={editorValues.category} onChange={(e) => handleEditorFieldChange('category', e.target.value)} />
                      </div>
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-slate-600">品牌</div>
                        <Input value={editorValues.brand} onChange={(e) => handleEditorFieldChange('brand', e.target.value)} />
                      </div>
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-slate-600">库存</div>
                        <Input type="number" min="0" value={editorValues.stock} onChange={(e) => handleEditorFieldChange('stock', e.target.value)} />
                      </div>
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-slate-600">零售价</div>
                        <Input type="number" min="0" step="0.01" value={editorValues.retail_price} onChange={(e) => handleEditorFieldChange('retail_price', e.target.value)} />
                      </div>
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-slate-600">成本价</div>
                        <Input type="number" min="0" step="0.01" value={editorValues.cost_price} onChange={(e) => handleEditorFieldChange('cost_price', e.target.value)} />
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <div className="text-xs font-medium text-slate-600">主档说明</div>
                        <Input value={editorValues.description} onChange={(e) => handleEditorFieldChange('description', e.target.value)} placeholder="补充商品用途、规格或客服常用描述" />
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                      {editorIssue?.issueType === 'product_catalog_gap'
                        ? '保存后会同步补齐商品知识底座，后续客服和搜索会直接使用这份主档。'
                        : editorIssue?.issueType === 'product_missing_price'
                          ? '保存后价格复核、毛利判断和客服报价会直接使用新售价。'
                          : '这里适合做日常商品修正，保存后主档、价格和知识底座会一起更新。'}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={handleSaveEditor} disabled={editorSaving}>
                        {editorSaving ? '保存中...' : '保存修复'}
                      </Button>
                      <Button variant="outline" onClick={closeEditor} disabled={editorSaving}>
                        关闭编辑器
                      </Button>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          )}

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

      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">待补齐清单</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              variant={issueView === 'catalog_gaps' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setIssueView('catalog_gaps')}
            >
              主档缺口
            </Button>
            <Button
              variant={issueView === 'missing_price' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setIssueView('missing_price')}
            >
              缺售价
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setIssueView(null)}>
              清空
            </Button>
          </div>

          {issueView && issueRows.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    {Object.keys(issueRows[0]).slice(0, 4).map((key) => (
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
                    const issueKey = issueType ? buildIssueKey(issueType, row) : '';
                    const statusRecord = issueType ? issueStatuses[`${issueType}::${issueKey}`] : undefined;
                    return (
                    <tr key={`${issueTitle}-${index}`}>
                      {Object.keys(issueRows[0]).slice(0, 4).map((key) => (
                        <td key={`${issueTitle}-${index}-${key}`} className="px-4 py-3 text-slate-700">
                          {String(row[key] ?? '—')}
                        </td>
                      ))}
                      <td className="px-4 py-3 text-slate-700">
                        <Badge variant={statusRecord?.status === 'resolved' ? 'default' : 'outline'}>
                          {getIssueStatusText(statusRecord?.status)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            disabled={savingIssueKey === issueKey}
                            onClick={() => openProductEditor(String(row.product_id || ''), {
                              issueType,
                              issueKey,
                              row,
                            })}
                          >
                            编辑修复
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={savingIssueKey === issueKey}
                            onClick={() => handleIssueStatusChange(row, 'acknowledged')}
                          >
                            已知晓
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={savingIssueKey === issueKey}
                            onClick={() => handleIssueStatusChange(row, 'resolved')}
                          >
                            已修复
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={savingIssueKey === issueKey}
                            onClick={() => handleIssueStatusChange(row, 'ignored')}
                          >
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
          ) : issueView ? (
            <div className="text-sm text-muted-foreground">当前没有 {issueTitle} 待处理项。</div>
          ) : (
            <div className="text-sm text-muted-foreground">选择一种问题类型，直接在当前页面查看待补齐清单。</div>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col sm:flex-row gap-4">
        <Input
          placeholder="搜索商品名称..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <div className="text-sm text-muted-foreground flex items-center">
          当前显示 {filteredProducts.length} 件商品
          {typeof data?.total === 'number' && ` (筛选结果 ${Number(data.total).toLocaleString()} 件)`}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>🧾</span>
            商品主档与库存
          </CardTitle>
        </CardHeader>
        <CardContent>
          {filteredProducts.length > 0 ? (
            <div className="overflow-x-auto">
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
                      {Number(product.retail_price || product.price || 0) > 0
                        ? `¥${Number(product.retail_price || product.price || 0).toFixed(2)}`
                        : '待补齐'}
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
                      <div className="flex justify-end gap-3">
                        {(product.status === 'low_stock' || product.status === 'out_of_stock') ? (
                          <a href="/inventory" className="text-sm font-medium text-blue-600 hover:text-blue-700">
                            去补货
                          </a>
                        ) : null}
                        <button
                          type="button"
                          className="text-sm font-medium text-slate-700 hover:text-slate-900"
                          onClick={() => openProductEditor(product.product_id)}
                        >
                          编辑
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            </div>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              暂无商品数据
            </div>
          )}
        </CardContent>
      </Card>

          {/* Pagination */}
          {typeof data?.total === 'number' && data.total > pageSize && (
            <div className="flex justify-center gap-2">
              <Button
                variant="outline"
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page === 1}
              >
                上一页
              </Button>
              <div className="flex items-center px-4 py-2 text-sm text-muted-foreground">
                第 {page} 页，共 {Math.ceil(Number(data.total) / pageSize)} 页
              </div>
              <Button
                variant="outline"
                onClick={() => setPage(page + 1)}
                disabled={page >= Math.ceil(Number(data.total) / pageSize)}
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
                <span>⚡</span>
                补货动作
                <Badge variant="outline">{restockSuggestions.length} 个商品</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {restockSuggestions.length > 0 ? (
                <div className="overflow-x-auto">
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
                          <a href="/inventory" className="text-sm font-medium text-blue-600 hover:text-blue-700">
                            去处理
                          </a>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                </div>
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
