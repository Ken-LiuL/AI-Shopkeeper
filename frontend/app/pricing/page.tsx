'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  adoptPricingSuggestion,
  applyPricingSuggestions,
  batchUpdatePrices,
  getPricingRules,
  getPricingSuggestions,
  type BatchPriceUpdateRequest,
  type BatchPriceUpdateResult,
  type PricingRule,
  type PricingSuggestion,
} from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

function formatCurrency(amount: number) {
  return `¥${Number(amount || 0).toFixed(2)}`;
}

function getConfidenceLabel(confidence: number) {
  if (confidence >= 0.8) {
    return { text: '高', className: 'bg-green-100 text-green-700' };
  }
  if (confidence >= 0.6) {
    return { text: '中', className: 'bg-amber-100 text-amber-700' };
  }
  return { text: '低', className: 'bg-slate-100 text-slate-600' };
}

export default function PricingPage() {
  const [suggestions, setSuggestions] = useState<PricingSuggestion[]>([]);
  const [rules, setRules] = useState<PricingRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'suggestions' | 'rules'>('suggestions');
  const [adoptingIds, setAdoptingIds] = useState<Set<string>>(new Set());
  const [selectedSuggestions, setSelectedSuggestions] = useState<Set<string>>(new Set());
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [batchOperation, setBatchOperation] = useState<'multiply' | 'add' | 'set'>('multiply');
  const [batchValue, setBatchValue] = useState('');
  const [batchReason, setBatchReason] = useState('');
  const [batchProcessing, setBatchProcessing] = useState(false);

  // Apply suggestion state
  const [applyingIds, setApplyingIds] = useState<Set<string>>(new Set());
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set());
  const [showApplyConfirm, setShowApplyConfirm] = useState(false);
  const [pendingApplyItems, setPendingApplyItems] = useState<Array<{ product_id: string; new_price: number }>>([]);
  const [applyProcessing, setApplyProcessing] = useState(false);

  const summary = useMemo(() => {
    const highConfidence = suggestions.filter((item) => item.confidence >= 0.8).length;
    const raiseCount = suggestions.filter((item) => item.suggested_price > item.current_price).length;
    const cutCount = suggestions.filter((item) => item.suggested_price < item.current_price).length;
    return { highConfidence, raiseCount, cutCount };
  }, [suggestions]);

  useEffect(() => {
    void loadData();
  }, []);

  async function loadData() {
    try {
      setLoading(true);
      const [suggestionsData, rulesData] = await Promise.all([
        getPricingSuggestions(),
        getPricingRules(),
      ]);
      setSuggestions(suggestionsData);
      setRules(rulesData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }

  async function handleAdoptSuggestion(suggestionId: string) {
    try {
      setMessage(null);
      setAdoptingIds((prev) => new Set(prev).add(suggestionId));
      await adoptPricingSuggestion(suggestionId);
      setSuggestions((prev) =>
        prev.map((item) =>
          item.product_id === suggestionId ? { ...item, status: 'adopted' } : item,
        ),
      );
      setMessage('价格建议已标记为已采纳，可继续批量执行实际调价。');
    } catch (err) {
      setMessage(`操作失败：${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setAdoptingIds((prev) => {
        const next = new Set(prev);
        next.delete(suggestionId);
        return next;
      });
    }
  }

  function handleSelectSuggestion(suggestionId: string, checked: boolean) {
    setSelectedSuggestions((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(suggestionId);
      } else {
        next.delete(suggestionId);
      }
      return next;
    });
  }

  function handleSelectAll(checked: boolean) {
    if (checked) {
      setSelectedSuggestions(new Set(suggestions.map((item) => item.product_id)));
      return;
    }
    setSelectedSuggestions(new Set());
  }

  async function handleBatchUpdate() {
    if (selectedSuggestions.size === 0) {
      setMessage('请先选择要处理的商品。');
      return;
    }
    if (!batchValue || Number.isNaN(Number(batchValue))) {
      setMessage('请输入有效的调价值。');
      return;
    }

    setBatchProcessing(true);
    try {
      const request: BatchPriceUpdateRequest = {
        product_ids: Array.from(selectedSuggestions),
        operation: batchOperation,
        value: Number(batchValue),
        reason: batchReason || '价格复核批量执行',
      };

      const result: BatchPriceUpdateResult = await batchUpdatePrices(request);
      if (result.updated_count > 0) {
        setMessage(
          `批量调价完成，成功 ${result.updated_count} 个${
            result.failed_count > 0 ? `，失败 ${result.failed_count} 个` : ''
          }。`,
        );
        setSelectedSuggestions(new Set());
        setShowBatchModal(false);
        setBatchValue('');
        setBatchReason('');
        await loadData();
      } else {
        setMessage('批量调价失败，没有商品被成功更新。');
      }
    } catch (err) {
      setMessage(`批量调价失败：${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setBatchProcessing(false);
    }
  }

  function handleApplySingle(suggestion: PricingSuggestion) {
    setPendingApplyItems([{ product_id: suggestion.product_id, new_price: suggestion.suggested_price }]);
    setShowApplyConfirm(true);
  }

  function handleApplySelected() {
    if (selectedSuggestions.size === 0) {
      setMessage('请先选择要应用的商品。');
      return;
    }
    const items = suggestions
      .filter((s) => selectedSuggestions.has(s.product_id))
      .map((s) => ({ product_id: s.product_id, new_price: s.suggested_price }));
    setPendingApplyItems(items);
    setShowApplyConfirm(true);
  }

  async function handleConfirmApply() {
    if (pendingApplyItems.length === 0) return;
    setApplyProcessing(true);
    // Mark as applying
    const ids = new Set(pendingApplyItems.map((i) => i.product_id));
    setApplyingIds((prev) => new Set([...prev, ...ids]));
    try {
      const result = await applyPricingSuggestions(pendingApplyItems);
      if (result.updated_count > 0) {
        setAppliedIds((prev) => new Set([...prev, ...ids]));
        setMessage(
          `已成功应用 ${result.updated_count} 个商品的价格${result.failed_count > 0 ? `，${result.failed_count} 个失败` : ''}。`,
        );
        setSelectedSuggestions(new Set());
        await loadData();
      } else {
        setMessage('应用失败，没有商品价格被更新。');
      }
    } catch (err) {
      setMessage(`应用失败：${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setApplyingIds((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.delete(id));
        return next;
      });
      setApplyProcessing(false);
      setShowApplyConfirm(false);
      setPendingApplyItems([]);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">价格复核</h1>
          <p className="text-muted-foreground">只基于当前商品、订单和库存数据生成价格建议。</p>
        </div>
        <Card>
          <CardContent className="p-6">
            <div className="h-40 animate-pulse rounded bg-muted" />
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">价格复核</h1>
          <p className="text-muted-foreground">只基于当前商品、订单和库存数据生成价格建议。</p>
        </div>
        <Card className="border-red-200">
          <CardContent className="p-6 text-center">
            <p className="text-lg text-red-700">加载失败</p>
            <p className="mt-2 text-sm text-red-600">{error}</p>
            <Button className="mt-4" onClick={() => void loadData()}>重试</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">价格复核</h1>
        <p className="text-muted-foreground">
          当前只基于商品主档、订单销量、库存状态和类目价格带做判断，不使用竞品数据。
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-5">
            <div className="text-sm text-muted-foreground">待复核商品</div>
            <div className="mt-2 text-3xl font-bold">{suggestions.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="text-sm text-muted-foreground">高置信度建议</div>
            <div className="mt-2 text-3xl font-bold">{summary.highConfidence}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="text-sm text-muted-foreground">建议提价</div>
            <div className="mt-2 text-3xl font-bold">{summary.raiseCount}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="text-sm text-muted-foreground">建议降价</div>
            <div className="mt-2 text-3xl font-bold">{summary.cutCount}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-slate-200 bg-slate-50">
        <CardContent className="flex flex-col gap-3 p-5 text-sm text-slate-700 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="font-medium">数据边界</div>
            <div className="mt-1 text-slate-600">
              当前价格建议来自销量、库存、成本和类目价格带。没有竞品数据时，不给竞品结论。
            </div>
          </div>
          <a href="/imports">
            <Button variant="outline">查看当前数据入口</Button>
          </a>
        </CardContent>
      </Card>

      {message && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
          {message}
        </div>
      )}

      <div className="border-b border-gray-200">
        <nav className="flex space-x-8">
          <button
            onClick={() => setActiveTab('suggestions')}
            className={`border-b-2 px-1 py-2 text-sm font-medium ${
              activeTab === 'suggestions'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            }`}
          >
            价格建议
          </button>
          <button
            onClick={() => setActiveTab('rules')}
            className={`border-b-2 px-1 py-2 text-sm font-medium ${
              activeTab === 'rules'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            }`}
          >
            判断规则
          </button>
        </nav>
      </div>

      {activeTab === 'suggestions' && (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>价格建议清单</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                先复核高置信度建议，再决定是否批量执行。
              </p>
            </div>
            {selectedSuggestions.size > 0 && (
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setShowBatchModal(true)}>
                  批量调价 ({selectedSuggestions.size})
                </Button>
                <Button onClick={handleApplySelected}>
                  批量应用建议价 ({selectedSuggestions.size})
                </Button>
              </div>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {suggestions.length === 0 ? (
              <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                当前数据不足以产出价格建议。优先补齐成本价或更多订单数据。
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left">
                        <input
                          type="checkbox"
                          checked={selectedSuggestions.size === suggestions.length && suggestions.length > 0}
                          onChange={(e) => handleSelectAll(e.target.checked)}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        商品 / 建议
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        依据
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        置信度
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        预期影响
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        操作
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white">
                    {suggestions.map((suggestion) => {
                      const confidence = getConfidenceLabel(suggestion.confidence);
                      const diffPercent = suggestion.current_price > 0
                        ? Math.abs((suggestion.suggested_price - suggestion.current_price) / suggestion.current_price * 100)
                        : 0;

                      return (
                        <tr key={suggestion.product_id} className="hover:bg-gray-50">
                          <td className="px-4 py-4 align-top">
                            <input
                              type="checkbox"
                              checked={selectedSuggestions.has(suggestion.product_id)}
                              onChange={(e) => handleSelectSuggestion(suggestion.product_id, e.target.checked)}
                              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            />
                          </td>
                          <td className="px-6 py-4 align-top text-sm">
                            <div className="font-medium text-gray-900">{suggestion.product_name}</div>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                              <span className="rounded bg-slate-100 px-2 py-1 font-mono text-slate-600">
                                {formatCurrency(suggestion.current_price)}
                              </span>
                              <span className={suggestion.suggested_price > suggestion.current_price ? 'text-green-600' : 'text-red-600'}>
                                {suggestion.suggested_price > suggestion.current_price ? '↗' : '↘'}
                              </span>
                              <span
                                className={`rounded px-2 py-1 font-mono ${
                                  suggestion.suggested_price > suggestion.current_price
                                    ? 'bg-green-100 text-green-700'
                                    : 'bg-red-100 text-red-700'
                                }`}
                              >
                                {formatCurrency(suggestion.suggested_price)}
                              </span>
                              <span className="text-slate-500">({diffPercent.toFixed(1)}%)</span>
                            </div>
                          </td>
                          <td className="px-6 py-4 align-top text-sm text-gray-700">
                            {suggestion.reason}
                          </td>
                          <td className="px-6 py-4 align-top">
                            <span className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${confidence.className}`}>
                              {confidence.text}
                            </span>
                          </td>
                          <td className="px-6 py-4 align-top text-sm text-gray-700">
                            {suggestion.expected_impact || '需要结合执行结果继续观察'}
                          </td>
                          <td className="px-6 py-4 align-top text-sm">
                            <div className="flex flex-col gap-2">
                              {appliedIds.has(suggestion.product_id) ? (
                                <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-1 text-xs font-semibold text-green-700">
                                  ✓ 已应用
                                </span>
                              ) : (
                                <Button
                                  size="sm"
                                  disabled={applyingIds.has(suggestion.product_id)}
                                  onClick={() => handleApplySingle(suggestion)}
                                >
                                  {applyingIds.has(suggestion.product_id) ? '应用中...' : '应用'}
                                </Button>
                              )}
                              <Button
                                size="sm"
                                variant={suggestion.status === 'adopted' ? 'outline' : 'outline'}
                                disabled={adoptingIds.has(suggestion.product_id) || suggestion.status === 'adopted'}
                                onClick={() => void handleAdoptSuggestion(suggestion.product_id)}
                              >
                                {suggestion.status === 'adopted'
                                  ? '已采纳'
                                  : adoptingIds.has(suggestion.product_id)
                                    ? '处理中...'
                                    : '采纳'}
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {activeTab === 'rules' && (
        <Card>
          <CardHeader>
            <CardTitle>当前判断规则</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              这些规则只使用现有商品、订单和库存数据，不依赖竞品或外部市场数据。
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {rules.length === 0 ? (
              <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                暂无可用规则。
              </div>
            ) : (
              rules.map((rule) => (
                <div key={rule.rule_id} className="rounded-lg border p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="text-sm font-medium text-slate-900">{rule.name}</div>
                      <div className="mt-1 text-sm text-slate-600">{rule.description}</div>
                      <div className="mt-2 text-xs text-slate-400">优先级 {rule.priority}</div>
                    </div>
                    <span
                      className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${
                        rule.enabled ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {rule.enabled ? '启用中' : '未启用'}
                    </span>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      )}

      {showApplyConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 w-full max-w-sm rounded-lg bg-white">
            <div className="border-b border-gray-200 px-6 py-4">
              <h3 className="text-lg font-medium text-gray-900">确认应用价格</h3>
            </div>
            <div className="px-6 py-4 text-sm text-gray-700">
              确定要修改 <span className="font-bold text-gray-900">{pendingApplyItems.length}</span> 个商品的价格吗？此操作将立即更新商品实际售价。
            </div>
            <div className="flex justify-end gap-3 border-t border-gray-200 px-6 py-4">
              <Button
                variant="outline"
                disabled={applyProcessing}
                onClick={() => {
                  setShowApplyConfirm(false);
                  setPendingApplyItems([]);
                }}
              >
                取消
              </Button>
              <Button disabled={applyProcessing} onClick={() => void handleConfirmApply()}>
                {applyProcessing ? '应用中...' : '确认'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {showBatchModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 w-full max-w-md rounded-lg bg-white">
            <div className="border-b border-gray-200 px-6 py-4">
              <h3 className="text-lg font-medium text-gray-900">批量调价</h3>
              <p className="mt-1 text-sm text-gray-500">已选择 {selectedSuggestions.size} 个商品</p>
            </div>

            <div className="space-y-4 px-6 py-4">
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">调价方式</label>
                <select
                  value={batchOperation}
                  onChange={(e) => setBatchOperation(e.target.value as 'multiply' | 'add' | 'set')}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="multiply">按比例调价</option>
                  <option value="add">按数值调价</option>
                  <option value="set">设置固定价格</option>
                </select>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">
                  {batchOperation === 'multiply' ? '调价倍数' : batchOperation === 'add' ? '调价金额' : '新价格'}
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={batchValue}
                  onChange={(e) => setBatchValue(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">执行原因</label>
                <input
                  type="text"
                  value={batchReason}
                  onChange={(e) => setBatchReason(e.target.value)}
                  placeholder="例如：价格复核批量执行"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 border-t border-gray-200 px-6 py-4">
              <Button variant="outline" disabled={batchProcessing} onClick={() => setShowBatchModal(false)}>
                取消
              </Button>
              <Button disabled={batchProcessing || !batchValue} onClick={() => void handleBatchUpdate()}>
                {batchProcessing ? '处理中...' : '确认调价'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
