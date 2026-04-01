'use client';

import { useState, useCallback, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { fetchAPI } from '@/lib/api';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ListingCreateResponse {
  task_id: string;
  message?: string;
}

interface ListingStatusResponse {
  listing_id: string;
  status: 'processing' | 'completed' | 'failed';
  current_step?: string;
  step_detail?: string;
}

interface ListingDetailResponse {
  listing_id: string;
  status: 'processing' | 'completed' | 'failed';
  parsed_product?: ParsedProduct;
  matched_standard?: MatchedStandard | null;
  match_confidence?: number;
  listing_info?: ListingInfo;
  compliance_check?: ComplianceCheck;
  errors?: string[];
  current_step?: string;
  step_detail?: string;
  created_at?: string;
  finished_at?: string;
}

interface ParsedProduct {
  title?: string;
  cleaned_title?: string;
  brand?: string;
  category?: string;
  barcode?: string;
  specs?: Record<string, string>;
  // 医疗器械
  registration_number?: string;
  device_class?: string;
  scope?: string;
  [key: string]: unknown;
}

interface MatchedStandard {
  name?: string;
  standard_id?: string;
  id?: string;
  reason?: string;
  [key: string]: unknown;
}

interface ListingInfo {
  title?: string;
  price?: number | string;
  price_analysis?: string;
  selling_points?: string[];
  seo_keywords?: string[];
  description?: string;
  [key: string]: unknown;
}

interface ComplianceIssue {
  severity: 'fatal' | 'error' | 'warning' | 'info';
  message: string;
  field?: string;
}

interface ComplianceCheck {
  can_list?: boolean;
  issues?: ComplianceIssue[];
  [key: string]: unknown;
}

// ─── Step constants ───────────────────────────────────────────────────────────

type Step = 'input' | 'loading' | 'result';

const PIPELINE_STEPS = [
  { label: '解析商品信息', icon: '🔍' },
  { label: '匹配美团标品', icon: '🔗' },
  { label: '生成上架信息', icon: '✍️' },
  { label: '合规校验', icon: '✅' },
];

/** Map backend current_step value → pipeline step index (0-based) */
const STEP_MAP: Record<string, number> = {
  parsing: 0,
  matching: 1,
  filling: 2,
  compliance: 3,
};

// ─── Color helpers ────────────────────────────────────────────────────────────

function confidenceColor(conf: number) {
  if (conf >= 0.8) return 'text-green-600 bg-green-50 border-green-200';
  if (conf >= 0.5) return 'text-amber-600 bg-amber-50 border-amber-200';
  return 'text-red-600 bg-red-50 border-red-200';
}

function confidenceLabel(conf: number) {
  if (conf >= 0.8) return '高置信度';
  if (conf >= 0.5) return '中置信度';
  return '低置信度';
}

function severityColor(sev: string) {
  switch (sev) {
    case 'fatal': return 'bg-red-100 text-red-700 border-red-200';
    case 'error': return 'bg-orange-100 text-orange-700 border-orange-200';
    case 'warning': return 'bg-yellow-100 text-yellow-700 border-yellow-200';
    case 'info': return 'bg-blue-100 text-blue-700 border-blue-200';
    default: return 'bg-gray-100 text-gray-700';
  }
}

function severityLabel(sev: string) {
  switch (sev) {
    case 'fatal': return '致命';
    case 'error': return '错误';
    case 'warning': return '警告';
    case 'info': return '提示';
    default: return sev;
  }
}

const SEVERITY_ORDER = { fatal: 0, error: 1, warning: 2, info: 3 };

// ─── Component ───────────────────────────────────────────────────────────────

function ListingPage() {
  const [step, setStep] = useState<Step>('input');
  const [rawText, setRawText] = useState('');
  const [platform, setPlatform] = useState<'alibaba' | 'pdd'>('alibaba');
  const [pipelineStep, setPipelineStep] = useState(0);
  const [result, setResult] = useState<ListingDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Editable listing info
  const [editTitle, setEditTitle] = useState('');
  const [editPrice, setEditPrice] = useState('');
  const [editPoints, setEditPoints] = useState('');
  const [editKeywords, setEditKeywords] = useState('');
  const [editDesc, setEditDesc] = useState('');

  const initEditFields = useCallback((info: ListingInfo) => {
    setEditTitle(info.title || '');
    setEditPrice(String(info.price || ''));
    setEditPoints((info.selling_points || []).join('\n'));
    setEditKeywords((info.seo_keywords || []).join('、'));
    setEditDesc(info.description || '');
  }, []);

  /**
   * Poll backend status endpoint every 2s.
   * Uses current_step to drive the progress indicator.
   * When status === 'completed' | 'failed', fetches full detail and transitions to result.
   */
  const pollPipeline = useCallback((taskId: string) => {
    const poll = async () => {
      try {
        const statusData = await fetchAPI<ListingStatusResponse>(`/listing/${taskId}/status`);

        // Update pipeline step indicator based on current_step
        if (statusData.current_step && statusData.current_step in STEP_MAP) {
          setPipelineStep(STEP_MAP[statusData.current_step]);
        }

        if (statusData.status === 'completed' || statusData.status === 'failed') {
          // Fetch full detail
          const detail = await fetchAPI<ListingDetailResponse>(`/listing/${taskId}`);
          setResult(detail);
          if (detail.listing_info) {
            initEditFields(detail.listing_info);
          }
          setStep('result');
        } else {
          pollTimerRef.current = setTimeout(poll, 2000);
        }
      } catch {
        // Retry on error
        pollTimerRef.current = setTimeout(poll, 3000);
      }
    };

    setPipelineStep(0);
    // Start polling after a short delay to let backend spin up
    pollTimerRef.current = setTimeout(poll, 2000);
  }, [initEditFields]);

  const handleSubmit = useCallback(async () => {
    if (!rawText.trim()) return;
    setError(null);
    setStep('loading');
    try {
      const res = await fetchAPI<ListingCreateResponse>('/listing/create', {
        method: 'POST',
        body: JSON.stringify({
          source_url: '',
          platform,
          raw_product_data: rawText,
        }),
      });
      const taskId = res.task_id;
      pollPipeline(taskId);
    } catch (e) {
      setError((e as Error).message || '请求失败，请重试');
      setStep('input');
    }
  }, [rawText, platform, pollPipeline]);

  const handleReset = () => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    setStep('input');
    setResult(null);
    setError(null);
    setActionMessage(null);
    setPipelineStep(0);
  };

  const handleCopyListingPlan = useCallback(async () => {
    if (!result) return;

    const plan = [
      `标题：${editTitle || result.listing_info?.title || '—'}`,
      `建议售价：${editPrice || result.listing_info?.price || '—'}`,
      '',
      '卖点：',
      editPoints || '—',
      '',
      'SEO 关键词：',
      editKeywords || '—',
      '',
      '商品描述：',
      editDesc || '—',
    ].join('\n');

    try {
      await navigator.clipboard.writeText(plan);
      setActionMessage('上架方案已复制，可直接粘贴到美团后台。');
    } catch {
      setActionMessage('复制失败，请手动复制页面中的上架方案。');
    }
  }, [editDesc, editKeywords, editPoints, editPrice, editTitle, result]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">📤 智能上架</h1>
        <p className="mt-1 text-sm text-gray-500">
          粘贴 1688 或拼多多商品信息，AI 自动解析并生成美团上架方案
        </p>
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          ⚠️ {error}
        </div>
      )}

      {actionMessage && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          ✅ {actionMessage}
        </div>
      )}

      {/* ── Step 1: 输入 ─────────────────────────────────────────────── */}
      {step === 'input' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">商品信息输入</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Chrome 扩展提示 */}
            <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2 text-xs text-blue-600 leading-relaxed">
              💡 提示：安装 AI店长 Chrome 扩展后，可在 1688/拼多多商品页一键导入，无需手动粘贴。
            </div>

            <p className="text-sm text-gray-500">
              将 1688 或拼多多商品页面的信息复制粘贴到这里，AI 会自动解析并生成美团上架信息
            </p>

            {/* 平台选择 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">来源平台</label>
              <div className="flex gap-3">
                {[
                  { value: 'alibaba', label: '1688' },
                  { value: 'pdd', label: '拼多多' },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setPlatform(opt.value as 'alibaba' | 'pdd')}
                    className={`px-4 py-2 rounded-lg border text-sm font-medium transition-colors ${
                      platform === opt.value
                        ? 'bg-blue-50 border-blue-300 text-blue-700'
                        : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 文本输入 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">商品信息</label>
              <textarea
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                placeholder="将商品标题、价格、规格参数、图片链接等信息粘贴在这里..."
                rows={10}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-transparent resize-y"
              />
              <p className="mt-1 text-xs text-gray-400">已输入 {rawText.length} 字符</p>
            </div>

            <Button
              onClick={handleSubmit}
              disabled={!rawText.trim()}
              className="w-full sm:w-auto"
            >
              🚀 开始解析
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ── Step 2: AI 处理中 ─────────────────────────────────────────── */}
      {step === 'loading' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">AI 处理中...</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4 py-2">
              {PIPELINE_STEPS.map((s, i) => {
                const isDone = i < pipelineStep;
                const isActive = i === pipelineStep;
                return (
                  <div
                    key={i}
                    className={`flex items-center gap-4 p-4 rounded-xl border transition-all duration-500 ${
                      isDone
                        ? 'border-green-200 bg-green-50'
                        : isActive
                        ? 'border-blue-200 bg-blue-50 shadow-sm'
                        : 'border-gray-100 bg-gray-50 opacity-40'
                    }`}
                  >
                    <div className={`text-2xl transition-all ${isActive ? 'animate-pulse' : ''}`}>
                      {isDone ? '✅' : s.icon}
                    </div>
                    <div className="flex-1">
                      <div className={`text-sm font-medium ${isDone ? 'text-green-700' : isActive ? 'text-blue-700' : 'text-gray-400'}`}>
                        {s.label}
                      </div>
                      {isActive && (
                        <div className="mt-1 text-xs text-blue-500">处理中...</div>
                      )}
                      {isDone && (
                        <div className="mt-1 text-xs text-green-600">已完成</div>
                      )}
                    </div>
                    {isActive && (
                      <div className="flex gap-1">
                        {[0, 1, 2].map((dot) => (
                          <div
                            key={dot}
                            className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce"
                            style={{ animationDelay: `${dot * 0.15}s` }}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Progress bar */}
            <div className="mt-6">
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>进度</span>
                <span>{Math.round((pipelineStep / PIPELINE_STEPS.length) * 100)}%</span>
              </div>
              <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-400 rounded-full transition-all duration-700"
                  style={{ width: `${(pipelineStep / PIPELINE_STEPS.length) * 100}%` }}
                />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Step 3: 结果展示 ──────────────────────────────────────────── */}
      {step === 'result' && result && (
        <div className="space-y-4">
          {/* 失败状态 */}
          {result.status === 'failed' && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4">
              <p className="text-sm font-medium text-red-700">❌ 解析失败</p>
              {(result.errors || []).map((e, i) => (
                <p key={i} className="text-xs text-red-600 mt-1">{e}</p>
              ))}
            </div>
          )}

          {/* ① 商品解析结果 */}
          {result.parsed_product && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <span>🔍</span> 商品解析结果
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ParsedProductCard data={result.parsed_product} />
              </CardContent>
            </Card>
          )}

          {/* ② 标品匹配 */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <span>🔗</span> 标品匹配
              </CardTitle>
            </CardHeader>
            <CardContent>
              <MatchedStandardCard
                matched={result.matched_standard ?? null}
                confidence={result.match_confidence ?? 0}
              />
            </CardContent>
          </Card>

          {/* ③ 上架信息（可编辑） */}
          {result.listing_info && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <span>✍️</span> 上架信息
                  <span className="text-xs font-normal text-gray-400">（可编辑）</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">优化后标题</label>
                  <Input
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    placeholder="商品标题"
                  />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">建议售价（元）</label>
                    <Input
                      value={editPrice}
                      onChange={(e) => setEditPrice(e.target.value)}
                      placeholder="0.00"
                      type="text"
                    />
                  </div>
                  {result.listing_info.price_analysis && (
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">定价分析</label>
                      <p className="text-xs text-gray-500 mt-2 leading-relaxed">
                        {String(result.listing_info.price_analysis)}
                      </p>
                    </div>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">卖点（每行一条）</label>
                  <textarea
                    value={editPoints}
                    onChange={(e) => setEditPoints(e.target.value)}
                    rows={4}
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 resize-y"
                    placeholder="卖点1&#10;卖点2&#10;卖点3"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">SEO 关键词（用、分隔）</label>
                  <Input
                    value={editKeywords}
                    onChange={(e) => setEditKeywords(e.target.value)}
                    placeholder="关键词1、关键词2、关键词3"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">商品描述</label>
                  <textarea
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    rows={5}
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 resize-y"
                    placeholder="商品详细描述..."
                  />
                </div>
              </CardContent>
            </Card>
          )}

          {/* ④ 合规校验 */}
          {result.compliance_check && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <span>🛡️</span> 合规校验
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ComplianceCard data={result.compliance_check} />
              </CardContent>
            </Card>
          )}

          {/* ⑤ 底部操作 */}
          <div className="flex flex-wrap gap-3 pt-2">
            <Button
              onClick={handleCopyListingPlan}
              disabled={result.compliance_check?.can_list === false}
              className="flex-1 sm:flex-none"
            >
              📋 复制上架方案
            </Button>
            <Button
              variant="outline"
              onClick={handleReset}
              className="flex-1 sm:flex-none"
            >
              🔄 重新解析
            </Button>
            <Button
              variant="outline"
              className="flex-1 sm:flex-none"
            >
              💾 保存草稿
            </Button>
          </div>
          <p className="text-xs text-gray-500">
            当前生成的是可编辑上架草案，复制后到美团商家后台完成最终发布。
          </p>
        </div>
      )}
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ParsedProductCard({ data }: { data: ParsedProduct }) {
  const fields: Array<{ label: string; value: unknown }> = [
    { label: '清洗后标题', value: data.cleaned_title || data.title },
    { label: '品牌', value: data.brand },
    { label: '品类', value: data.category },
    { label: '条码', value: data.barcode },
  ];

  const medFields: Array<{ label: string; value: unknown }> = [
    { label: '注册证号', value: data.registration_number },
    { label: '分类等级', value: data.device_class },
    { label: '适用范围', value: data.scope },
  ];

  const hasMed = medFields.some((f) => f.value);
  const specs = data.specs && typeof data.specs === 'object' ? Object.entries(data.specs) : [];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {fields.map((f) => f.value ? (
          <div key={f.label}>
            <span className="text-xs text-gray-400">{f.label}</span>
            <p className="text-sm text-gray-800 font-medium mt-0.5">{String(f.value)}</p>
          </div>
        ) : null)}
      </div>

      {specs.length > 0 && (
        <div>
          <span className="text-xs text-gray-400">规格参数</span>
          <div className="mt-1 flex flex-wrap gap-2">
            {specs.map(([k, v]) => (
              <span key={k} className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                <span className="text-gray-400">{k}:</span> {String(v)}
              </span>
            ))}
          </div>
        </div>
      )}

      {hasMed && (
        <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
          <p className="text-xs font-semibold text-blue-700 mb-2">🏥 医疗器械信息</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {medFields.map((f) => f.value ? (
              <div key={f.label}>
                <span className="text-xs text-blue-400">{f.label}</span>
                <p className="text-sm text-blue-800 font-medium mt-0.5">{String(f.value)}</p>
              </div>
            ) : null)}
          </div>
        </div>
      )}
    </div>
  );
}

function MatchedStandardCard({
  matched,
  confidence,
}: {
  matched: MatchedStandard | null;
  confidence: number;
}) {
  if (!matched) {
    return (
      <div className="rounded-lg border border-gray-100 bg-gray-50 p-4 text-center text-sm text-gray-400">
        未匹配到对应标品
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-gray-800">{matched.name || '未知标品'}</p>
          {(matched.standard_id || matched.id) && (
            <p className="text-xs text-gray-400 mt-0.5">
              ID: {String(matched.standard_id || matched.id)}
            </p>
          )}
        </div>
        <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium shrink-0 ${confidenceColor(confidence)}`}>
          {confidenceLabel(confidence)} {(confidence * 100).toFixed(0)}%
        </span>
      </div>

      {matched.reason && (
        <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 text-xs text-gray-500">
          💡 {String(matched.reason)}
        </div>
      )}
    </div>
  );
}

function ComplianceCard({ data }: { data: ComplianceCheck }) {
  const canList = data.can_list !== false;
  const issues = (data.issues || []).slice().sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)
  );

  return (
    <div className="space-y-3">
      {/* 最终判定 */}
      <div className={`flex items-center gap-2 rounded-lg border px-4 py-3 ${
        canList ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'
      }`}>
        <span className="text-xl">{canList ? '✅' : '❌'}</span>
        <div>
          <p className={`text-sm font-medium ${canList ? 'text-green-700' : 'text-red-700'}`}>
            {canList ? '可以上架' : '暂不可上架，需先修改'}
          </p>
        </div>
      </div>

      {/* 问题列表 */}
      {issues.length > 0 && (
        <div className="space-y-2">
          {issues.map((issue, i) => (
            <div
              key={i}
              className={`flex items-start gap-2.5 rounded-lg border px-3 py-2.5 ${severityColor(issue.severity)}`}
            >
              <Badge className={`shrink-0 mt-0.5 text-[10px] ${severityColor(issue.severity)} border-0`}>
                {severityLabel(issue.severity)}
              </Badge>
              <div className="text-xs leading-relaxed">
                {issue.field && <span className="font-medium">[{issue.field}] </span>}
                {issue.message}
              </div>
            </div>
          ))}
        </div>
      )}

      {issues.length === 0 && (
        <p className="text-sm text-gray-400 text-center py-2">无合规问题</p>
      )}
    </div>
  );
}

export default ListingPage;
