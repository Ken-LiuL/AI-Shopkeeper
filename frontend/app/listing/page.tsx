'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { withErrorBoundary } from '@/components/error-boundary';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL
  || (process.env.NODE_ENV === 'development' ? 'https://ai-shopkeeper-kk.fly.dev' : '');

type ListingPlatform = 'alibaba' | 'pdd';

interface ListingHistoryItem {
  listing_id?: string;
  source_url?: string;
  platform?: string;
  status?: string;
  created_at?: string;
  product_data?: Record<string, unknown>;
}

interface ParsedProduct {
  [key: string]: unknown;
}

function ListingPage() {
  const [productUrl, setProductUrl] = useState('');
  const [platform, setPlatform] = useState<ListingPlatform>('alibaba');

  const [parsedProduct, setParsedProduct] = useState<ParsedProduct | null>(null);
  const [parseLoading, setParseLoading] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createSuccess, setCreateSuccess] = useState<string | null>(null);

  const [history, setHistory] = useState<ListingHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    loadHistory();
    return () => stopHistoryPolling();
  }, []);

  const detectPlatform = (url: string): ListingPlatform => {
    const normalized = url.toLowerCase();
    if (normalized.includes('pinduoduo.com') || normalized.includes('yangkeduo.com')) return 'pdd';
    return 'alibaba';
  };

  const stopHistoryPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  };

  const startHistoryPolling = () => {
    stopHistoryPolling();
    pollIntervalRef.current = setInterval(async () => {
      const latest = await loadHistory();
      const hasProcessing = latest.some((item) => item.status === 'processing');
      if (!hasProcessing) stopHistoryPolling();
    }, 3000);
    pollTimeoutRef.current = setTimeout(() => {
      stopHistoryPolling();
    }, 60000);
  };

  const loadHistory = async (): Promise<ListingHistoryItem[]> => {
    try {
      setHistoryLoading(true);
      setHistoryError(null);
      const res = await fetch(`${BASE_URL}/api/listing`);
      const json = await res.json();
      if (!res.ok || json.success === false) {
        throw new Error(json.message || `HTTP ${res.status}`);
      }
      const list = Array.isArray(json.data) ? json.data : [];
      setHistory(list);
      return list;
    } catch (err) {
      console.error('Error loading listing history:', err);
      setHistoryError('加载上架历史失败，请稍后重试');
      return [];
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleParse = async () => {
    if (!productUrl.trim()) {
      setParseError('请输入商品链接');
      return;
    }

    const detected = detectPlatform(productUrl);
    setPlatform(detected);
    setParseLoading(true);
    setParseError(null);
    setCreateError(null);
    setCreateSuccess(null);
    try {
      const res = await fetch(`${BASE_URL}/api/listing/parse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: productUrl.trim(),
          platform: detected,
        }),
      });
      const json = await res.json();
      if (!res.ok || json.success === false) {
        throw new Error(json.message || `HTTP ${res.status}`);
      }
      setParsedProduct((json.data || {}) as ParsedProduct);
    } catch (err) {
      console.error('Parse listing failed:', err);
      setParseError('解析失败，请检查链接是否有效');
      setParsedProduct(null);
    } finally {
      setParseLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!parsedProduct) return;

    setCreateLoading(true);
    setCreateError(null);
    setCreateSuccess(null);
    try {
      const res = await fetch(`${BASE_URL}/api/listing/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_url: productUrl.trim(),
          platform,
          raw_product_data: JSON.stringify(parsedProduct),
        }),
      });
      const json = await res.json();
      if (!res.ok || json.success === false) {
        throw new Error(json.message || `HTTP ${res.status}`);
      }
      setCreateSuccess(`上架任务已创建（任务ID：${json.task_id || '已提交'}）`);
      const latest = await loadHistory();
      if (latest.some((item) => item.status === 'processing')) {
        startHistoryPolling();
      }
    } catch (err) {
      console.error('Create listing failed:', err);
      setCreateError('创建上架任务失败，请稍后重试');
    } finally {
      setCreateLoading(false);
    }
  };

  const parsedName = useMemo(() => {
    return String(
      parsedProduct?.title
      || parsedProduct?.name
      || parsedProduct?.product_name
      || parsedProduct?.item_title
      || '未识别商品名称'
    );
  }, [parsedProduct]);

  const parsedPrice = useMemo(() => {
    return String(
      parsedProduct?.price
      || parsedProduct?.current_price
      || parsedProduct?.min_price
      || parsedProduct?.max_price
      || '—'
    );
  }, [parsedProduct]);

  const parsedImages = useMemo(() => {
    const raw = parsedProduct?.images || parsedProduct?.image_urls || parsedProduct?.imgs || [];
    if (!Array.isArray(raw)) return [];
    return raw.filter((v) => typeof v === 'string') as string[];
  }, [parsedProduct]);

  const parsedSpecs = useMemo(() => {
    const raw = parsedProduct?.specs || parsedProduct?.specifications || parsedProduct?.sku_options;
    if (!raw || typeof raw !== 'object') return [];
    return Object.entries(raw as Record<string, unknown>);
  }, [parsedProduct]);

  const seoSuggestion = useMemo(() => {
    const ai = (parsedProduct?.ai_suggestion || parsedProduct?.ai_optimization || {}) as Record<string, unknown>;
    const title = String(ai.seo_title || ai.title || `${parsedName}｜智能优化标题`);
    const description = String(ai.seo_description || ai.description || `${parsedName}，支持快速发货，适配门店经营场景。`);
    return { title, description };
  }, [parsedName, parsedProduct]);

  const complianceText = useMemo(() => {
    const compliance = parsedProduct?.compliance || parsedProduct?.compliance_check || parsedProduct?.risk_check;
    if (!compliance) return '未返回明确校验结果，请人工复核后上架。';
    if (typeof compliance === 'string') return compliance;
    return JSON.stringify(compliance);
  }, [parsedProduct]);

  const getPlatformText = (v?: string) => {
    if (v === 'pdd') return '拼多多';
    if (v === 'alibaba') return '1688';
    return '—';
  };

  const getStatusBadge = (status?: string) => {
    switch (status) {
      case 'completed':
        return <Badge className="bg-green-100 text-green-700">已完成</Badge>;
      case 'processing':
        return <Badge className="bg-blue-100 text-blue-700">处理中</Badge>;
      case 'failed':
        return <Badge className="bg-red-100 text-red-700">失败</Badge>;
      default:
        return <Badge className="bg-gray-100 text-gray-600">{status || '未知'}</Badge>;
    }
  };

  const formatTime = (value?: string) => {
    if (!value) return '—';
    try {
      return new Date(value).toLocaleString('zh-CN');
    } catch {
      return value;
    }
  };

  const getHistoryName = (item: ListingHistoryItem) => {
    const data = item.product_data || {};
    const obj = data as Record<string, unknown>;
    return String(obj.title || obj.name || obj.product_name || item.source_url || '未命名商品');
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-3xl font-bold tracking-tight">📤 智能上架</CardTitle>
          <p className="text-muted-foreground">输入 1688 / 拼多多商品链接，自动解析并创建上架任务</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 md:flex-row">
            <Input
              placeholder="请输入商品链接（支持 1688 / 拼多多）"
              value={productUrl}
              onChange={(e) => setProductUrl(e.target.value)}
            />
            <Button onClick={handleParse} disabled={parseLoading}>
              {parseLoading ? '解析中...' : '解析商品'}
            </Button>
          </div>
          {parseError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {parseError}
            </div>
          )}
          {createError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {createError}
            </div>
          )}
          {createSuccess && (
            <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
              {createSuccess}
            </div>
          )}
        </CardContent>
      </Card>

      {parsedProduct && (
        <Card>
          <CardHeader>
            <CardTitle>解析结果</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-3">
                <div>
                  <p className="text-sm text-muted-foreground">商品名称</p>
                  <p className="font-medium">{parsedName}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">来源平台</p>
                  <p className="font-medium">{getPlatformText(platform)}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">价格</p>
                  <p className="font-medium">¥ {parsedPrice}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">规格</p>
                  {parsedSpecs.length > 0 ? (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {parsedSpecs.map(([key, value]) => (
                        <Badge key={key} variant="outline">{key}: {String(value)}</Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">暂无规格信息</p>
                  )}
                </div>
              </div>
              <div>
                <p className="text-sm text-muted-foreground mb-2">商品图片</p>
                {parsedImages.length > 0 ? (
                  <img
                    src={parsedImages[0]}
                    alt={parsedName}
                    className="h-44 w-full rounded-lg border object-cover"
                  />
                ) : (
                  <div className="h-44 w-full rounded-lg border bg-muted flex items-center justify-center text-sm text-muted-foreground">
                    暂无图片
                  </div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">AI 优化建议</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <p><span className="font-medium">SEO 标题：</span>{seoSuggestion.title}</p>
                  <p><span className="font-medium">描述建议：</span>{seoSuggestion.description}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">合规校验结果</CardTitle>
                </CardHeader>
                <CardContent className="text-sm">
                  {complianceText}
                </CardContent>
              </Card>
            </div>

            <div className="flex justify-end">
              <Button onClick={handleCreate} disabled={createLoading}>
                {createLoading ? '提交中...' : '确认上架'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>上架历史</CardTitle>
          <Button variant="outline" size="sm" onClick={loadHistory} disabled={historyLoading}>
            {historyLoading ? '刷新中...' : '刷新'}
          </Button>
        </CardHeader>
        <CardContent>
          {historyError && (
            <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {historyError}
            </div>
          )}
          <Table>
            <TableCaption>智能上架任务记录</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>商品名</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>创建时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.length > 0 ? history.map((item, idx) => (
                <TableRow key={item.listing_id || `${item.source_url || 'row'}-${idx}`}>
                  <TableCell className="max-w-[340px] truncate">{getHistoryName(item)}</TableCell>
                  <TableCell>{getPlatformText(item.platform)}</TableCell>
                  <TableCell>{getStatusBadge(item.status)}</TableCell>
                  <TableCell>{formatTime(item.created_at)}</TableCell>
                </TableRow>
              )) : (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                    暂无上架历史
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

export default withErrorBoundary(ListingPage);
