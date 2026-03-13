'use client';
import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { withErrorBoundary } from '@/components/error-boundary';
import { fetchAPI } from '@/lib/api';

// ── Types ─────────────────────────────────────────────────────

interface CSStats {
  totalChats: number;
  autoResolveRate: number;
  avgScore: number;
  humanTransfer: number;
  savedCost: number;
  total_sessions?: number;
  today_sessions?: number;
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
  const [autoReplyEnabled, setAutoReplyEnabled] = useState(true);
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

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([loadStats(), loadSessions()]);
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
  }, []);

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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">💬 客服管理</h1>
          <p className="text-muted-foreground mt-1">
            AI 买家客服工作台 — 监控自动回复质量，管理对话历史
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

      {/* ── 系统状态 & 设置 ── */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 自动回复开关 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">⚙️ 自动回复设置</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">AI 自动回复</div>
                <div className="text-xs text-muted-foreground">接收美团 IM 消息并自动回复</div>
              </div>
              <button
                onClick={() => setAutoReplyEnabled((v) => !v)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  autoReplyEnabled ? 'bg-blue-500' : 'bg-gray-300'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    autoReplyEnabled ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">响应超时限制</span>
              <span className="font-mono text-xs">25 秒</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">转人工阈值</span>
              <span className="text-xs text-muted-foreground">投诉升级词 / 安全问题</span>
            </div>
            <div className="pt-1">
              <Badge variant={autoReplyEnabled ? 'default' : 'secondary'} className="text-xs">
                {autoReplyEnabled ? '✅ 运行中' : '⏸ 已暂停'}
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* 知识库管理 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">📚 知识库管理</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">商品知识</span>
              <span className="text-green-600">✅ 已同步</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">售后政策</span>
              <span className="text-green-600">✅ 最新</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">FAQ 库</span>
              <span className="text-green-600">✅ 已加载</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">向量索引</span>
              <span className="text-green-600">✅ Neo4j</span>
            </div>
          </CardContent>
        </Card>

        {/* 系统状态 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">🔧 系统状态</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">AI 引擎</span>
              <Badge variant="secondary" className="text-xs">Sonnet / Flash</Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">平台对接</span>
              <span className="text-green-600">✅ 美团 IM</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">回复语气</span>
              <span className="text-xs text-muted-foreground">亲~ 美团风格</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">数据权限</span>
              <span className="text-xs text-orange-500">仅商品/订单/售后</span>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── 模拟对话测试 ── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">🧪 模拟对话测试</h2>
          <Button variant="outline" size="sm" onClick={createTestSession} className="gap-1">
            ➕ 新建测试客户
          </Button>
        </div>

        {testSessions.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center">
              <div className="text-3xl mb-3">🧪</div>
              <div className="text-sm text-muted-foreground mb-4">
                模拟买家与 AI 客服对话，测试回复质量
              </div>
              <Button variant="outline" onClick={createTestSession}>
                ➕ 创建第一个测试客户
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4" style={{ minHeight: '400px' }}>
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
                                <Badge variant="outline" className="text-[10px] h-4 px-1 border-red-200 text-red-600">
                                  错误: {msg.errorCode}
                                </Badge>
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

      {/* ── 最近对话列表 ── */}
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

      {/* ── 低分回复审核队列（占位） ── */}
      <section>
        <h2 className="text-lg font-semibold mb-3">低分回复审核队列</h2>
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground text-sm">
            <div className="text-2xl mb-2">✅</div>
            暂无需要审核的低分回复（评分阈值：低于 0.7）
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

export default withErrorBoundary(CustomerServicePage);
