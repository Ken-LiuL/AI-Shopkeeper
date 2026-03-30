'use client';

import { withErrorBoundary } from '@/components/error-boundary';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

function ListingPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">智能上架</h1>
        <p className="text-muted-foreground">
          当前阶段不作为主能力推进。它依赖外部货源链接和平台解析，不是这批商品、订单、库存数据能支撑的日常经营动作。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>为什么现在收起</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            现阶段最重要的是把已导入的商品、订单、库存数据真正用起来，而不是把精力放在外部链接解析和上架流程上。
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border bg-slate-50 p-4">
              <div className="text-sm text-muted-foreground">现阶段状态</div>
              <div className="mt-1 text-lg font-semibold">暂停进入主流程</div>
            </div>
            <div className="rounded-lg border bg-slate-50 p-4">
              <div className="text-sm text-muted-foreground">为什么暂停</div>
              <div className="mt-1 text-lg font-semibold">不基于已导入经营数据</div>
            </div>
            <div className="rounded-lg border bg-slate-50 p-4">
              <div className="text-sm text-muted-foreground">当前更重要</div>
              <div className="mt-1 text-lg font-semibold">先补齐商品与知识</div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">先做商品主档完整性</Badge>
            <Badge variant="outline">先做知识补齐</Badge>
            <Badge variant="outline">先做库存与订单动作</Badge>
          </div>

          <div className="flex flex-wrap gap-3">
            <a href="/products">
              <Button>先去处理商品修复</Button>
            </a>
            <a href="/knowledge">
              <Button variant="outline">去补知识中心</Button>
            </a>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default withErrorBoundary(ListingPage);
