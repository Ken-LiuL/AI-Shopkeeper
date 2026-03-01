'use client';

import { useState, useEffect } from 'react';
import { getPricingSuggestions, getPricingRules, adoptPricingSuggestion, type PricingSuggestion, type PricingRule } from '@/lib/api';

export default function PricingPage() {
  const [suggestions, setSuggestions] = useState<PricingSuggestion[]>([]);
  const [rules, setRules] = useState<PricingRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'suggestions' | 'rules'>('suggestions');
  const [adoptingIds, setAdoptingIds] = useState<Set<string>>(new Set());

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
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">加载中...</p>
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
            <h3 className="text-lg font-medium text-gray-900">调价建议</h3>
            <p className="text-sm text-gray-500 mt-1">
              基于市场分析和销售数据生成的智能调价建议
            </p>
          </div>
          
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
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
    </div>
  );
}