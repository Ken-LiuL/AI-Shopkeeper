'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AICapabilityHeader } from '@/components/ai-capability-badge';

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getCompetitorOverview, getPriceComparison, getCompetitorPriceChanges } from '@/lib/api';
import type { CompetitorOverview, PriceComparison, CompetitorPriceChange } from '@/lib/api';

export default function CompetitorsPage() {
  const [overview, setOverview] = useState<CompetitorOverview | null>(null);
  const [priceComparison, setPriceComparison] = useState<PriceComparison[]>([]);
  const [priceChanges, setPriceChanges] = useState<CompetitorPriceChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const [overviewData, priceData, changesData] = await Promise.all([
          getCompetitorOverview(),
          getPriceComparison(20),
          getCompetitorPriceChanges(30),
        ]);
        setOverview(overviewData);
        setPriceComparison(priceData);
        setPriceChanges(changesData);
      } catch (error) {
        console.error('Error fetching competitor data:', error);
        setError('加载竞品数据失败，请稍后重试');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  const getPriceDiffColor = (diff: number) => {
    if (diff > 10) return 'text-red-600'; // We're much more expensive
    if (diff > 0) return 'text-orange-600'; // We're more expensive
    if (diff < -10) return 'text-green-600'; // We're much cheaper
    if (diff < 0) return 'text-blue-600'; // We're cheaper
    return 'text-gray-600'; // Similar price
  };

  const getPriceDiffText = (diff: number) => {
    if (Math.abs(diff) < 0.1) return '价格相当';
    return diff > 0 ? `我们贵 ${diff.toFixed(1)}%` : `我们便宜 ${Math.abs(diff).toFixed(1)}%`;
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">🔍 竞品监控</h1>
          <p className="text-muted-foreground">自动追踪竞品价格和活动变化，AI 分析影响并推荐应对策略</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {[1, 2].map((i) => (
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
        <div>
          <h1 className="text-3xl font-bold tracking-tight">🔍 竞品监控</h1>
          <p className="text-muted-foreground">自动追踪竞品价格和活动变化，AI 分析影响并推荐应对策略</p>
        </div>
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <div className="text-red-500 text-4xl mb-4">⚠️</div>
            <h3 className="text-lg font-medium text-red-800 mb-2">数据加载失败</h3>
            <p className="text-red-600 mb-4">{error}</p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600"
            >
              重新加载
            </button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">🔍 竞品监控</h1>
        <AICapabilityHeader
          capabilities={['实时监控', '价格追踪', 'AI 分析']}
          description="自动追踪竞品价格和活动变化，AI 分析影响并推荐应对策略"
        />
      </div>

      {/* Overview Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">监控店铺</p>
                <p className="text-3xl font-bold text-blue-600">{Number(overview?.summary.total_stores || 0).toLocaleString()}</p>
                <p className="text-sm text-muted-foreground mt-1">个竞争对手</p>
              </div>
              <div className="text-4xl">🏪</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">监控商品</p>
                <p className="text-3xl font-bold text-green-600">{Number(overview?.summary.total_products || 0).toLocaleString()}</p>
                <p className="text-sm text-muted-foreground mt-1">个产品</p>
              </div>
              <div className="text-4xl">📦</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">价格优势</p>
                <p className="text-3xl font-bold text-purple-600">
                  {priceComparison.length > 0 ?
                    Math.round((priceComparison.filter(item => Number(item.price_diff_pct || 0) <= 0).length / priceComparison.length) * 100) : 0}%
                </p>
                <p className="text-sm text-muted-foreground mt-1">商品更有优势</p>
              </div>
              <div className="text-4xl">💰</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Overview Summary */}
      {overview && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>📊</span>
              竞争分析概况
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div>
                <h4 className="font-medium mb-2">总体情况</h4>
                <p className="text-muted-foreground">
                  监控 {Number(overview.summary.total_stores)} 家竞品店铺，{Number(overview.summary.total_products)} 个商品，{Number(overview.summary.total_keywords)} 个品类。
                  平均商品价格 ¥{Number(overview.summary.avg_product_price).toFixed(2)}。
                </p>
              </div>

              <div>
                <h4 className="font-medium mb-2">主要竞争品类</h4>
                <div className="flex flex-wrap gap-2">
                  {overview.top_categories.map((cat, index) => (
                    <Badge key={index} variant="secondary">
                      {cat.category} ({Number(cat.product_count)} 个商品, 均价¥{Number(cat.avg_price).toFixed(0)})
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Price Comparison Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>🏷️</span>
            价格对比分析
          </CardTitle>
        </CardHeader>
        <CardContent>
          {priceComparison.length > 0 ? (
            <Table>
              <TableCaption>与竞争对手的价格对比</TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead>商品名称</TableHead>
                  <TableHead className="text-right">我们的价格</TableHead>
                  <TableHead className="text-right">竞争对手价格</TableHead>
                  <TableHead>竞争对手店铺</TableHead>
                  <TableHead className="text-right">价格差异</TableHead>
                  <TableHead>竞争优势</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {priceComparison.map((item, index) => (
                  <TableRow key={index}>
                    <TableCell className="font-medium">{item.name}</TableCell>
                    <TableCell className="text-right font-semibold">
                      ¥{Number(item.our_price).toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right">
                      ¥{Number(item.competitor_price).toFixed(2)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{item.competitor_store}</Badge>
                    </TableCell>
                    <TableCell className={`text-right font-medium ${getPriceDiffColor(Number(item.price_diff_pct))}`}>
                      {Number(item.price_diff_pct).toFixed(1)}%
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={Number(item.price_diff_pct) <= 0 ? "default" : "secondary"}
                        className={Number(item.price_diff_pct) <= 0 ? "bg-green-100 text-green-800" : ""}
                      >
                        {getPriceDiffText(Number(item.price_diff_pct))}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              暂无价格对比数据
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>📉</span>
            竞品价格变动
          </CardTitle>
        </CardHeader>
        <CardContent>
          {priceChanges.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>商品</TableHead>
                  <TableHead>竞品</TableHead>
                  <TableHead className="text-right">原价</TableHead>
                  <TableHead className="text-right">现价</TableHead>
                  <TableHead className="text-right">变动</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {priceChanges.map((item, index) => (
                  <TableRow key={`${item.product_id}-${index}`}>
                    <TableCell className="font-medium">{item.product_name}</TableCell>
                    <TableCell>{item.competitor_name}</TableCell>
                    <TableCell className="text-right">¥{Number(item.old_price).toFixed(2)}</TableCell>
                    <TableCell className="text-right">¥{Number(item.new_price).toFixed(2)}</TableCell>
                    <TableCell className={`text-right font-medium ${Number(item.change_pct) >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                      {Number(item.change_pct) >= 0 ? '+' : ''}{Number(item.change_pct).toFixed(2)}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              暂无竞品价格变动数据
            </div>
          )}
        </CardContent>
      </Card>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="cursor-pointer hover:shadow-md transition-shadow">
          <CardContent className="p-4 text-center">
            <div className="text-2xl mb-2">🔄</div>
            <div className="text-sm font-medium">刷新监控数据</div>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md transition-shadow">
          <CardContent className="p-4 text-center">
            <div className="text-2xl mb-2">📈</div>
            <div className="text-sm font-medium">价格趋势分析</div>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md transition-shadow">
          <CardContent className="p-4 text-center">
            <div className="text-2xl mb-2">🎯</div>
            <div className="text-sm font-medium">竞价策略建议</div>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md transition-shadow">
          <CardContent className="p-4 text-center">
            <div className="text-2xl mb-2">📱</div>
            <div className="text-sm font-medium">设置价格预警</div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
