'use client';

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getInventoryList, type InventoryListItem } from '@/lib/api';

export default function InventoryPage() {
  const [items, setItems] = useState<InventoryListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const data = await getInventoryList(200);
        setItems(data);
      } catch (err: unknown) {
        setError((err as Error).message || '加载库存失败');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const renderBadge = (item: InventoryListItem) => {
    if (item.stock === 0) {
      return <Badge variant="destructive">断货</Badge>;
    }
    if (item.stock < 10) {
      return <Badge className="bg-amber-100 text-amber-800">低库存</Badge>;
    }
    return <Badge variant="outline">正常</Badge>;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">库存管理</h1>
        <p className="text-muted-foreground">按库存升序显示，优先处理低库存与断货商品</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>库存列表</CardTitle>
        </CardHeader>
        <CardContent>
          {loading && <div className="text-sm text-muted-foreground">加载中...</div>}
          {error && <div className="text-sm text-red-600">{error}</div>}
          {!loading && !error && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>商品名</TableHead>
                  <TableHead className="text-right">当前库存</TableHead>
                  <TableHead>状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow
                    key={`${item.source}-${item.product_id}-${item.name}`}
                    className={item.stock === 0 ? 'bg-red-50' : item.stock < 10 ? 'bg-amber-50' : ''}
                  >
                    <TableCell className="font-medium">{item.name}</TableCell>
                    <TableCell className="text-right">{item.stock}</TableCell>
                    <TableCell>{renderBadge(item)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
