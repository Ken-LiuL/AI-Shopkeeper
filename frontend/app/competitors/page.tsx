'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function CompetitorsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">竞品监控</h1>
        <p className="text-muted-foreground">
          当前阶段未启用。现有真实数据只有商品、订单、库存，不能支撑可信的竞品结论。
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardContent className="p-6">
            <p className="text-sm font-medium text-muted-foreground">当前状态</p>
            <p className="mt-2 text-3xl font-bold text-slate-900">未启用</p>
            <p className="mt-1 text-sm text-muted-foreground">不再用推导数据或演示数据冒充竞品能力。</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <p className="text-sm font-medium text-muted-foreground">缺的数据</p>
            <p className="mt-2 text-3xl font-bold text-slate-900">3 类</p>
            <p className="mt-1 text-sm text-muted-foreground">竞品店铺、竞品商品价格、竞品价格变化。</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <p className="text-sm font-medium text-muted-foreground">当前替代动作</p>
            <p className="mt-2 text-3xl font-bold text-slate-900">价格复核</p>
            <p className="mt-1 text-sm text-muted-foreground">先用销量、库存、成本和类目价格带复核本店价格。</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>为什么现在不做</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>没有真实竞品数据时，所谓“竞品均价”“竞品降价提醒”“竞争机会”都会变成猜测。</p>
          <p>这类能力一旦做假，比没有更伤客户信任。所以这一页先明确关闭，等有真实竞品导入后再重启。</p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">不使用演示竞品</Badge>
            <Badge variant="outline">不使用推导竞品</Badge>
            <Badge variant="outline">等待真实竞品导入</Badge>
          </div>
          <div className="flex flex-wrap gap-3 pt-2">
            <a href="/pricing">
              <Button>先做价格复核</Button>
            </a>
            <a href="/imports">
              <Button variant="outline">查看当前数据入口</Button>
            </a>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
