'use client';
import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { withErrorBoundary } from '@/components/error-boundary';
import { fetchAPI, lookupIssueActions, updateIssueAction } from '@/lib/api';
import type { IssueActionRecord } from '@/lib/api';

// ── Types ─────────────────────────────────────────────────────

interface CSStats {
  totalChats: number;
  autoResolveRate: number;
  avgScore: number;
  humanTransfer: number;
  savedCost: number;
  total_sessions?: number;
  today_sessions?: number;
  knowledgeStatus?: {
    productKnowledgeCount: number;
    faqCount: number;
    policyCount: number;
    knowledgeBaseCount: number;
    totalKnowledgeItems: number;
  };
}

interface RecentSession {
  session_id: string;
  customer_id?: string;
  last_message?: string;
  message_count?: number;
  created_at?: string;
  updated_at?: string;
}

interface TestMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  intent?: string;
  needsHuman?: boolean;
  confidence?: number;
  errorCode?: string;
  errorDetail?: string;
}

interface QualityQueueItem {
  queue_type: 'low_score' | 'bad_feedback';
  session_id: string;
  score: number;
  reason: string;
  user_message?: string;
  ai_reply?: string;
  created_at?: string;
}

function buildQualityIssueKey(item: QualityQueueItem) {
  return JSON.stringify({
    queue_type: item.queue_type,
    session_id: item.session_id,
    created_at: item.created_at || '',
    reason: item.reason || '',
    user_message: item.user_message || '',
  });
}

function getIssueStatusText(status?: string) {
  switch (status) {
    case 'acknowledged': return '已知晓';
    case 'resolved': return '已修复';
    case 'ignored': return '已忽略';
    default: return '待处理';
  }
}

// ── Stat Card ─────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  color = 'text-gray-900',
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-5 pb-4">
        <div className={`text-2xl font-bold ${color}`}>{value}</div>
        <div className="text-sm text-muted-foreground mt-1">{label}</div>
        {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

// ── Loading Skeleton ──────────────────────────────────────────

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`bg-muted animate-pulse rounded ${className}`} />;
}

// ── Main Page ─────────────────────────────────────────────────

function CustomerServicePage() {
  const [stats, setStats] = useState<CSStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [sessions, setSessions] = useState<RecentSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [qualityQueue, setQualityQueue] = useState<QualityQueueItem[]>([]);
  const [qualityStatuses, setQualityStatuses] = useState<Record<string, IssueActionRecord>>({});
  const [qualityLoading, setQualityLoading] = useState(true);
  const [savingIssueKey, setSavingIssueKey] = useState<string | null>(null);
  const [queueingKnowledgeKey, setQueueingKnowledgeKey] = useState<string | null>(null);
  const [queuedKnowledgeKeys, setQueuedKnowledgeKeys] = useState<Record<string, boolean>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [testSessions, setTestSessions] = useState<{id: string; name: string; messages: TestMessage[]}[]>([]);
  const [activeTestSession, setActiveTestSession] = useState<string | null>(null);
  const [testInput, setTestInput] = useState('');
  const [testLoading, setTestLoading] = useState(false);

  const loadStats = async () => {
    try {
      const data = await fetchAPI<Record<string, unknown>>('/customer-service/stats');
      setStats({
        totalChats: Number(data.totalChats ?? data.today_sessions ?? 0),
        autoResolveRate: Number(data.autoResolveRate ?? data.resolution_rate ?? 0),
        avgScore: Number(data.avgScore ?? (data.avg_rating ? Number(data.avg_rating) / 5 : 0)),
        humanTransfer: Number(data.humanTransfer ?? 0),
        savedCost: Number(data.savedCost ?? 0),
        total_sessions: Number(data.total_sessions ?? 0),
        knowledgeStatus: {
          productKnowledgeCount: Number((data.knowledgeStatus as Record<string, unknown> | undefined)?.productKnowledgeCount ?? 0),
          faqCount: Number((data.knowledgeStatus as Record<string, unknown> | undefined)?.faqCount ?? 0),
          policyCount: Number((data.knowledgeStatus as Record<string, unknown> | undefined)?.policyCount ?? 0),
          knowledgeBaseCount: Number((data.knowledgeStatus as Record<string, unknown> | undefined)?.knowledgeBaseCount ?? 0),
          totalKnowledgeItems: Number((data.knowledgeStatus as Record<string, unknown> | undefined)?.totalKnowledgeItems ?? 0),
        },
      });
    } catch (err) {
      console.error('Failed to load CS stats:', err);
    } finally {
      setStatsLoading(false);
    }
  };

  const loadSessions = async () => {
    try {
      type SessionsApiResponse = RecentSession[] | { sessions: RecentSession[] };
      const data = await fetchAPI<SessionsApiResponse>('/customer-service/sessions?limit=20');
      const list: RecentSession[] = Array.isArray(data)
        ? data
        : (data as { sessions: RecentSession[] }).sessions || [];
      setSessions(list);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    } finally {
      setSessionsLoading(false);
    }
  };

  const loadQualityQueue = async () => {
    try {
      const data = await fetchAPI<QualityQueueItem[]>('/customer-service/quality-queue?limit=10');
      setQualityQueue(data);
    } catch (err) {
      console.error('Failed to load quality queue:', err);
      setQualityQueue([]);
    } finally {
      setQualityLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([loadStats(), loadSessions(), loadQualityQueue()]);
    setRefreshing(false);
  };

  const createTestSession = async () => {
    const sessionName = `测试客户 ${testSessions.length + 1}`;
    try {
      const data = await fetchAPI<{session_id: string; created_at: string}>('/customer-service/sessions', {
        method: 'POST',
        body: JSON.stringify({ customer_id: `test_${Date.now()}` }),
      });
      const newSession = {
        id: data.session_id,
        name: sessionName,
        messages: [] as TestMessage[],
      };
      setTestSessions(prev => [...prev, newSession]);
      setActiveTestSession(data.session_id);
    } catch {
      const localId = `test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const newSession = {
        id: localId,
        name: sessionName,
        messages: [] as TestMessage[],
      };
      setTestSessions(prev => [...prev, newSession]);
      setActiveTestSession(localId);
    }
  };

  const sendTestMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!testInput.trim() || testLoading || !activeTestSession) return;

    const userMsg: TestMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: testInput.trim(),
      timestamp: new Date(),
    };

    setTestSessions(prev => prev.map(s =>
      s.id === activeTestSession ? { ...s, messages: [...s.messages, userMsg] } : s
    ));
    setTestInput('');
    setTestLoading(true);

    try {
      const response = await fetchAPI<{
        session_id: string;
        reply: string;
        intent?: string;
        needs_human?: boolean;
        error_code?: string;
        error_detail?: string;
      }>('/customer-service/chat', {
        method: 'POST',
        body: JSON.stringify({
          session_id: activeTestSession,
          message: userMsg.content,
        }),
      });

      const aiMsg: TestMessage = {
        id: `ai-${Date.now()}`,
        role: 'assistant',
        content: response.reply,
        timestamp: new Date(),
        intent: response.intent,
        needsHuman: response.needs_human,
        errorCode: response.error_code,
        errorDetail: response.error_detail,
      };

      setTestSessions(prev => prev.map(s =>
        s.id === activeTestSession ? { ...s, messages: [...s.messages, aiMsg] } : s
      ));
    } catch {
      const errMsg: TestMessage = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: '⚠️ 请求失败，请检查后端服务是否运行。',
        timestamp: new Date(),
      };
      setTestSessions(prev => prev.map(s =>
        s.id === activeTestSession ? { ...s, messages: [...s.messages, errMsg] } : s
      ));
    } finally {
      setTestLoading(false);
    }
  };

  const handleTestFeedback = async (sessionId: string, messageId: string, rating: 'good' | 'bad') => {
    try {
      await fetchAPI('/customer-service/feedback', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          message_id: messageId,
          rating,
          comment: `测试反馈: ${rating}`,
        }),
      });
    } catch {
      console.error('Feedback submission failed');
    }
  };

  useEffect(() => {
    loadStats();
    loadSessions();
    loadQualityQueue();
  }, []);

  useEffect(() => {
    if (qualityQueue.length === 0) return;
    lookupIssueActions(
      qualityQueue.slice(0, 10).map((item) => ({
        issue_type: 'customer_service_quality',
        issue_key: buildQualityIssueKey(item),
      }))
    )
      .then((rows) => {
        setQualityStatuses((prev) => {
          const next = { ...prev };
          rows.forEach((item) => {
            next[`${item.issue_type}::${item.issue_key}`] = item;
          });
          return next;
        });
      })
      .catch(() => {});
  }, [qualityQueue]);

  const formatTime = (dateStr?: string) => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleString('zh-CN', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return '—';
    }
  };

  const currentTestSession = testSessions.find((session) => session.id === activeTestSession);
  const knowledgeStatus = stats?.knowledgeStatus;
  const autoReplyReady = (knowledgeStatus?.productKnowledgeCount ?? 0) > 0;
  const faqCount = Number(knowledgeStatus?.faqCount ?? 0);
  const policyCount = Number(knowledgeStatus?.policyCount ?? 0);
  const structuredKnowledgeCount = Number(knowledgeStatus?.knowledgeBaseCount ?? 0);
  const productKnowledgeCount = Number(knowledgeStatus?.productKnowledgeCount ?? 0);
  const totalKnowledgeItems = Number(knowledgeStatus?.totalKnowledgeItems ?? 0);
  const avgScore = Number(stats?.avgScore ?? 0);
  const humanTransfer = Number(stats?.humanTransfer ?? 0);
  const autoResolveRate = Number(stats?.autoResolveRate ?? 0);
  const qualityRiskCount =
    (faqCount === 0 ? 1 : 0) +
    (policyCount === 0 ? 1 : 0) +
    (structuredKnowledgeCount === 0 ? 1 : 0) +
    (avgScore < 0.85 ? 1 : 0) +
    (humanTransfer > 0 ? 1 : 0);

  const renderKnowledgeBadge = (count: number, emptyText = '待补齐') => (
    count > 0 ? (
      <span className="text-green-600">{count.toLocaleString()} 条</span>
    ) : (
      <span className="text-orange-500">{emptyText}</span>
    )
  );

  const workbenchActions = [
    {
      title: '补 FAQ',
      detail: faqCount > 0 ? `当前已有 ${faqCount} 条 FAQ` : '当前没有 FAQ，常见问题只能依赖模型常识',
      href: '/knowledge',
      tone: faqCount > 0 ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800',
      cta: faqCount > 0 ? '继续完善' : '先补知识',
    },
    {
      title: '补售后政策',
      detail: policyCount > 0 ? `当前已有 ${policyCount} 条售后政策` : '售后政策为空，退款/退货类问题风险最高',
      href: '/knowledge',
      tone: policyCount > 0 ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-red-200 bg-red-50 text-red-800',
      cta: policyCount > 0 ? '继续维护' : '立即补齐',
    },
    {
      title: '看转人工风险',
      detail: humanTransfer > 0 ? `今天已有 ${humanTransfer} 次转人工，需要回看触发原因` : '今天暂无转人工，继续保持',
      href: '/customer-service',
      tone: humanTransfer > 0 ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-slate-200 bg-slate-50 text-slate-700',
      cta: humanTransfer > 0 ? '回看对话' : '查看会话',
    },
  ];

  const handleQualityStatusChange = async (
    item: QualityQueueItem,
    status: 'acknowledged' | 'resolved' | 'ignored'
  ) => {
    const issueKey = buildQualityIssueKey(item);
    setSavingIssueKey(issueKey);
    try {
      const result = await updateIssueAction({
        issue_type: 'customer_service_quality',
        issue_key: issueKey,
        title: item.reason || '客服低分回复',
        status,
        metadata: item,
      });
      setQualityStatuses((prev) => ({
        ...prev,
        [`${result.issue_type}::${result.issue_key}`]: result,
      }));
      if (status === 'resolved' || status === 'ignored') {
        setQualityQueue((prev) => prev.filter((entry) => buildQualityIssueKey(entry) !== issueKey));
      }
    } finally {
      setSavingIssueKey(issueKey);
    }
  };

  const handleQueueKnowledgeRepair = async (item: QualityQueueItem) => {
    const issueKey = buildQualityIssueKey(item);
    setQueueingKnowledgeKey(issueKey);
    try {
      await updateIssueAction({
        issue_type: 'knowledge_repair_draft',
        issue_key: issueKey,
        title: item.reason || '客服知识修复',
        status: 'acknowledged',
        metadata: {
          category: '客服修复',
          question: item.user_message || item.reason || '客服常见问题',
          suggested_answer: item.ai_reply || '',
          reason: item.reason || '',
          source_issue_type: item.queue_type,
          session_id: item.session_id,
          created_at: item.created_at,
        },
      });
      setQueuedKnowledgeKeys((prev) => ({ ...prev, [issueKey]: true }));
    } finally {
      setQueueingKnowledgeKey(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">💬 客服质量运营台</h1>
          <p className="text-muted-foreground mt-1">
            先补知识，再看转人工和低质量回复。客服模块的目标不是“能聊天”，而是“稳定少出错”。
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
          className="gap-2"
        >
          {refreshing ? (
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-400" />
          ) : (
            '🔄'
          )}
          刷新
        </Button>
      </div>

      {/* ── 今日客服指标 ── */}
      <section>
        <h2 className="text-lg font-semibold mb-3">今日 AI 客服指标</h2>
        {statsLoading ? (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <Card key={i}>
                <CardContent className="pt-5 pb-4">
                  <Skeleton className="h-8 w-16 mb-2" />
                  <Skeleton className="h-4 w-24" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : stats ? (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <StatCard
              label="今日处理对话"
              value={stats.totalChats}
              color="text-blue-600"
            />
            <StatCard
              label="自动解决率"
              value={`${stats.autoResolveRate}%`}
              sub="未转人工比例"
              color="text-green-600"
            />
            <StatCard
              label="平均回复评分"
              value={stats.avgScore.toFixed(2)}
              sub="满分 1.0"
              color={stats.avgScore >= 0.85 ? 'text-green-600' : 'text-orange-500'}
            />
            <StatCard
              label="转人工次数"
              value={stats.humanTransfer}
              color="text-orange-500"
            />
            <StatCard
              label="预估节省人力"
              value={`¥${stats.savedCost}/天`}
              color="text-purple-600"
            />
          </div>
        ) : (
          <div className="text-sm text-muted-foreground py-4">暂无数据</div>
        )}
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <a href="/knowledge" className="block rounded-xl border border-amber-200 bg-amber-50 p-4 transition-colors hover:bg-amber-100">
          <div className="text-xs text-amber-700">待补客服知识项</div>
          <div className="mt-1 text-3xl font-semibold text-amber-900">{qualityRiskCount}</div>
          <div className="mt-2 text-xs text-amber-700">FAQ、政策、结构化知识与质量风险合并视角</div>
        </a>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">商品知识底座</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{productKnowledgeCount.toLocaleString()}</div>
            <div className="mt-2 text-xs text-slate-500">商品知识不足时，推荐与说明类回复会变弱</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">自动解决率</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{autoResolveRate.toFixed(1)}%</div>
            <div className="mt-2 text-xs text-slate-500">低于 80% 时应优先看知识缺口和转人工原因</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="text-xs text-slate-500">平均回复评分</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{avgScore.toFixed(2)}</div>
            <div className="mt-2 text-xs text-slate-500">低于 0.85 说明回复质量还不够稳</div>
          </CardContent>
        </Card>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-[1.1fr,0.9fr] gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">今日修复优先级</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {workbenchActions.map((item) => (
              <a
                key={item.title}
                href={item.href}
                className={`block rounded-xl border p-4 transition-colors hover:opacity-90 ${item.tone}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">{item.title}</div>
                    <div className="mt-1 text-xs leading-5 opacity-90">{item.detail}</div>
                  </div>
                  <span className="text-xs font-medium whitespace-nowrap">{item.cta}</span>
                </div>
              </a>
            ))}
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
              自动回复状态由知识和服务可用性共同决定，不提供假开关。当前响应超时限制 25 秒，投诉升级词和安全问题默认转人工。
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">知识底座现状</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">商品知识</span>
              {renderKnowledgeBadge(productKnowledgeCount)}
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">售后政策</span>
              {renderKnowledgeBadge(policyCount)}
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">FAQ 库</span>
              {renderKnowledgeBadge(faqCount)}
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">结构化知识</span>
              {renderKnowledgeBadge(structuredKnowledgeCount)}
            </div>
            <div className="pt-1 text-xs text-muted-foreground">
              当前可用知识总量 {totalKnowledgeItems.toLocaleString()} 条
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
              {autoReplyReady
                ? `当前已具备自动回复底座，商品知识 ${productKnowledgeCount.toLocaleString()} 条。下一步重点是补 FAQ、售后政策和结构化规则。`
                : '商品知识底座仍不完整，当前客服 AI 可信度不足，应该先补数据再扩大自动回复范围。'}
            </div>
          </CardContent>
        </Card>
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-3">最近对话记录</h2>
        <Card>
          <CardContent className="p-0">
            {sessionsLoading ? (
              <div className="p-4 space-y-3">
                {[1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="flex gap-3 items-center">
                    <Skeleton className="h-8 w-8 rounded-full" />
                    <div className="flex-1 space-y-1">
                      <Skeleton className="h-4 w-32" />
                      <Skeleton className="h-3 w-48" />
                    </div>
                    <Skeleton className="h-3 w-16" />
                  </div>
                ))}
              </div>
            ) : sessions.length === 0 ? (
              <div className="py-10 text-center text-muted-foreground text-sm">
                暂无对话记录
              </div>
            ) : (
              <div className="divide-y">
                {sessions.map((session) => (
                  <div
                    key={session.session_id}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
                  >
                    <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-sm flex-shrink-0">
                      👤
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-700 truncate">
                        {session.customer_id
                          ? `买家 ${session.customer_id.slice(-6)}`
                          : `会话 ${session.session_id.slice(-6)}`}
                      </div>
                      {session.last_message && (
                        <div className="text-xs text-muted-foreground truncate">
                          {session.last_message}
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1 flex-shrink-0">
                      {session.message_count != null && (
                        <Badge variant="outline" className="text-xs">
                          {session.message_count} 条
                        </Badge>
                      )}
                      <div className="text-xs text-muted-foreground">
                        {formatTime(session.updated_at || session.created_at)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-semibold">内部验证</h2>
            <p className="text-sm text-muted-foreground">仅用于运营或研发验证客服回复，不再作为主界面重心。</p>
          </div>
          <Button variant="outline" size="sm" onClick={createTestSession} className="gap-1">
            ➕ 新建测试客户
          </Button>
        </div>

        {testSessions.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="py-8 text-center">
              <div className="text-3xl mb-3">🧪</div>
              <div className="text-sm text-muted-foreground mb-4">
                需要时再创建模拟买家，验证回复质量和转人工逻辑。
              </div>
              <Button variant="outline" onClick={createTestSession}>
                创建测试会话
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4" style={{ minHeight: '360px' }}>
            <div className="lg:col-span-1 space-y-2">
              {testSessions.map((session) => (
                <button
                  key={session.id}
                  onClick={() => setActiveTestSession(session.id)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                    activeTestSession === session.id
                      ? 'bg-blue-50 border border-blue-200 text-blue-700'
                      : 'bg-gray-50 border border-gray-100 hover:bg-gray-100'
                  }`}
                >
                  <div className="font-medium">👤 {session.name}</div>
                  <div className="text-xs text-muted-foreground truncate">
                    {session.messages.length > 0
                      ? `${session.messages[session.messages.length - 1].content.slice(0, 30)}...`
                      : '新会话'}
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5">
                    {session.messages.filter(m => m.role === 'user').length} 条消息
                  </div>
                </button>
              ))}
            </div>

            <Card className="lg:col-span-3 flex flex-col">
              <CardHeader className="border-b py-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <span>💬</span>
                    {currentTestSession?.name || '选择测试客户'}
                  </CardTitle>
                  <Badge variant="secondary" className="text-xs">
                    AI 客服模式
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col p-0" style={{ maxHeight: '400px' }}>
                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {activeTestSession && currentTestSession?.messages.length === 0 && (
                    <div className="text-center text-sm text-muted-foreground py-8">
                      <div className="text-2xl mb-2">💬</div>
                      扮演买家发送消息，测试 AI 客服的回复质量
                      <div className="flex flex-wrap justify-center gap-2 mt-4">
                        {['血压计推荐一个', '我买的体温计坏了要退货', '订单多久能送到', '你们有没有血糖试纸'].map(q => (
                          <button
                            key={q}
                            onClick={() => setTestInput(q)}
                            className="text-xs px-3 py-1.5 rounded-full border border-gray-200 hover:bg-blue-50 hover:border-blue-200 transition-colors"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {activeTestSession && currentTestSession?.messages.map((msg) => {
                    const isAI = msg.role === 'assistant';
                    return (
                      <div key={msg.id} className={`flex ${isAI ? 'justify-start' : 'justify-end'}`}>
                        <div className="max-w-[80%]">
                          <div className={`rounded-lg px-3 py-2 text-sm ${
                            isAI ? 'bg-gray-100' : 'bg-blue-500 text-white'
                          }`}>
                            {msg.content}
                          </div>
                          {isAI && (
                            <div className="flex items-center gap-1.5 mt-1 px-1">
                              {msg.intent && (
                                <Badge variant="outline" className="text-[10px] h-4 px-1">
                                  {msg.intent}
                                </Badge>
                              )}
                              {msg.needsHuman && (
                                <Badge variant="destructive" className="text-[10px] h-4 px-1">
                                  需转人工
                                </Badge>
                              )}
                              {msg.errorCode && (
                                <div className="flex flex-col gap-0.5">
                                  <Badge
                                    variant="outline"
                                    className="text-[10px] h-4 px-1 border-red-200 text-red-600"
                                  >
                                    错误: {msg.errorCode}
                                  </Badge>
                                  {msg.errorDetail && (
                                    <span className="text-[10px] text-red-500 max-w-[300px] break-all leading-tight">
                                      {msg.errorDetail}
                                    </span>
                                  )}
                                </div>
                              )}
                              <div className="flex gap-0.5 ml-1">
                                <button
                                  onClick={() => handleTestFeedback(currentTestSession!.id, msg.id, 'good')}
                                  className="text-xs text-gray-400 hover:text-green-500 transition-colors"
                                  title="好评"
                                >👍</button>
                                <button
                                  onClick={() => handleTestFeedback(currentTestSession!.id, msg.id, 'bad')}
                                  className="text-xs text-gray-400 hover:text-red-500 transition-colors"
                                  title="差评"
                                >👎</button>
                              </div>
                              <span className="text-[10px] text-gray-400">
                                {msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}

                  {testLoading && (
                    <div className="flex justify-start">
                      <div className="bg-gray-100 rounded-lg px-3 py-2">
                        <div className="flex items-center gap-2">
                          <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-gray-400" />
                          <span className="text-xs text-muted-foreground">AI 客服回复中...</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {activeTestSession && (
                  <div className="border-t p-3">
                    <form onSubmit={sendTestMessage} className="flex gap-2">
                      <Input
                        value={testInput}
                        onChange={(e) => setTestInput(e.target.value)}
                        placeholder="扮演买家输入消息..."
                        disabled={testLoading}
                        className="flex-1 text-sm"
                      />
                      <Button type="submit" size="sm" disabled={!testInput.trim() || testLoading}>
                        发送
                      </Button>
                    </form>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </section>

      {/* ── 低分回复审核队列 ── */}
      <section>
        <h2 className="text-lg font-semibold mb-3">低分回复审核队列</h2>
        <Card>
          <CardContent className="p-0">
            {qualityLoading ? (
              <div className="p-4 space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="px-4 py-3">
                    <Skeleton className="h-4 w-48 mb-2" />
                    <Skeleton className="h-3 w-full mb-2" />
                    <Skeleton className="h-3 w-3/4" />
                  </div>
                ))}
              </div>
            ) : qualityQueue.length === 0 ? (
              <div className="py-8 text-center text-muted-foreground text-sm">
                <div className="text-2xl mb-2">✅</div>
                暂无需要审核的低分回复
              </div>
            ) : (
              <div className="divide-y">
                {qualityQueue.map((item, index) => (
                  <div key={`${item.queue_type}-${item.session_id}-${index}`} className="px-4 py-4">
                    {(() => {
                      const issueKey = buildQualityIssueKey(item);
                      const statusRecord = qualityStatuses[`customer_service_quality::${issueKey}`];
                      const knowledgeLink = `/knowledge?category=${encodeURIComponent('客服修复')}&question=${encodeURIComponent(item.user_message || item.reason || '客服常见问题')}&answer=${encodeURIComponent(item.ai_reply || item.reason || '')}`;
                      const knowledgeQueued = queuedKnowledgeKeys[issueKey];
                      return (
                        <>
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <Badge variant={item.queue_type === 'bad_feedback' ? 'destructive' : 'secondary'}>
                            {item.queue_type === 'bad_feedback' ? '差评反馈' : '低分回复'}
                          </Badge>
                          <Badge variant={statusRecord?.status === 'resolved' ? 'default' : 'outline'}>
                            {getIssueStatusText(statusRecord?.status)}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            会话 {item.session_id ? item.session_id.slice(-8) : '未知'}
                          </span>
                        </div>
                        <div className="text-sm font-medium text-slate-900">{item.reason || '需要人工复核'}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-sm font-semibold text-slate-900">{item.score.toFixed(2)}</div>
                        <div className="text-xs text-muted-foreground">{formatTime(item.created_at)}</div>
                      </div>
                    </div>
                    {item.user_message && (
                      <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                        <div className="font-medium text-slate-900">用户问题</div>
                        <div className="mt-1 line-clamp-2">{item.user_message}</div>
                      </div>
                    )}
                    {item.ai_reply && (
                      <div className="mt-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
                        <div className="font-medium">AI 回复</div>
                        <div className="mt-1 line-clamp-3">{item.ai_reply}</div>
                      </div>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={savingIssueKey === issueKey}
                        onClick={() => handleQualityStatusChange(item, 'acknowledged')}
                      >
                        已知晓
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={savingIssueKey === issueKey}
                        onClick={() => handleQualityStatusChange(item, 'resolved')}
                      >
                        已修复
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={savingIssueKey === issueKey}
                        onClick={() => handleQualityStatusChange(item, 'ignored')}
                      >
                        忽略
                      </Button>
                      <a
                        href={knowledgeLink}
                        className="inline-flex items-center rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800 hover:bg-amber-100"
                      >
                        沉淀为 FAQ
                      </a>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={knowledgeQueued || queueingKnowledgeKey === issueKey}
                        onClick={() => handleQueueKnowledgeRepair(item)}
                      >
                        {knowledgeQueued ? '已加入知识修复' : queueingKnowledgeKey === issueKey ? '加入中...' : '加入知识修复'}
                      </Button>
                    </div>
                        </>
                      );
                    })()}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

export default withErrorBoundary(CustomerServicePage);
