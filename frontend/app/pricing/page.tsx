'use client';

import { useState, useEffect } from 'react';
import { getPricingSuggestions, getPricingRules, adoptPricingSuggestion, batchUpdatePrices, type PricingSuggestion, type PricingRule, type BatchPriceUpdateRequest, type BatchPriceUpdateResult } from '@/lib/api';


export default function PricingPage() {
  const [suggestions, setSuggestions] = useState<PricingSuggestion[]>([]);
  const [rules, setRules] = useState<PricingRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'suggestions' | 'rules'>('suggestions');
  const [adoptingIds, setAdoptingIds] = useState<Set<string>>(new Set());
  const [selectedSuggestions, setSelectedSuggestions] = useState<Set<string>>(new Set());
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [batchOperation, setBatchOperation] = useState<'multiply' | 'add' | 'set'>('multiply');
  const [batchValue, setBatchValue] = useState<string>('');
  const [batchReason, setBatchReason] = useState<string>('');
  const [batchProcessing, setBatchProcessing] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
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
  };

  const handleAdoptSuggestion = async (suggestionId: string) => {
    try {
      setAdoptingIds(prev => new Set([...prev, suggestionId]));
      await adoptPricingSuggestion(suggestionId);

      // 更新建议状态
      setSuggestions(prev =>
        prev.map(s =>
          s.product_id === suggestionId
            ? { ...s, status: 'adopted' as const }
            : s
        )
      );
    } catch (err) {
      alert('操作失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setAdoptingIds(prev => {
        const newSet = new Set(prev);
        newSet.delete(suggestionId);
        return newSet;
      });
    }
  };

  const handleSelectSuggestion = (suggestionId: string, checked: boolean) => {
    setSelectedSuggestions(prev => {
      const newSet = new Set(prev);
      if (checked) {
        newSet.add(suggestionId);
      } else {
        newSet.delete(suggestionId);
      }
      return newSet;
    });
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedSuggestions(new Set(suggestions.map(s => s.product_id)));
    } else {
      setSelectedSuggestions(new Set());
    }
  };

  const handleBatchUpdate = async () => {
    if (selectedSuggestions.size === 0) {
      alert('请选择要调价的商品');
      return;
    }

    if (!batchValue || isNaN(Number(batchValue))) {
      alert('请输入有效的数值');
      return;
    }

    setBatchProcessing(true);

    try {
      const request: BatchPriceUpdateRequest = {
        product_ids: Array.from(selectedSuggestions),
        operation: batchOperation,
        value: Number(batchValue),
        reason: batchReason || '批量调价操作'
      };

      const result: BatchPriceUpdateResult = await batchUpdatePrices(request);

      // 显示结果
      const successCount = result.updated_count;
      const failedCount = result.failed_count;

      if (successCount > 0) {
        alert(`批量调价完成！成功更新 ${successCount} 个商品${failedCount > 0 ? `，失败 ${failedCount} 个` : ''}。`);

        // 重新加载数据
        loadData();

        // 重置选择和对话框
        setSelectedSuggestions(new Set());
        setShowBatchModal(false);
        setBatchValue('');
        setBatchReason('');
      } else {
        alert(`批量调价失败！所有 ${failedCount} 个商品都更新失败。`);
      }

    } catch (err) {
      alert('批量调价失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setBatchProcessing(false);
    }
  };

  const formatCurrency = (amount: number) => {
    return `¥${Number(amount).toFixed(2)}`;
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return 'text-green-600 bg-green-100';
    if (confidence >= 0.6) return 'text-yellow-600 bg-yellow-100';
    return 'text-red-600 bg-red-100';
  };

  const getConfidenceLabel = (confidence: number) => {
    if (confidence >= 0.8) return '高';
    if (confidence >= 0.6) return '中';
    return '低';
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">💰 智能定价</h1>
          <div className="text-sm text-gray-500">
            AI驱动的定价优化建议
          </div>
        </div>

        {/* Loading skeleton */}
        <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <div className="animate-pulse">
              <div className="h-6 bg-gray-200 rounded w-1/4 mb-2"></div>
              <div className="h-4 bg-gray-200 rounded w-1/2"></div>
            </div>
          </div>
          <div className="p-6">
            <div className="animate-pulse space-y-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex space-x-4 items-center py-4 border-b border-gray-100">
                  <div className="w-4 h-4 bg-gray-200 rounded"></div>
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-gray-200 rounded w-3/4"></div>
                    <div className="h-3 bg-gray-200 rounded w-1/2"></div>
                  </div>
                  <div className="h-8 bg-gray-200 rounded w-16"></div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <p className="text-red-600 text-lg">❌ 加载失败</p>
          <p className="text-gray-600 mt-2">{error}</p>
          <button
            onClick={loadData}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">💰 智能定价</h1>
        <div className="text-sm text-gray-500">
          AI驱动的定价优化建议
        </div>
      </div>

      {/* Tab 导航 */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-8">
          <button
            onClick={() => setActiveTab('suggestions')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'suggestions'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            调价建议
          </button>
          <button
            onClick={() => setActiveTab('rules')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'rules'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            定价规则
          </button>
        </nav>
      </div>

      {activeTab === 'suggestions' && (
        <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-medium text-gray-900">调价建议</h3>
                <p className="text-sm text-gray-500 mt-1">
                  基于市场分析和销售数据生成的智能调价建议
                </p>
              </div>
              {selectedSuggestions.size > 0 && (
                <button
                  onClick={() => setShowBatchModal(true)}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
                >
                  批量调价 ({selectedSuggestions.size})
                </button>
              )}
            </div>
          </div>

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
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    商品名称
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    当前价格
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    建议价格
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    调整原因
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    置信度
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    预计影响
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {suggestions.map((suggestion) => (
                  <tr key={suggestion.product_id} className="hover:bg-gray-50">
                    <td className="px-4 py-4 whitespace-nowrap">
                      <input
                        type="checkbox"
                        checked={selectedSuggestions.has(suggestion.product_id)}
                        onChange={(e) => handleSelectSuggestion(suggestion.product_id, e.target.checked)}
                        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {suggestion.product_name}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {formatCurrency(suggestion.current_price)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <span className={`font-medium ${
                        suggestion.suggested_price > suggestion.current_price
                          ? 'text-green-600'
                          : 'text-red-600'
                      }`}>
                        {formatCurrency(suggestion.suggested_price)}
                      </span>
                      <span className="ml-2 text-xs text-gray-500">
                        {suggestion.suggested_price > suggestion.current_price ? '↗' : '↘'}
                        {Math.abs((suggestion.suggested_price - suggestion.current_price) / suggestion.current_price * 100).toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900 max-w-xs">
                      <div className="truncate" title={suggestion.reason}>
                        {suggestion.reason}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${getConfidenceColor(suggestion.confidence)}`}>
                        {getConfidenceLabel(suggestion.confidence)}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900 max-w-xs">
                      <div className="truncate" title={suggestion.expected_impact}>
                        {suggestion.expected_impact}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      {suggestion.status === 'adopted' ? (
                        <span className="text-green-600 font-medium">✅ 已采纳</span>
                      ) : (
                        <button
                          onClick={() => handleAdoptSuggestion(suggestion.product_id)}
                          disabled={adoptingIds.has(suggestion.product_id)}
                          className="bg-blue-600 text-white px-3 py-1 rounded-md text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {adoptingIds.has(suggestion.product_id) ? '处理中...' : '采纳'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {suggestions.length === 0 && (
            <div className="text-center py-12">
              <p className="text-gray-500">暂无调价建议</p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'rules' && (
        <div className="bg-white rounded-lg shadow-sm border">
          <div className="px-6 py-4 border-b border-gray-200">
            <h3 className="text-lg font-medium text-gray-900">定价规则设置</h3>
            <p className="text-sm text-gray-500 mt-1">
              配置智能定价的规则和策略
            </p>
          </div>

          <div className="p-6 space-y-4">
            {rules.map((rule) => (
              <div key={rule.rule_id} className="border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <h4 className="text-sm font-medium text-gray-900">{rule.name}</h4>
                    <p className="text-sm text-gray-500 mt-1">{rule.description}</p>
                    <div className="mt-2">
                      <span className="text-xs text-gray-400">优先级: {Number(rule.priority)}</span>
                    </div>
                  </div>
                  <div className="flex items-center">
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        className="sr-only peer"
                        checked={rule.enabled}
                        readOnly
                      />
                      <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                    </label>
                  </div>
                </div>
              </div>
            ))}

            {rules.length === 0 && (
              <div className="text-center py-8">
                <p className="text-gray-500">暂无定价规则</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 批量调价模态框 */}
      {showBatchModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="text-lg font-medium text-gray-900">批量调价</h3>
              <p className="text-sm text-gray-500 mt-1">
                已选择 {selectedSuggestions.size} 个商品
              </p>
            </div>

            <div className="px-6 py-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  调价方式
                </label>
                <select
                  value={batchOperation}
                  onChange={(e) => setBatchOperation(e.target.value as 'multiply' | 'add' | 'set')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="multiply">按比例调价 (乘以)</option>
                  <option value="add">按数值调价 (加/减)</option>
                  <option value="set">设置固定价格</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {batchOperation === 'multiply' ? '调价倍数' : batchOperation === 'add' ? '调价金额' : '新价格'}
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={batchValue}
                  onChange={(e) => setBatchValue(e.target.value)}
                  placeholder={
                    batchOperation === 'multiply' ? '如：1.1 表示涨价10%' :
                    batchOperation === 'add' ? '如：10 表示涨价10元，-5表示降价5元' :
                    '输入新的价格'
                  }
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  调价原因 (可选)
                </label>
                <input
                  type="text"
                  value={batchReason}
                  onChange={(e) => setBatchReason(e.target.value)}
                  placeholder="如：市场竞争调整、促销活动等"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div className="px-6 py-4 border-t border-gray-200 flex gap-3 justify-end">
              <button
                onClick={() => setShowBatchModal(false)}
                disabled={batchProcessing}
                className="px-4 py-2 text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={handleBatchUpdate}
                disabled={batchProcessing || !batchValue}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {batchProcessing ? '处理中...' : '确认调价'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
