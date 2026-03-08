'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { LoadingSpinner } from '@/components/loading-spinner';

interface MedicalAnalysis {
  category_analysis: Array<{
    category: string;
    product_count: number;
    avg_price: number;
    main_device_type: string;
    recommended_margin: number;
    special_requirements: string[];
  }>;
  compliance_analysis: Array<{
    product_id: string;
    name: string;
    category: string;
    current_price: number;
    device_type: string;
    min_margin_percent: number;
    compliance_suggestions: string[];
    sales_suggestions: string[];
  }>;
  summary: {
    total_medical_categories: number;
    total_medical_products: number;
    avg_margin_requirement: number;
    device_type_distribution: {
      一类器械: number;
      二类器械: number;
      三类器械: number;
    };
  };
  recommendations: string[];
}

export function MedicalDevicePanel() {
  const [analysis, setAnalysis] = useState<MedicalAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchAnalysis = async () => {
      try {
        const response = await fetch('/api/pricing/medical-analysis');
        const result = await response.json();

        if (result.success) {
          setAnalysis(result.data);
        } else {
          setError(result.message || '加载失败');
        }
      } catch {
        setError('网络请求失败');
      } finally {
        setLoading(false);
      }
    };

    fetchAnalysis();
  }, []);

  const getDeviceTypeBadge = (type: string) => {
    const colors = {
      '一类器械': 'bg-green-100 text-green-800',
      '二类器械': 'bg-yellow-100 text-yellow-800',
      '三类器械': 'bg-red-100 text-red-800',
      '默认医疗': 'bg-gray-100 text-gray-800',
    };
    return colors[type as keyof typeof colors] || colors['默认医疗'];
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>🏥</span>
            医疗器械专业分析
          </CardTitle>
        </CardHeader>
        <CardContent>
          <LoadingSpinner text="正在加载医疗器械分析数据..." />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>🏥</span>
            医疗器械专业分析
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8">
            <p className="text-red-600 mb-4">❌ {error}</p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              重试
            </button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!analysis) return null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>🏥</span>
            医疗器械专业分析
            <Badge variant="outline">即时零售专业版</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">
                {analysis.summary.total_medical_categories}
              </div>
              <div className="text-sm text-gray-600">医疗品类</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">
                {analysis.summary.total_medical_products}
              </div>
              <div className="text-sm text-gray-600">医疗商品</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-orange-600">
                {analysis.summary.avg_margin_requirement}%
              </div>
              <div className="text-sm text-gray-600">建议毛利率</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-600">
                {Object.values(analysis.summary.device_type_distribution).reduce((a, b) => a + b, 0)}
              </div>
              <div className="text-sm text-gray-600">器械分类</div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* 品类分析 */}
            <div>
              <h4 className="text-lg font-semibold mb-4 flex items-center gap-2">
                📊 品类分析
              </h4>
              <div className="space-y-3 max-h-96 overflow-y-auto">
                {analysis.category_analysis.map((category, index) => (
                  <div key={index} className="border border-gray-200 rounded-lg p-4">
                    <div className="flex items-start justify-between mb-2">
                      <h5 className="font-medium text-sm">{category.category}</h5>
                      <Badge className={getDeviceTypeBadge(category.main_device_type)}>
                        {category.main_device_type}
                      </Badge>
                    </div>
                    <div className="text-sm text-gray-600 space-y-1">
                      <div>商品数量: {category.product_count}个</div>
                      <div>均价: ¥{category.avg_price.toFixed(2)}</div>
                      <div>建议毛利率: {category.recommended_margin}%</div>
                    </div>
                    {category.special_requirements.length > 0 && (
                      <div className="mt-2">
                        <div className="text-xs text-gray-500 mb-1">特殊要求:</div>
                        <ul className="text-xs text-gray-600 space-y-1">
                          {category.special_requirements.slice(0, 2).map((req, reqIndex) => (
                            <li key={reqIndex} className="flex items-start gap-1">
                              <span className="text-orange-500">•</span>
                              <span>{req}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* 合规分析 */}
            <div>
              <h4 className="text-lg font-semibold mb-4 flex items-center gap-2">
                ⚖️ 合规建议
              </h4>
              <div className="space-y-3 max-h-96 overflow-y-auto">
                {analysis.compliance_analysis.map((product, index) => (
                  <div key={index} className="border border-gray-200 rounded-lg p-4">
                    <div className="flex items-start justify-between mb-2">
                      <h5 className="font-medium text-sm">{product.name}</h5>
                      <Badge className={getDeviceTypeBadge(product.device_type)}>
                        {product.device_type}
                      </Badge>
                    </div>
                    <div className="text-sm text-gray-600 mb-3">
                      <div>当前价格: ¥{product.current_price}</div>
                      <div>建议毛利率: ≥{product.min_margin_percent}%</div>
                    </div>

                    {product.compliance_suggestions.length > 0 && (
                      <div className="mb-3">
                        <div className="text-xs font-medium text-blue-600 mb-1">合规要求:</div>
                        <ul className="text-xs text-gray-600 space-y-1">
                          {product.compliance_suggestions.slice(0, 2).map((suggestion, suggestionIndex) => (
                            <li key={suggestionIndex} className="flex items-start gap-1">
                              <span className="text-blue-500">•</span>
                              <span>{suggestion}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {product.sales_suggestions.length > 0 && (
                      <div>
                        <div className="text-xs font-medium text-green-600 mb-1">销售建议:</div>
                        <ul className="text-xs text-gray-600 space-y-1">
                          {product.sales_suggestions.slice(0, 2).map((suggestion, suggestionIndex) => (
                            <li key={suggestionIndex} className="flex items-start gap-1">
                              <span className="text-green-500">•</span>
                              <span>{suggestion}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 专业建议 */}
          <div className="mt-6 p-4 bg-blue-50 rounded-lg">
            <h5 className="font-semibold text-blue-900 mb-3 flex items-center gap-2">
              💡 医疗器械专业建议
            </h5>
            <ul className="space-y-2">
              {analysis.recommendations.map((rec, index) => (
                <li key={index} className="text-sm text-blue-800 flex items-start gap-2">
                  <span className="text-blue-600 mt-1">•</span>
                  <span>{rec}</span>
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
