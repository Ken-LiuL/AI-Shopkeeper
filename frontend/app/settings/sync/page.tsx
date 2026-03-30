'use client';

import { useCallback, useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  commitManualImport,
  getManualImportComparison,
  getManualImportOverview,
  getManualImportReview,
  getManualImportRuns,
  previewManualImport,
  type ManualImportComparison,
  type ManualImportOverview,
  type ManualImportPreview,
  type ManualImportQualityIssue,
  type ManualImportReview,
  type ManualImportResult,
  type ManualImportRun,
  type ManualImportType,
} from '@/lib/api';

const IMPORT_TYPE_LABELS: Record<ManualImportType, string> = {
  products: '商品规格明细',
  orders: '订单列表与明细',
  inventory: '库存查询',
};

const IMPORT_TEMPLATES: Array<{
  importType: ManualImportType;
  title: string;
  description: string;
  impact: string;
}> = [
  {
    importType: 'products',
    title: '商品规格明细表',
    description: '补齐 SKU、条码、品牌、分类、卖点、售价、组合关系。',
    impact: '驱动商品管理、客服知识、搜索召回和定价基础信息。',
  },
  {
    importType: 'orders',
    title: '订单列表+明细表',
    description: '补齐真实订单、商品行、支付金额、门店、状态和退款标记。',
    impact: '驱动日报、热销识别、套餐分析、销量回填和经营概览。',
  },
  {
    importType: 'inventory',
    title: '库存查询表',
    description: '补齐总库存、可用库存、锁定库存、渠道库存和成本价。',
    impact: '驱动库存页、低库存预警、补货建议和库存价值判断。',
  },
];

const REVIEW_TABLE_LABELS: Record<string, string> = {
  stockout_but_selling: '高风险缺货商品',
  products_missing_price: '缺售价商品',
  missing_price: '缺售价商品',
  catalog_gaps: '主档缺口商品',
  order_amount_mismatch: '金额不一致订单',
  inventory_missing_cost: '缺成本库存',
};

const REVIEW_ACTION_LINKS: Record<string, string> = {
  stockout_but_selling: '/inventory',
  catalog_gaps: '/products',
  products_missing_price: '/products',
  missing_price: '/products',
  order_amount_mismatch: '/orders',
  inventory_missing_cost: '/inventory',
};

type ImportTypeSelection = 'auto' | ManualImportType;

function formatTime(ts?: string | null) {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
  } catch {
    return ts;
  }
}

function formatPreviewValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return JSON.stringify(value, null, 0);
  } catch {
    return String(value);
  }
}

function qualityTone(score?: number) {
  if ((score ?? 0) >= 90) return 'bg-emerald-100 text-emerald-800';
  if ((score ?? 0) >= 75) return 'bg-amber-100 text-amber-800';
  return 'bg-red-100 text-red-800';
}

function formatSignedDelta(value?: number, suffix = '') {
  if (value === undefined || value === null) return '—';
  if (value === 0) return `0${suffix}`;
  return `${value > 0 ? '+' : ''}${value}${suffix}`;
}

function issueTone(severity: ManualImportQualityIssue['severity']) {
  if (severity === 'critical') return 'bg-red-50 border-red-200 text-red-700';
  if (severity === 'warning') return 'bg-amber-50 border-amber-200 text-amber-700';
  return 'bg-slate-50 border-slate-200 text-slate-700';
}

function ManualImportSectionPreview({
  title,
  rows,
}: {
  title: string;
  rows: unknown[];
}) {
  if (!rows.length) {
    return null;
  }

  const firstRow = rows[0];
  const isRecordList =
    !Array.isArray(firstRow) &&
    typeof firstRow === 'object' &&
    firstRow !== null;

  if (!isRecordList) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div className="mb-2 text-sm font-medium text-slate-800">{title}</div>
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs text-slate-700">
          {JSON.stringify(rows.slice(0, 3), null, 2)}
        </pre>
      </div>
    );
  }

  const columns = Object.keys(firstRow as Record<string, unknown>).slice(0, 6);

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-800">
        {title}
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-white">
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  className="px-4 py-3 text-left font-medium text-slate-500"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {rows.slice(0, 5).map((row, index) => {
              const record = row as Record<string, unknown>;
              return (
                <tr key={`${title}-${index}`}>
                  {columns.map((column) => (
                    <td
                      key={`${title}-${index}-${column}`}
                      className="max-w-xs px-4 py-3 align-top text-slate-700"
                    >
                      <div className="max-h-16 overflow-hidden break-all">
                        {formatPreviewValue(record[column])}
                      </div>
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function SyncSettingsPage() {
  const [overview, setOverview] = useState<ManualImportOverview | null>(null);
  const [review, setReview] = useState<ManualImportReview | null>(null);
  const [runs, setRuns] = useState<ManualImportRun[]>([]);
  const [comparison, setComparison] = useState<ManualImportComparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [manualLoading, setManualLoading] = useState(true);
  const [manualError, setManualError] = useState<string | null>(null);

  const [selectedType, setSelectedType] = useState<ImportTypeSelection>('auto');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ManualImportPreview | null>(null);
  const [lastResult, setLastResult] = useState<ManualImportResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [manualMessage, setManualMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const loadManualData = useCallback(async (quiet = false) => {
    if (!quiet) {
      setManualLoading(true);
    }
    setManualError(null);
    try {
      const [overviewData, reviewData, runData] = await Promise.all([
        getManualImportOverview(),
        getManualImportReview(12),
        getManualImportRuns(10),
      ]);
      setOverview(overviewData);
      setReview(reviewData);
      setRuns(runData);
    } catch (error) {
      setManualError(`加载导入记录失败: ${(error as Error).message}`);
    } finally {
      if (!quiet) {
        setManualLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    loadManualData();

    const importTimer = setInterval(() => {
      loadManualData(true);
    }, 60000);

    return () => {
      clearInterval(importTimer);
    };
  }, [loadManualData]);

  const selectedImportType =
    selectedType === 'auto' ? undefined : selectedType;

  const comparisonImportType =
    selectedImportType
    || lastResult?.import_type
    || overview?.latest_run?.import_type;
  const comparisonRefreshKey = `${comparisonImportType || 'auto'}:${lastResult?.run_id || overview?.latest_run?.created_at || 'none'}`;

  const loadComparison = useCallback(async (importType?: ManualImportType) => {
    setComparisonLoading(true);
    try {
      const data = await getManualImportComparison(importType);
      setComparison(data);
    } catch {
      setComparison(null);
    } finally {
      setComparisonLoading(false);
    }
  }, []);

  useEffect(() => {
    loadComparison(comparisonImportType);
  }, [comparisonImportType, comparisonRefreshKey, loadComparison]);

  const handlePreview = async () => {
    if (!selectedFile) {
      setManualMessage({ ok: false, text: '请先选择要预览的 Excel 文件' });
      return;
    }
    setPreviewing(true);
    setManualMessage(null);
    try {
      const data = await previewManualImport(selectedFile, selectedImportType);
      setPreview(data);
      setLastResult(null);
      setManualMessage({
        ok: true,
        text: `已识别为${IMPORT_TYPE_LABELS[data.import_type]}，共 ${data.total_rows} 行。`,
      });
    } catch (error) {
      setPreview(null);
      setManualMessage({ ok: false, text: (error as Error).message });
    } finally {
      setPreviewing(false);
    }
  };

  const handleImport = async () => {
    if (!selectedFile) {
      setManualMessage({ ok: false, text: '请先选择要导入的 Excel 文件' });
      return;
    }
    setImporting(true);
    setManualMessage(null);
    try {
      const data = await commitManualImport(selectedFile, selectedImportType);
      setLastResult(data);
      setPreview(data);
      setManualMessage({
        ok: true,
        text: `导入完成：写入 ${data.imported_rows} 行，跳过 ${data.skipped_rows} 行。`,
      });
      await loadManualData(true);
    } catch (error) {
      setManualMessage({ ok: false, text: (error as Error).message });
    } finally {
      setImporting(false);
    }
  };

  const latestPreview = lastResult || preview;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">数据导入中心</h1>
          <p className="mt-1 text-sm text-slate-500">
            当前主链路只有人工导入。系统会在导入时自动做识别、质检、回填和导入后 review，直接服务库存、订单、商品和客服 AI。
          </p>
        </div>
        <Badge className="w-fit bg-slate-900 text-white">AI 数据底座</Badge>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {[
          {
            title: '1. 上传批次',
            description: '每天导出商品、订单、库存三张表，拖入后先做自动识别。',
          },
          {
            title: '2. AI 审查质量',
            description: '系统识别缺售价、金额异常、主档缺口、缺成本等风险。',
          },
          {
            title: '3. 导入后复核',
            description: '自动生成缺货、补档、异常订单等待处理清单，直接进入工作台处理。',
          },
        ].map((step) => (
          <Card key={step.title} className="border-slate-200 bg-slate-50/70">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{step.title}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">{step.description}</CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {IMPORT_TEMPLATES.map((template) => (
          <Card key={template.importType} className="border-slate-200">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center justify-between text-base">
                <span>{template.title}</span>
                <Badge variant="outline">{IMPORT_TYPE_LABELS[template.importType]}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-slate-600">
              <p>{template.description}</p>
              <p className="rounded-lg bg-slate-50 p-3 text-slate-700">{template.impact}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-[1.2fr,0.8fr]">
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>上传与质检</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-4 md:grid-cols-[180px,1fr]">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700">导入类型</label>
                  <select
                    value={selectedType}
                    onChange={(event) => setSelectedType(event.target.value as ImportTypeSelection)}
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm outline-none ring-0 focus:border-slate-400"
                  >
                    <option value="auto">自动识别</option>
                    <option value="products">商品规格明细</option>
                    <option value="orders">订单列表与明细</option>
                    <option value="inventory">库存查询</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-700">Excel 文件</label>
                  <Input
                    type="file"
                    accept=".xls,.xlsx"
                    onChange={(event) => {
                      const nextFile = event.target.files?.[0] || null;
                      setSelectedFile(nextFile);
                      setPreview(null);
                      setLastResult(null);
                      setManualMessage(null);
                    }}
                  />
                  <p className="text-xs text-slate-500">
                    支持 `.xlsx` 和 `.xls`。当前样例中的商品表、订单表、库存表都能被识别。
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button onClick={handlePreview} disabled={!selectedFile || previewing}>
                  {previewing ? '预览中...' : '预览并审查质量'}
                </Button>
                <Button
                  variant="outline"
                  onClick={handleImport}
                  disabled={!selectedFile || importing}
                >
                  {importing ? '导入中...' : '确认导入'}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setSelectedFile(null);
                    setPreview(null);
                    setLastResult(null);
                    setManualMessage(null);
                  }}
                >
                  清空
                </Button>
              </div>

              {manualMessage && (
                <div
                  className={`rounded-lg border px-4 py-3 text-sm ${
                    manualMessage.ok
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                      : 'border-red-200 bg-red-50 text-red-700'
                  }`}
                >
                  {manualMessage.text}
                </div>
              )}

              {latestPreview && (
                <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge variant="outline">{IMPORT_TYPE_LABELS[latestPreview.import_type]}</Badge>
                    <span className="text-sm text-slate-600">{latestPreview.filename}</span>
                    <Badge className={qualityTone(latestPreview.quality_report.score)}>
                      质量分 {latestPreview.quality_report.score}
                    </Badge>
                    <span className="text-sm text-slate-500">
                      {latestPreview.total_rows} 行
                    </span>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    {Object.entries(latestPreview.quality_report.stats).map(([key, value]) => (
                      <div key={key} className="rounded-lg border border-slate-200 bg-white p-3">
                        <div className="text-xs text-slate-500">{key}</div>
                        <div className="mt-1 text-lg font-semibold text-slate-900">{String(value)}</div>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-lg border border-slate-200 bg-white p-4">
                    <div className="mb-2 text-sm font-medium text-slate-800">识别到的 Sheet</div>
                    <div className="flex flex-wrap gap-2">
                      {latestPreview.detected_sheets.map((sheet) => (
                        <Badge key={sheet} variant="outline">
                          {sheet}
                        </Badge>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="text-sm font-medium text-slate-800">数据质量问题</div>
                    {latestPreview.quality_report.issues.length > 0 ? (
                      latestPreview.quality_report.issues.map((issue) => (
                        <div
                          key={`${issue.code}-${issue.message}`}
                          className={`rounded-lg border p-4 text-sm ${issueTone(issue.severity)}`}
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium">{issue.message}</span>
                            <Badge variant="outline">{issue.severity}</Badge>
                            <span>影响 {issue.count} 行</span>
                          </div>
                          {issue.samples.length > 0 && (
                            <div className="mt-2 text-xs">
                              样例: {issue.samples.join('，')}
                            </div>
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
                        这一批数据没有识别到明显结构问题，可以直接进入正式导入。
                      </div>
                    )}
                  </div>

                  <div className="rounded-lg border border-slate-200 bg-white p-4">
                    <div className="mb-2 text-sm font-medium text-slate-800">补齐建议</div>
                    <div className="space-y-2 text-sm text-slate-600">
                      {latestPreview.quality_report.suggestions.map((suggestion) => (
                        <p key={suggestion}>{suggestion}</p>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>导入概览</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {manualLoading ? (
                <div className="text-sm text-slate-500">正在加载导入记录...</div>
              ) : manualError ? (
                <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                  {manualError}
                </div>
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
                    {(['products', 'orders', 'inventory'] as ManualImportType[]).map((type) => {
                      const item = overview?.by_type.find((row) => row.import_type === type);
                      return (
                        <div key={type} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                          <div className="text-sm font-medium text-slate-800">
                            {IMPORT_TYPE_LABELS[type]}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">
                            导入次数 {item?.run_count || 0}
                          </div>
                          <div className="mt-2 text-2xl font-semibold text-slate-900">
                            {item?.imported_rows || 0}
                          </div>
                          <div className="text-xs text-slate-500">累计写入行数</div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="rounded-lg border border-slate-200 bg-white p-4">
                    <div className="text-sm font-medium text-slate-800">最近一次导入</div>
                    {overview?.latest_run ? (
                      <div className="mt-3 space-y-2 text-sm text-slate-600">
                        <div>{overview.latest_run.filename}</div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline">
                            {IMPORT_TYPE_LABELS[overview.latest_run.import_type]}
                          </Badge>
                          <Badge className={qualityTone(overview.latest_run.quality_score)}>
                            质量分 {overview.latest_run.quality_score}
                          </Badge>
                        </div>
                        <div className="text-xs text-slate-500">
                          {formatTime(overview.latest_run.created_at)}
                        </div>
                      </div>
                    ) : (
                      <div className="mt-2 text-sm text-slate-500">还没有正式导入记录。</div>
                    )}
                  </div>

                  <div className="rounded-lg border border-slate-200 bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium text-slate-800">与上一批对比</div>
                      {comparison?.import_type ? (
                        <Badge variant="outline">{IMPORT_TYPE_LABELS[comparison.import_type]}</Badge>
                      ) : null}
                    </div>
                    {comparisonLoading ? (
                      <div className="mt-3 text-sm text-slate-500">正在对比最近两次导入...</div>
                    ) : !comparison?.latest_run ? (
                      <div className="mt-3 text-sm text-slate-500">还没有可对比的导入批次。</div>
                    ) : (
                      <div className="mt-3 space-y-4">
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                            <div className="text-xs text-slate-500">写入行数变化</div>
                            <div className="mt-1 text-lg font-semibold text-slate-900">
                              {formatSignedDelta(comparison.delta.imported_rows)}
                            </div>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                            <div className="text-xs text-slate-500">质量分变化</div>
                            <div className="mt-1 text-lg font-semibold text-slate-900">
                              {formatSignedDelta(comparison.delta.quality_score)}
                            </div>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                            <div className="text-xs text-slate-500">总行数变化</div>
                            <div className="mt-1 text-lg font-semibold text-slate-900">
                              {formatSignedDelta(comparison.delta.total_rows)}
                            </div>
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                            <div className="text-xs text-slate-500">待处理问题变化</div>
                            <div className="mt-1 text-lg font-semibold text-slate-900">
                              {formatSignedDelta(comparison.delta.open_issues)}
                            </div>
                          </div>
                        </div>

                        {comparison.review_delta.available ? (
                          <div className="space-y-3 text-sm">
                            {comparison.review_delta.new_issues.length > 0 ? (
                              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-700">
                                新增问题：{comparison.review_delta.new_issues.map((item) => `${item.title} ${item.current}`).join('，')}
                              </div>
                            ) : null}
                            {comparison.review_delta.resolved_issues.length > 0 ? (
                              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-emerald-700">
                                已修复问题：{comparison.review_delta.resolved_issues.map((item) => `${item.title} ${item.previous}`).join('，')}
                              </div>
                            ) : null}
                            {comparison.review_delta.improved_issues.length > 0 ? (
                              <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-blue-700">
                                改善中：{comparison.review_delta.improved_issues.map((item) => `${item.title} ${Math.abs(item.delta)}`).join('，')}
                              </div>
                            ) : null}
                            {comparison.review_delta.worsened_issues.length > 0 ? (
                              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-700">
                                恶化问题：{comparison.review_delta.worsened_issues.map((item) => `${item.title} +${item.delta}`).join('，')}
                              </div>
                            ) : null}
                          </div>
                        ) : (
                          <div className="text-sm text-slate-500">
                            当前只能对比导入规模和质量分。完成至少两次同类型正式导入后，系统会开始比较新增问题、已修复问题和恶化问题。
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
                    订单导入后会回填 `products.monthly_sales` 和热销商品数据集。库存导入后会回填
                    `qnh_inventory`、`products.stock` 和 `qnh_products.stock`。商品导入后会补齐客服可检索的商品知识文本。
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {latestPreview && (
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>标准化预览</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {Object.entries(latestPreview.normalized_preview).map(([section, rows]) => (
                <ManualImportSectionPreview
                  key={section}
                  title={section}
                  rows={rows as unknown[]}
                />
              ))}
            </CardContent>
          </Card>
        )}

        <Card className="border-slate-200">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>最近导入记录</CardTitle>
            <Button variant="outline" onClick={() => loadManualData()}>
              刷新记录
            </Button>
          </CardHeader>
          <CardContent>
            {manualLoading ? (
              <div className="text-sm text-slate-500">正在加载...</div>
            ) : runs.length === 0 ? (
              <div className="text-sm text-slate-500">还没有人工导入记录。</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="px-4 py-3 text-left font-medium text-slate-500">时间</th>
                      <th className="px-4 py-3 text-left font-medium text-slate-500">类型</th>
                      <th className="px-4 py-3 text-left font-medium text-slate-500">文件</th>
                      <th className="px-4 py-3 text-left font-medium text-slate-500">写入/总行数</th>
                      <th className="px-4 py-3 text-left font-medium text-slate-500">质量分</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {runs.map((run) => (
                      <tr key={run.run_id}>
                        <td className="px-4 py-3 text-slate-600">{formatTime(run.created_at)}</td>
                        <td className="px-4 py-3">
                          <Badge variant="outline">{IMPORT_TYPE_LABELS[run.import_type]}</Badge>
                        </td>
                        <td className="max-w-md px-4 py-3 text-slate-700">{run.filename}</td>
                        <td className="px-4 py-3 text-slate-700">
                          {run.imported_rows} / {run.total_rows}
                        </td>
                        <td className="px-4 py-3">
                          <Badge className={qualityTone(run.quality_score)}>
                            {run.quality_score}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {review && (
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>导入后 Review</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                <div className="rounded-lg border border-red-200 bg-red-50 p-4">
                  <div className="text-xs text-red-600">有销量但缺货</div>
                  <div className="mt-1 text-2xl font-semibold text-red-800">
                    {review.open_summary?.stockout_but_selling ?? review.summary.stockout_but_selling ?? 0}
                  </div>
                </div>
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                  <div className="text-xs text-amber-700">主档缺口</div>
                  <div className="mt-1 text-2xl font-semibold text-amber-900">
                    {review.open_summary?.catalog_gaps ?? review.summary.catalog_gaps ?? 0}
                  </div>
                </div>
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                  <div className="text-xs text-amber-700">缺售价商品</div>
                  <div className="mt-1 text-2xl font-semibold text-amber-900">
                    {review.open_summary?.products_missing_price ?? review.summary.products_missing_price ?? 0}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs text-slate-600">金额不一致订单</div>
                  <div className="mt-1 text-2xl font-semibold text-slate-900">
                    {review.open_summary?.order_amount_mismatch ?? review.summary.order_amount_mismatch ?? 0}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs text-slate-600">缺成本库存</div>
                  <div className="mt-1 text-2xl font-semibold text-slate-900">
                    {review.open_summary?.inventory_missing_cost ?? review.summary.inventory_missing_cost ?? 0}
                  </div>
                </div>
              </div>

              <div className="space-y-3">
                {review.issues.map((issue) => (
                  <div
                    key={issue.key}
                    className={`rounded-lg border p-4 text-sm ${issueTone(issue.severity)}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{issue.title}</span>
                      <Badge variant="outline">{issue.severity}</Badge>
                      <span>影响 {issue.count} 条</span>
                      {REVIEW_ACTION_LINKS[issue.key] && (
                        <a
                          href={REVIEW_ACTION_LINKS[issue.key]}
                          className="ml-auto text-xs font-medium text-blue-700 hover:text-blue-800"
                        >
                          去处理
                        </a>
                      )}
                    </div>
                    <p className="mt-2">{issue.description}</p>
                    <p className="mt-1 text-xs opacity-80">{issue.recommended_action}</p>
                  </div>
                ))}
              </div>

              <div className="space-y-4">
                {Object.entries(review.tables).map(([key, rows]) =>
                  rows.length > 0 ? (
                    <ManualImportSectionPreview
                      key={key}
                      title={REVIEW_TABLE_LABELS[key] || key}
                      rows={rows}
                    />
                  ) : null
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
