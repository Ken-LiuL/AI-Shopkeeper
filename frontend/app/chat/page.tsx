'use client';
import { useState, useRef, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { AICapabilityHeader } from '@/components/ai-capability-badge';
import { withErrorBoundary } from '@/components/error-boundary';
import { fetchAPI } from '@/lib/api';

// ── Types ─────────────────────────────────────────────────────

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  intent?: string;
  needsHuman?: boolean;
}

interface BossCapability {
  id: string;
  name: string;
  icon: string;
  example: string;
}

// ── Helpers ───────────────────────────────────────────────────

function generateSessionId() {
  return 'boss_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

const INTENT_LABELS: Record<string, string> = {
  sales_analysis: '📊 销量分析',
  inventory: '📦 库存管理',
  competitors: '🏪 竞品监控',
  pricing: '💰 定价建议',
  selection: '🎯 选品推荐',
  alerts: '🔔 预警处理',
  cs_management: '💬 客服管理',
  reports: '📈 经营报告',
  general: '💬 通用咨询',
};

function getIntentLabel(intent?: string): string | null {
  if (!intent) return null;
  return INTENT_LABELS[intent] ?? `💬 ${intent}`;
}

// ── Quick Actions ─────────────────────────────────────────────

const QUICK_ACTIONS = [
  { text: '今天经营数据怎么样', icon: '📊' },
  { text: '哪些商品快断货了', icon: '📦' },
  { text: '竞品最近有什么价格变化', icon: '🏪' },
  { text: '本周有什么需要处理的预警', icon: '🔔' },
  { text: '帮我看看最近的客户评价', icon: '⭐' },
  { text: '给我定价建议', icon: '💰' },
];

// ── Typing Effect ─────────────────────────────────────────────

function TypingMessage({ text, onDone }: { text: string; onDone?: () => void }) {
  const [displayed, setDisplayed] = useState('');
  const indexRef = useRef(0);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);
  const onDoneRef = useRef(onDone);

  useEffect(() => {
    onDoneRef.current = onDone;
  });

  const CHAR_INTERVAL = 18;

  useEffect(() => {
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

// ── Capabilities Panel ────────────────────────────────────────

function CapabilitiesPanel({ onSelect }: { onSelect: (example: string) => void }) {
  const [caps, setCaps] = useState<BossCapability[]>([]);

  useEffect(() => {
    fetchAPI<BossCapability[]>('/boss/capabilities')
      .then(setCaps)
      .catch(() => {});
  }, []);

  if (caps.length === 0) return null;

  return (
    <Card className="mb-3">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">🎯 我能帮您做什么</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2">
        {caps.map((cap) => (
          <button
            key={cap.id}
            onClick={() => onSelect(cap.example)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-left border border-gray-100 hover:bg-blue-50 hover:border-blue-200 transition-colors"
          >
            <span className="text-base">{cap.icon}</span>
            <div>
              <div className="font-medium text-gray-700">{cap.name}</div>
              <div className="text-gray-400 truncate">{cap.example}</div>
            </div>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

// ── Main Component ────────────────────────────────────────────

function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '老板好！我是 AI 店长助手，您的专属经营顾问 📊\n\n我可以帮您分析销量、查库存预警、监控竞品、给定价建议、推荐选品……有什么想了解的？',
      timestamp: new Date(),
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentSessionId] = useState<string>(() => generateSessionId());
  const [latestAiMessageId, setLatestAiMessageId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

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
      const response = await fetchAPI<{
        session_id: string;
        reply: string;
        intent?: string;
        needs_human?: boolean;
      }>('/boss/chat', {
        method: 'POST',
        body: JSON.stringify({
          session_id: currentSessionId,
          message: userMessage.content,
        }),
      });

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.reply,
        timestamp: new Date(),
        intent: response.intent,
        needsHuman: response.needs_human,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setLatestAiMessageId(assistantMessage.id);
    } catch {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: '抱歉，发送消息时出现错误，请稍后重试。',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      setLatestAiMessageId(null);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleQuickAction = (text: string) => {
    setInputText(text);
    inputRef.current?.focus();
  };

  return (
    <div className="h-[calc(100vh-7rem)] flex flex-col space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">🤖 AI 店长助手</h1>
          <AICapabilityHeader
            capabilities={['DeepSeek 经营分析', '实时数据接入', '智能意图识别', '多轮对话记忆']}
            description="您的智能经营顾问 — 数据分析、库存管理、定价建议、竞品监控"
          />
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-6 min-h-0">
        {/* Left Sidebar */}
        <div className="lg:col-span-1 flex flex-col gap-3 min-h-0 overflow-y-auto">
          <CapabilitiesPanel onSelect={handleQuickAction} />

          {/* Session Info */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">💡 使用提示</CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-muted-foreground space-y-2">
              <p>直接用自然语言提问，例如：</p>
              <ul className="space-y-1 list-disc list-inside">
                <li>今天销量比昨天如何？</li>
                <li>哪些商品库存快不够了？</li>
                <li>竞品最近降价了吗？</li>
                <li>血压计应该定什么价？</li>
              </ul>
              <p className="text-gray-400 pt-1">数据基于店铺实时数据，结论直接可用。</p>
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
                  经营顾问对话
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
                  const intentLabel = isAI ? getIntentLabel(message.intent) : null;

                  return (
                    <div
                      key={message.id}
                      className={`flex ${isAI ? 'justify-start' : 'justify-end'}`}
                    >
                      <div className="max-w-[80%]">
                        {/* Message bubble */}
                        <div
                          className={`rounded-lg px-4 py-3 ${
                            isAI ? 'bg-muted' : 'bg-blue-500 text-white'
                          }`}
                        >
                          <div className="text-sm whitespace-pre-wrap">
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
                        </div>

                        {/* AI message meta */}
                        {isAI && intentLabel && (
                          <div className="mt-1.5 flex items-center gap-2 px-1">
                            <Badge variant="outline" className="text-xs h-5 px-1.5 font-normal">
                              {intentLabel}
                            </Badge>
                          </div>
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
                        <span className="text-sm text-muted-foreground">AI 店长正在分析...</span>
                      </div>
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>

              {/* Quick Actions */}
              <div className="flex gap-2 px-4 py-2 border-t overflow-x-auto shrink-0">
                {QUICK_ACTIONS.map(({ text, icon }) => (
                  <Button
                    key={text}
                    variant="outline"
                    size="sm"
                    className="shrink-0 text-xs"
                    onClick={() => handleQuickAction(text)}
                    disabled={loading}
                  >
                    {icon} {text}
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
                    placeholder="老板，有什么想了解的？"
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
                  AI 店长助手基于店铺实时数据，给出专业经营建议。按 Enter 发送消息。
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
