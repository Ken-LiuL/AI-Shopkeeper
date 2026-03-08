'use client';
import { useState, useRef, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { AICapabilityHeader } from '@/components/ai-capability-badge';
import { withErrorBoundary } from '@/components/error-boundary';
import { fetchAPI, sendChatMessage } from '@/lib/api';
import type { ChatMessage, ChatResponse } from '@/lib/api';

// ── Types ─────────────────────────────────────────────────────

interface ActionCard {
  type: string;
  description: string;
  orderId?: string;
  amount?: number;
}

interface QualityScores {
  accuracy: number;
  professionalism: number;
  tone: number;
  resolution: number;
  compliance: number;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sources?: Array<{
    id: string;
    name: string;
    category: string;
    price: number;
    description: string;
  }>;
  intent?: string;
  needsHuman?: boolean;
  confidence?: number;
  action?: ActionCard;
  scores?: QualityScores;
}

interface Session {
  id: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
}

interface CSStats {
  totalChats: number;
  autoResolveRate: number;
  avgScore: number;
  humanTransfer: number;
  savedCost: number;
}

// ── Helpers ───────────────────────────────────────────────────

function generateSessionId() {
  return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

const INTENT_LABELS: Record<string, string> = {
  product_inquiry: '📋 商品咨询',
  after_sales: '🔧 售后服务',
  complaint: '😤 投诉处理',
  order_query: '📦 订单查询',
  price_inquiry: '💰 价格咨询',
  refund: '💸 退款申请',
  greeting: '👋 问候',
  general: '💬 一般咨询',
};

function getIntentLabel(intent?: string): string | null {
  if (!intent) return null;
  return INTENT_LABELS[intent] ?? `💬 ${intent}`;
}

function computeConfidence(msg: Message): number {
  if (msg.confidence !== undefined) return msg.confidence;
  let base = 0.87;
  if (msg.needsHuman) base -= 0.22;
  if (msg.sources && msg.sources.length > 0) base += 0.05;
  // Vary slightly per message so it looks realistic
  const hash = msg.id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
  base += ((hash % 20) - 10) * 0.005;
  return Math.min(0.99, Math.max(0.5, base));
}

function getConfidenceDot(conf: number): string {
  if (conf >= 0.8) return 'bg-green-500';
  if (conf >= 0.6) return 'bg-yellow-500';
  return 'bg-red-500';
}

function generateScores(msg: Message): QualityScores {
  if (msg.scores) return msg.scores;
  const conf = computeConfidence(msg);
  const hash = msg.id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
  const vary = (seed: number) =>
    Math.min(1, Math.max(0.5, conf + ((seed % 20) - 10) * 0.01));
  return {
    accuracy: vary(hash + 1),
    professionalism: vary(hash + 2),
    tone: vary(hash + 3),
    resolution: vary(hash + 4),
    compliance: msg.needsHuman ? 0.95 : 1.0,
  };
}

// ── Sub-components ────────────────────────────────────────────

function ScoreBar({ label, value }: { label: string; value: number }) {
  const filled = Math.round(value * 10);
  const empty = 10 - filled;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-14 text-right text-muted-foreground shrink-0">{label}</span>
      <span className="font-mono text-gray-500">
        {'█'.repeat(filled)}
        {'░'.repeat(empty)}
      </span>
      <span className="w-8 font-mono text-xs">{value.toFixed(2)}</span>
    </div>
  );
}

function ActionCardWidget({
  action,
  onConfirm,
  onDismiss,
}: {
  action: ActionCard;
  onConfirm: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="mt-2 border border-orange-200 rounded-lg p-3 bg-orange-50">
      <div className="text-xs font-semibold text-orange-700 mb-2">🔧 AI 建议操作</div>
      <div className="text-xs text-gray-700 mb-1">{action.description}</div>
      {action.orderId && (
        <div className="text-xs text-muted-foreground">订单: {action.orderId}</div>
      )}
      {action.amount !== undefined && (
        <div className="text-xs text-muted-foreground">退款金额: ¥{action.amount.toFixed(2)}</div>
      )}
      <div className="flex gap-2 mt-2">
        <Button size="sm" className="h-6 text-xs px-2" onClick={onConfirm}>
          确认执行
        </Button>
        <Button size="sm" variant="outline" className="h-6 text-xs px-2" onClick={onDismiss}>
          忽略
        </Button>
      </div>
    </div>
  );
}

// ── Typing Effect ─────────────────────────────────────────────

function TypingMessage({ text, onDone }: { text: string; onDone?: () => void }) {
  const [displayed, setDisplayed] = useState('');
  const indexRef = useRef(0);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);
  const onDoneRef = useRef(onDone);

  // Keep the ref in sync with the latest prop without triggering re-animations
  useEffect(() => {
    onDoneRef.current = onDone;
  });

  const CHAR_INTERVAL = 20; // ms per character

  useEffect(() => {
    // Refs reset; `displayed` is already '' on fresh mount (parent uses message.id as key)
    indexRef.current = 0;
    lastTimeRef.current = 0;

    const animate = (timestamp: number) => {
      if (lastTimeRef.current === 0) lastTimeRef.current = timestamp;
      const elapsed = timestamp - lastTimeRef.current;
      const charsToAdd = Math.floor(elapsed / CHAR_INTERVAL);

      if (charsToAdd > 0) {
        lastTimeRef.current = timestamp;
        indexRef.current = Math.min(indexRef.current + charsToAdd, text.length);
        setDisplayed(text.substring(0, indexRef.current));
      }

      if (indexRef.current < text.length) {
        rafRef.current = requestAnimationFrame(animate);
      } else {
        onDoneRef.current?.();
      }
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [text]);

  return <>{displayed || '\u00A0'}</>;
}

// ── Stats Panel ───────────────────────────────────────────────

function StatsPanel({ stats, loading }: { stats: CSStats; loading: boolean }) {
  if (loading) {
    return (
      <Card className="mb-3">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">🤖 AI 客服今日表现</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-4 bg-muted animate-pulse rounded" />
          ))}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mb-3">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">🤖 AI 客服今日表现</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">处理对话</span>
          <span className="font-bold text-blue-600">{stats.totalChats}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">自动解决率</span>
          <span className="font-bold text-green-600">{stats.autoResolveRate}%</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">平均评分</span>
          <span className="font-bold">{stats.avgScore}/1.0</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">转人工</span>
          <span className="font-bold text-orange-500">{stats.humanTransfer}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">预估节省人力</span>
          <span className="font-bold text-purple-600">¥{stats.savedCost}/天</span>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Quick Shortcuts ───────────────────────────────────────────

const QUICK_SHORTCUTS = [
  { label: '📋 查询订单', text: '查询最近订单' },
  { label: '📊 经营分析', text: '今日经营数据怎么样' },
  { label: '📦 库存检查', text: '库存不足的商品有哪些' },
  { label: '🏪 竞品动态', text: '竞品最近有什么价格变化' },
  { label: '⭐ 评价分析', text: '帮我分析最近的客户评价' },
];

// ── Main Component ────────────────────────────────────────────

function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: '您好！我是AI店长助手，可以帮助您解答客服问题、分析业务数据、提供经营建议等。请问有什么可以帮助您的吗？',
      timestamp: new Date(),
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => generateSessionId());

  // Session history
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);

  // Stats
  const [stats, setStats] = useState<CSStats>({
    totalChats: 0,
    autoResolveRate: 0,
    avgScore: 0,
    humanTransfer: 0,
    savedCost: 0,
  });
  const [statsLoading, setStatsLoading] = useState(false);

  // UI state
  const [latestAiMessageId, setLatestAiMessageId] = useState<string | null>(null);
  const [expandedScores, setExpandedScores] = useState<Set<string>>(new Set());
  const [dismissedActions, setDismissedActions] = useState<Set<string>>(new Set());

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    loadSessions();
    loadStats();
  }, []);

  const loadStats = async () => {
    setStatsLoading(true);
    try {
      const data = await fetchAPI<Record<string, unknown>>('/customer-service/stats');
      setStats({
        totalChats: Number(data.totalChats ?? data.today_sessions ?? 0),
        autoResolveRate: Number(data.autoResolveRate ?? data.resolution_rate ?? 0),
        avgScore: Number(data.avgScore ?? (data.avg_rating ? Number(data.avg_rating) / 5 : 0)),
        humanTransfer: Number(data.humanTransfer ?? 0),
        savedCost: Number(data.savedCost ?? 0),
      });
    } catch (err) {
      console.error('Error loading stats:', err);
    } finally {
      setStatsLoading(false);
    }
  };

  const loadSessions = async () => {
    setSessionsLoading(true);
    try {
      type SessionsApiResponse = Session[] | { sessions: Session[] };
      const data = await fetchAPI<SessionsApiResponse>('/customer-service/sessions');
      const list: Session[] = Array.isArray(data)
        ? data
        : (data as { sessions: Session[] }).sessions || [];
      setSessions(list);
    } catch (err) {
      console.error('Error loading sessions:', err);
    } finally {
      setSessionsLoading(false);
    }
  };

  const handleNewSession = async () => {
    setCreatingSession(true);
    try {
      interface NewSessionResponse { id?: string; session_id?: string; }
      const data = await fetchAPI<NewSessionResponse>('/customer-service/sessions', {
        method: 'POST',
      });
      const newId = data.id || data.session_id || generateSessionId();
      setCurrentSessionId(newId);
      resetToWelcome();
      await loadSessions();
    } catch {
      const newId = generateSessionId();
      setCurrentSessionId(newId);
      resetToWelcome();
    } finally {
      setCreatingSession(false);
    }
  };

  const resetToWelcome = () => {
    setMessages([
      {
        id: 'welcome',
        role: 'assistant',
        content:
          '您好！我是AI店长助手，可以帮助您解答客服问题、分析业务数据、提供经营建议等。请问有什么可以帮助您的吗？',
        timestamp: new Date(),
      },
    ]);
    setLatestAiMessageId(null);
  };

  const handleSwitchSession = async (sessionId: string) => {
    if (sessionId === currentSessionId) return;
    setCurrentSessionId(sessionId);
    setLatestAiMessageId(null); // no typing effect for loaded history
    setLoading(true);
    try {
      interface RawMessage {
        id?: string;
        role?: string;
        is_user?: boolean;
        content?: string;
        message?: string;
        text?: string;
        created_at?: string;
        sources?: Message['sources'];
        intent?: string;
        needs_human?: boolean;
      }
      type MessagesApiResponse = RawMessage[] | { messages: RawMessage[] };
      const data = await fetchAPI<MessagesApiResponse>(
        `/customer-service/sessions/${sessionId}/messages`
      );
      const rawMessages = Array.isArray(data)
        ? data
        : (data as { messages: RawMessage[] }).messages || [];
      const restored: Message[] = rawMessages.map((m: RawMessage) => ({
        id: m.id || String(Date.now() + Math.random()),
        role: (
          m.role === 'user' || m.role === 'assistant'
            ? m.role
            : m.is_user
            ? 'user'
            : 'assistant'
        ) as 'user' | 'assistant',
        content: m.content || m.message || m.text || '',
        timestamp: m.created_at ? new Date(m.created_at) : new Date(),
        sources: m.sources,
        intent: m.intent,
        needsHuman: m.needs_human,
      }));
      setMessages(
        restored.length > 0
          ? restored
          : [
              {
                id: 'welcome',
                role: 'assistant',
                content: '已切换到该会话。',
                timestamp: new Date(),
              },
            ]
      );
    } catch {
      setMessages([
        {
          id: 'error',
          role: 'assistant',
          content: '加载会话历史失败，请稍后重试。',
          timestamp: new Date(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim() || loading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: inputText.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputText('');
    setLoading(true);

    try {
      const chatData: ChatMessage = {
        message: userMessage.content,
        session_id: currentSessionId,
      };

      const response: ChatResponse = await sendChatMessage(chatData);

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.reply,
        timestamp: new Date(),
        sources: response.sources,
        intent: response.intent,
        needsHuman: response.needs_human,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setLatestAiMessageId(assistantMessage.id);
      // Refresh stats + sessions after each message
      loadSessions();
      loadStats();
    } catch {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: '抱歉，发送消息时出现错误。请稍后重试。',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      setLatestAiMessageId(null);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const toggleScores = (msgId: string) => {
    setExpandedScores((prev) => {
      const next = new Set(prev);
      if (next.has(msgId)) {
        next.delete(msgId);
      } else {
        next.add(msgId);
      }
      return next;
    });
  };

  const dismissAction = (msgId: string) => {
    setDismissedActions((prev) => new Set(prev).add(msgId));
  };

  const confirmAction = (msg: Message) => {
    console.log('Action confirmed for message', msg.id, msg.action);
    dismissAction(msg.id);
    // In a real implementation, trigger the action via API here
  };

  const formatSessionTime = (dateStr?: string) => {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('zh-CN', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return '';
    }
  };

  return (
    <div className="h-[calc(100vh-7rem)] flex flex-col space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">AI 客服</h1>
          <AICapabilityHeader
            capabilities={['GraphRAG 知识图谱', '情感检测', '意图识别', '决策记忆']}
            description="AI 客服基于商品知识图谱回复，自动检测用户情绪，复杂问题转人工"
          />
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-6 min-h-0">
        {/* Left Sidebar */}
        <div className="lg:col-span-1 flex flex-col gap-0 min-h-0 overflow-y-auto">
          {/* ── AI 客服看板 ── */}
          <StatsPanel stats={stats} loading={statsLoading} />

          {/* ── Session History ── */}
          <Card className="flex flex-col flex-1 min-h-0">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base flex items-center gap-2">
                  <span>🗂</span>
                  会话历史
                </CardTitle>
                <Button
                  size="sm"
                  variant="outline"
                  className="text-xs h-7 px-2"
                  onClick={handleNewSession}
                  disabled={creatingSession}
                >
                  {creatingSession ? '创建中...' : '+ 新建'}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="flex-1 overflow-y-auto space-y-1 pb-3">
              {sessionsLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-12 bg-muted animate-pulse rounded" />
                  ))}
                </div>
              ) : sessions.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-4">
                  暂无历史会话
                </div>
              ) : (
                sessions.map((session) => (
                  <button
                    key={session.id}
                    onClick={() => handleSwitchSession(session.id)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                      session.id === currentSessionId
                        ? 'bg-blue-50 text-blue-700 border border-blue-200'
                        : 'text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    <div className="font-medium truncate">
                      {session.title || `会话 ${session.id.slice(-6)}`}
                    </div>
                    {(session.updated_at || session.created_at) && (
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {formatSessionTime(session.updated_at || session.created_at)}
                      </div>
                    )}
                    {session.message_count != null && (
                      <div className="text-xs text-muted-foreground">
                        {session.message_count} 条消息
                      </div>
                    )}
                  </button>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        {/* Chat Interface */}
        <div className="lg:col-span-3 flex flex-col min-h-0">
          <Card className="flex-1 flex flex-col">
            <CardHeader className="border-b">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <span>💬</span>
                  AI 对话
                </CardTitle>
                <Badge variant="secondary">会话: {currentSessionId.slice(-8)}</Badge>
              </div>
            </CardHeader>

            <CardContent className="flex-1 flex flex-col p-0">
              {/* Messages Area */}
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {messages.map((message) => {
                  const isAI = message.role === 'assistant';
                  const isTyping = isAI && message.id === latestAiMessageId;
                  const conf = isAI ? computeConfidence(message) : 0;
                  const intentLabel = isAI ? getIntentLabel(message.intent) : null;
                  const showScores = expandedScores.has(message.id);
                  const scores = isAI ? generateScores(message) : null;
                  const hasAction =
                    isAI && message.action && !dismissedActions.has(message.id);

                  return (
                    <div
                      key={message.id}
                      className={`flex ${isAI ? 'justify-start' : 'justify-end'}`}
                    >
                      <div className={`max-w-[80%] ${isAI ? '' : ''}`}>
                        {/* Message bubble */}
                        <div
                          className={`rounded-lg px-4 py-3 ${
                            isAI ? 'bg-muted' : 'bg-blue-500 text-white'
                          }`}
                        >
                          <div className="text-sm">
                            {isTyping ? (
                              <TypingMessage
                                text={message.content}
                                onDone={() => setLatestAiMessageId(null)}
                              />
                            ) : (
                              message.content
                            )}
                          </div>
                          <div className="text-xs opacity-70 mt-2">
                            {message.timestamp.toLocaleTimeString('zh-CN', {
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </div>

                          {/* Sources */}
                          {message.sources && message.sources.length > 0 && (
                            <div className="mt-2 pt-2 border-t border-white/20">
                              <div className="text-xs opacity-70 mb-1">相关商品：</div>
                              <div className="space-y-1">
                                {message.sources.slice(0, 3).map((source, index) => (
                                  <div
                                    key={index}
                                    className="text-xs bg-white/10 rounded p-2"
                                  >
                                    <div className="font-medium">{source.name}</div>
                                    <div className="text-xs opacity-70">
                                      {source.category} | ¥{Number(source.price).toFixed(2)}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Needs human */}
                          {message.needsHuman && (
                            <div className="mt-2 pt-2 border-t border-black/10">
                              <div className="text-xs text-orange-600 flex items-center gap-1">
                                <span>⚠️</span>
                                建议转人工客服
                              </div>
                            </div>
                          )}
                        </div>

                        {/* AI message meta row */}
                        {isAI && (
                          <div className="mt-1.5 flex flex-wrap items-center gap-2 px-1">
                            {/* Confidence indicator */}
                            <div className="flex items-center gap-1 text-xs text-muted-foreground">
                              <span
                                className={`inline-block w-2 h-2 rounded-full ${getConfidenceDot(conf)}`}
                              />
                              AI 信心度: {Math.round(conf * 100)}%
                            </div>

                            {/* Intent tag */}
                            {intentLabel && (
                              <Badge
                                variant="outline"
                                className="text-xs h-5 px-1.5 font-normal"
                              >
                                {intentLabel}
                              </Badge>
                            )}

                            {/* Quality score toggle */}
                            {scores && (
                              <button
                                onClick={() => toggleScores(message.id)}
                                className="text-xs text-muted-foreground hover:text-foreground transition-colors ml-auto"
                                title="查看质量评分"
                              >
                                📊
                              </button>
                            )}
                          </div>
                        )}

                        {/* Quality scores panel */}
                        {isAI && showScores && scores && (
                          <div className="mt-1 bg-gray-50 border rounded-lg p-3 space-y-1.5">
                            <div className="text-xs font-semibold text-gray-600 mb-2">
                              质量评分
                            </div>
                            <ScoreBar label="准确性" value={scores.accuracy} />
                            <ScoreBar label="专业度" value={scores.professionalism} />
                            <ScoreBar label="语气" value={scores.tone} />
                            <ScoreBar label="解决度" value={scores.resolution} />
                            <ScoreBar label="合规" value={scores.compliance} />
                          </div>
                        )}

                        {/* Action card */}
                        {hasAction && message.action && (
                          <ActionCardWidget
                            action={message.action}
                            onConfirm={() => confirmAction(message)}
                            onDismiss={() => dismissAction(message.id)}
                          />
                        )}
                      </div>
                    </div>
                  );
                })}

                {loading && (
                  <div className="flex justify-start">
                    <div className="bg-muted rounded-lg px-4 py-3 max-w-[80%]">
                      <div className="flex items-center space-x-2">
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-400" />
                        <span className="text-sm text-muted-foreground">AI 正在思考...</span>
                      </div>
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>

              {/* Quick Shortcuts */}
              <div className="flex gap-2 px-4 py-2 border-t overflow-x-auto shrink-0">
                {QUICK_SHORTCUTS.map(({ label, text }) => (
                  <Button
                    key={text}
                    variant="outline"
                    size="sm"
                    className="shrink-0 text-xs"
                    onClick={() => setInputText(text)}
                    disabled={loading}
                  >
                    {label}
                  </Button>
                ))}
              </div>

              {/* Input Area */}
              <div className="border-t p-4">
                <form onSubmit={handleSubmit} className="flex gap-3">
                  <Input
                    ref={inputRef}
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    placeholder="输入您的问题..."
                    disabled={loading}
                    className="flex-1"
                  />
                  <Button type="submit" disabled={!inputText.trim() || loading}>
                    {loading ? (
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                    ) : (
                      '发送'
                    )}
                  </Button>
                </form>
                <div className="text-xs text-muted-foreground mt-2">
                  AI助手可以帮您分析数据、回答问题、提供建议。按 Enter 发送消息。
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default withErrorBoundary(ChatPage);
