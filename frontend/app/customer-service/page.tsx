'use client';
import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
              <Badge variant="secondary" className="text-xs">DeepSeek / Flash</Badge>
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
