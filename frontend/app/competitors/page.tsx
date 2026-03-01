'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getCompetitorOverview, getPriceComparison } from '@/lib/api';
import type { CompetitorOverview, PriceComparison } from '@/lib/api';

export default function CompetitorsPage() {
  const [overview, setOverview] = useState<CompetitorOverview | null>(null);
  const [priceComparison, setPriceComparison] = useState<PriceComparison[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [overviewData, priceData] = await Promise.all([
          getCompetitorOverview(),
          getPriceComparison(20),
        ]);
        setOverview(overviewData);
        setPriceComparison(priceData);
      } catch (error) {
        console.error('Error fetching competitor data:', error);
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">竞品监控</h1>
        <p className="text-muted-foreground">实时监控竞争对手价格和产品策略</p>
      </div>

      {/* Overview Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-muted-foreground">监控店铺</p>
                <p className="text-3xl font-bold text-blue-600">9</p>
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
                <p className="text-3xl font-bold text-green-600">78</p>
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
                <p className="text-3xl font-bold text-purple-600">62%</p>
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
                <p className="text-muted-foreground">{overview.summary}</p>
              </div>

              <div>
                <h4 className="font-medium mb-2">主要竞争品类</h4>
                <div className="flex flex-wrap gap-2">
                  {overview.top_categories.map((category, index) => (
                    <Badge key={index} variant="secondary">
                      {category}
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
                      ¥{item.our_price.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right">
                      ¥{item.competitor_price.toFixed(2)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{item.competitor_store}</Badge>
                    </TableCell>
                    <TableCell className={`text-right font-medium ${getPriceDiffColor(item.price_diff_pct)}`}>
                      {item.price_diff_pct.toFixed(1)}%
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={item.price_diff_pct <= 0 ? "default" : "secondary"}
                        className={item.price_diff_pct <= 0 ? "bg-green-100 text-green-800" : ""}
                      >
                        {getPriceDiffText(item.price_diff_pct)}
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
