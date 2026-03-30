'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { withErrorBoundary } from '@/components/error-boundary';
import { fetchAPI } from '@/lib/api';

interface KnowledgeStats {
  knowledgeStatus?: {
    productKnowledgeCount: number;
    faqCount: number;
    policyCount: number;
    knowledgeBaseCount: number;
    totalKnowledgeItems: number;
  };
}

interface FAQEntry {
  id: string;
  question: string;
  answer: string;
  category: string;
  source?: string;
}

interface PolicyEntry {
  id: string;
  title: string;
  content: string;
  category: string;
  url?: string;
  source?: string;
}

interface KnowledgeRepairDraft {
  issue_key: string;
  status: string;
  metadata?: {
    category?: string;
    question?: string;
    suggested_answer?: string;
    reason?: string;
    session_id?: string;
    created_at?: string;
  };
  updated_at?: string;
}

const SOURCE_LABELS: Record<string, string> = {
  knowledge_base: '人工FAQ',
  auto_faq: '自动FAQ',
  policy_documents: '售后政策',
  product_knowledge: '商品知识',
};

function KnowledgePage() {
  const searchParams = useSearchParams();
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [entries, setEntries] = useState<FAQEntry[]>([]);
  const [policies, setPolicies] = useState<PolicyEntry[]>([]);
  const [knowledgeDrafts, setKnowledgeDrafts] = useState<KnowledgeRepairDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [policySaving, setPolicySaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [editingFaqId, setEditingFaqId] = useState<string | null>(null);
  const [editingPolicyId, setEditingPolicyId] = useState<string | null>(null);
  const [form, setForm] = useState({
    category: '通用',
    question: '',
    answer: '',
  });
  const [policyForm, setPolicyForm] = useState({
    category: '售后政策',
    title: '',
    content: '',
    url: '',
  });
  const [editFaqForm, setEditFaqForm] = useState({
    category: '通用',
    question: '',
    answer: '',
  });
  const [editPolicyForm, setEditPolicyForm] = useState({
    category: '售后政策',
    title: '',
    content: '',
    url: '',
  });

  const load = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const [statsData, faqData, policyData, draftData] = await Promise.all([
        fetchAPI<Record<string, unknown>>('/customer-service/stats'),
        fetchAPI<FAQEntry[]>('/knowledge/faq?limit=50'),
        fetchAPI<PolicyEntry[]>('/knowledge/policies?limit=50'),
        fetchAPI<KnowledgeRepairDraft[]>('/issue-actions?issue_type=knowledge_repair_draft&status=acknowledged&limit=50'),
      ]);
      setStats({
        knowledgeStatus: statsData.knowledgeStatus as KnowledgeStats['knowledgeStatus'],
      });
      setEntries(faqData);
      setPolicies(policyData);
      setKnowledgeDrafts(draftData);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const question = searchParams.get('question');
    const answer = searchParams.get('answer');
    const category = searchParams.get('category');
    if (!question && !answer && !category) return;
    setForm((prev) => ({
      category: category || prev.category,
      question: question || prev.question,
      answer: answer || prev.answer,
    }));
  }, [searchParams]);

  const handleCreate = async () => {
    if (!form.question.trim() || !form.answer.trim()) {
      setMessage('问题和答案不能为空');
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await fetchAPI('/knowledge/faq', {
        method: 'POST',
        body: JSON.stringify({
          category: form.category.trim() || '通用',
          question: form.question.trim(),
          answer: form.answer.trim(),
        }),
      });
      setForm({ category: '通用', question: '', answer: '' });
      setMessage('FAQ 已创建');
      await load();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (faqId: string) => {
    setMessage(null);
    try {
      await fetchAPI(`/knowledge/faq/${faqId}`, { method: 'DELETE' });
      setMessage('FAQ 已删除');
      await load();
    } catch (error) {
      setMessage((error as Error).message);
    }
  };

  const handleStartEditFaq = (entry: FAQEntry) => {
    setEditingFaqId(entry.id);
    setEditFaqForm({
      category: entry.category || '通用',
      question: entry.question,
      answer: entry.answer,
    });
  };

  const handleSaveFaq = async () => {
    if (!editingFaqId) return;
    setSaving(true);
    setMessage(null);
    try {
      await fetchAPI(`/knowledge/faq/${editingFaqId}`, {
        method: 'PUT',
        body: JSON.stringify({
          category: editFaqForm.category.trim() || '通用',
          question: editFaqForm.question.trim(),
          answer: editFaqForm.answer.trim(),
        }),
      });
      setEditingFaqId(null);
      setMessage('FAQ 已更新');
      await load();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleCreatePolicy = async () => {
    if (!policyForm.title.trim() || !policyForm.content.trim()) {
      setMessage('政策标题和内容不能为空');
      return;
    }
    setPolicySaving(true);
    setMessage(null);
    try {
      await fetchAPI('/knowledge/policies', {
        method: 'POST',
        body: JSON.stringify({
          category: policyForm.category.trim() || '售后政策',
          policy_type: policyForm.category.trim() || '售后政策',
          title: policyForm.title.trim(),
          content: policyForm.content.trim(),
          url: policyForm.url.trim() || null,
        }),
      });
      setPolicyForm({ category: '售后政策', title: '', content: '', url: '' });
      setMessage('售后政策已创建');
      await load();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setPolicySaving(false);
    }
  };

  const handleDeletePolicy = async (policyId: string) => {
    setMessage(null);
    try {
      await fetchAPI(`/knowledge/policies/${policyId}`, { method: 'DELETE' });
      setMessage('售后政策已删除');
      await load();
    } catch (error) {
      setMessage((error as Error).message);
    }
  };

  const handleUseKnowledgeDraft = (draft: KnowledgeRepairDraft) => {
    setForm({
      category: draft.metadata?.category || '客服修复',
      question: draft.metadata?.question || '',
      answer: draft.metadata?.suggested_answer || '',
    });
    setMessage('已将知识修复草稿填入 FAQ 表单');
  };

  const handleCloseKnowledgeDraft = async (draft: KnowledgeRepairDraft, status: 'resolved' | 'ignored') => {
    setMessage(null);
    try {
      await fetchAPI('/issue-actions', {
        method: 'POST',
        body: JSON.stringify({
          issue_type: 'knowledge_repair_draft',
          issue_key: draft.issue_key,
          title: '客服知识修复',
          status,
          metadata: draft.metadata || {},
        }),
      });
      setKnowledgeDrafts((prev) => prev.filter((item) => item.issue_key !== draft.issue_key));
      setMessage(status === 'resolved' ? '知识修复草稿已关闭' : '知识修复草稿已忽略');
    } catch (error) {
      setMessage((error as Error).message);
    }
  };

  const handleStartEditPolicy = (entry: PolicyEntry) => {
    setEditingPolicyId(entry.id);
    setEditPolicyForm({
      category: entry.category || '售后政策',
      title: entry.title,
      content: entry.content,
      url: entry.url || '',
    });
  };

  const handleSavePolicy = async () => {
    if (!editingPolicyId) return;
    setPolicySaving(true);
    setMessage(null);
    try {
      await fetchAPI(`/knowledge/policies/${editingPolicyId}`, {
        method: 'PUT',
        body: JSON.stringify({
          category: editPolicyForm.category.trim() || '售后政策',
          policy_type: editPolicyForm.category.trim() || '售后政策',
          title: editPolicyForm.title.trim(),
          content: editPolicyForm.content.trim(),
          url: editPolicyForm.url.trim() || null,
        }),
      });
      setEditingPolicyId(null);
      setMessage('售后政策已更新');
      await load();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setPolicySaving(false);
    }
  };

  const knowledgeStatus = stats?.knowledgeStatus;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">📚 知识中心</h1>
          <p className="mt-1 text-sm text-muted-foreground">把 FAQ、售后政策和结构化知识真正管起来，客服质量才会稳定。</p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}>
          {loading ? '刷新中...' : '刷新'}
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">商品知识</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{Number(knowledgeStatus?.productKnowledgeCount || 0)}</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">FAQ</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{Number(knowledgeStatus?.faqCount || 0)}</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">售后政策</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{Number(knowledgeStatus?.policyCount || 0)}</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">结构化知识</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{Number(knowledgeStatus?.knowledgeBaseCount || 0)}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-slate-200">
        <CardHeader>
          <CardTitle>新增 FAQ</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <Input
              value={form.category}
              onChange={(event) => setForm((prev) => ({ ...prev, category: event.target.value }))}
              placeholder="分类，例如：售后/配送/规格"
            />
            <Input
              value={form.question}
              onChange={(event) => setForm((prev) => ({ ...prev, question: event.target.value }))}
              placeholder="问题"
              className="md:col-span-2"
            />
          </div>
          <textarea
            value={form.answer}
            onChange={(event) => setForm((prev) => ({ ...prev, answer: event.target.value }))}
            placeholder="答案"
            className="min-h-32 w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400"
          />
          <div className="flex items-center gap-3">
            <Button onClick={handleCreate} disabled={saving}>
              {saving ? '保存中...' : '保存 FAQ'}
            </Button>
            {message && <div className="text-sm text-slate-600">{message}</div>}
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardHeader>
          <CardTitle>新增售后政策</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Input
              value={policyForm.category}
              onChange={(event) => setPolicyForm((prev) => ({ ...prev, category: event.target.value }))}
              placeholder="政策分类，例如：退款/配送/破损"
            />
            <Input
              value={policyForm.url}
              onChange={(event) => setPolicyForm((prev) => ({ ...prev, url: event.target.value }))}
              placeholder="来源链接，可不填"
            />
          </div>
          <Input
            value={policyForm.title}
            onChange={(event) => setPolicyForm((prev) => ({ ...prev, title: event.target.value }))}
            placeholder="政策标题"
          />
          <textarea
            value={policyForm.content}
            onChange={(event) => setPolicyForm((prev) => ({ ...prev, content: event.target.value }))}
            placeholder="政策内容"
            className="min-h-32 w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400"
          />
          <div className="flex items-center gap-3">
            <Button onClick={handleCreatePolicy} disabled={policySaving}>
              {policySaving ? '保存中...' : '保存政策'}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200 bg-slate-50/70">
        <CardHeader>
          <CardTitle>当前知识缺口</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-medium text-slate-900">售后政策偏空</div>
            <div className="mt-1 text-sm text-slate-600">
              当前政策条目 {Number(knowledgeStatus?.policyCount || 0)} 条。退款、配送、破损、禁忌类问题仍缺正式知识源。
            </div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-medium text-slate-900">人工 FAQ 仍少</div>
            <div className="mt-1 text-sm text-slate-600">
              当前结构化 FAQ {Number(knowledgeStatus?.knowledgeBaseCount || 0)} 条。应优先补高频咨询和售后争议问题。
            </div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-medium text-slate-900">商品知识已接入</div>
            <div className="mt-1 text-sm text-slate-600">
              已有 {Number(knowledgeStatus?.productKnowledgeCount || 0)} 条商品知识，可作为客服 grounding，但不能替代售后规则。
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardHeader>
          <CardTitle>客服知识修复草稿</CardTitle>
        </CardHeader>
        <CardContent>
          {knowledgeDrafts.length === 0 ? (
            <div className="text-sm text-muted-foreground">当前没有待沉淀的客服知识草稿。</div>
          ) : (
            <div className="space-y-3">
              {knowledgeDrafts.map((draft) => (
                <div key={draft.issue_key} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{draft.metadata?.category || '客服修复'}</Badge>
                        <Badge variant="secondary">待沉淀</Badge>
                      </div>
                      <div className="text-sm font-medium text-slate-900">{draft.metadata?.question || '待补问题'}</div>
                      <div className="text-sm text-slate-600 whitespace-pre-wrap">{draft.metadata?.suggested_answer || '当前没有建议答案'}</div>
                      {draft.metadata?.reason ? (
                        <div className="text-xs text-amber-700">触发原因：{draft.metadata.reason}</div>
                      ) : null}
                    </div>
                    <div className="flex flex-col gap-2">
                      <Button size="sm" onClick={() => handleUseKnowledgeDraft(draft)}>
                        填入 FAQ
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => handleCloseKnowledgeDraft(draft, 'resolved')}>
                        已处理
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleCloseKnowledgeDraft(draft, 'ignored')}>
                        忽略
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardHeader>
          <CardTitle>知识条目</CardTitle>
        </CardHeader>
        <CardContent>
          {entries.length === 0 ? (
            <div className="text-sm text-muted-foreground">当前还没有可运营的 FAQ 条目。</div>
          ) : (
            <div className="space-y-3">
              {entries.map((entry) => (
                <div key={entry.id} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{entry.category || '未分类'}</Badge>
                        {entry.source && <Badge variant="secondary">{SOURCE_LABELS[entry.source] || entry.source}</Badge>}
                      </div>
                      {editingFaqId === entry.id ? (
                        <div className="space-y-3">
                          <Input
                            value={editFaqForm.category}
                            onChange={(event) => setEditFaqForm((prev) => ({ ...prev, category: event.target.value }))}
                            placeholder="分类"
                          />
                          <Input
                            value={editFaqForm.question}
                            onChange={(event) => setEditFaqForm((prev) => ({ ...prev, question: event.target.value }))}
                            placeholder="问题"
                          />
                          <textarea
                            value={editFaqForm.answer}
                            onChange={(event) => setEditFaqForm((prev) => ({ ...prev, answer: event.target.value }))}
                            className="min-h-28 w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400"
                          />
                        </div>
                      ) : (
                        <>
                          <div className="text-sm font-medium text-slate-900">{entry.question}</div>
                          <div className="text-sm text-slate-600 whitespace-pre-wrap">{entry.answer}</div>
                        </>
                      )}
                    </div>
                    {entry.id.startsWith('kb_') ? (
                      <div className="flex flex-col gap-2">
                        {editingFaqId === entry.id ? (
                          <>
                            <Button size="sm" onClick={handleSaveFaq} disabled={saving}>
                              {saving ? '保存中...' : '保存'}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => setEditingFaqId(null)}>
                              取消
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button variant="ghost" size="sm" onClick={() => handleStartEditFaq(entry)}>
                              编辑
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => handleDelete(entry.id)}>
                              删除
                            </Button>
                          </>
                        )}
                      </div>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardHeader>
          <CardTitle>售后政策</CardTitle>
        </CardHeader>
        <CardContent>
          {policies.length === 0 ? (
            <div className="text-sm text-muted-foreground">当前还没有可运营的售后政策条目。</div>
          ) : (
            <div className="space-y-3">
              {policies.map((entry) => (
                <div key={entry.id} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{entry.category || '售后政策'}</Badge>
                        <Badge variant="secondary">{SOURCE_LABELS[entry.source || 'policy_documents'] || '售后政策'}</Badge>
                      </div>
                      {editingPolicyId === entry.id ? (
                        <div className="space-y-3">
                          <Input
                            value={editPolicyForm.category}
                            onChange={(event) => setEditPolicyForm((prev) => ({ ...prev, category: event.target.value }))}
                            placeholder="分类"
                          />
                          <Input
                            value={editPolicyForm.title}
                            onChange={(event) => setEditPolicyForm((prev) => ({ ...prev, title: event.target.value }))}
                            placeholder="政策标题"
                          />
                          <Input
                            value={editPolicyForm.url}
                            onChange={(event) => setEditPolicyForm((prev) => ({ ...prev, url: event.target.value }))}
                            placeholder="来源链接"
                          />
                          <textarea
                            value={editPolicyForm.content}
                            onChange={(event) => setEditPolicyForm((prev) => ({ ...prev, content: event.target.value }))}
                            className="min-h-28 w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400"
                          />
                        </div>
                      ) : (
                        <>
                          <div className="text-sm font-medium text-slate-900">{entry.title}</div>
                          <div className="text-sm text-slate-600 whitespace-pre-wrap">{entry.content}</div>
                          {entry.url ? <div className="text-xs text-slate-500">{entry.url}</div> : null}
                        </>
                      )}
                    </div>
                    <div className="flex flex-col gap-2">
                      {editingPolicyId === entry.id ? (
                        <>
                          <Button size="sm" onClick={handleSavePolicy} disabled={policySaving}>
                            {policySaving ? '保存中...' : '保存'}
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setEditingPolicyId(null)}>
                            取消
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button variant="ghost" size="sm" onClick={() => handleStartEditPolicy(entry)}>
                            编辑
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => handleDeletePolicy(entry.id)}>
                            删除
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default withErrorBoundary(KnowledgePage);
