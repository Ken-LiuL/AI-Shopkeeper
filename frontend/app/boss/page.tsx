'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { sendBossMessage } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { withErrorBoundary } from '@/components/error-boundary';

// ── Types ─────────────────────────────────────────────────────

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  intent?: string;
}

// ── Quick Question Presets ────────────────────────────────────

const QUICK_QUESTIONS = [
  { label: '今天卖了多少钱？', icon: '💰' },
  { label: '哪些商品最好卖？', icon: '🏆' },
  { label: '库存不足的商品有哪些？', icon: '📦' },
  { label: '本周销售趋势如何？', icon: '📈' },
];

// ── Intent Badge ──────────────────────────────────────────────

const INTENT_LABELS: Record<string, string> = {
  sales_analysis: '📊 销售分析',
  inventory: '📦 库存',
  pricing: '💰 定价',
  selection: '🎯 选品',
  alerts: '🔔 预警',
  cs_management: '💬 客服',
  general: '💡 通用',
  error: '❌ 错误',
};

function IntentBadge({ intent }: { intent?: string }) {
  if (!intent || intent === 'general') return null;
  const label = INTENT_LABELS[intent] ?? intent;
  return (
    <span className="inline-block text-xs bg-blue-50 text-blue-600 border border-blue-100 rounded-full px-2 py-0.5 mb-2">
      {label}
    </span>
  );
}

// ── Message Bubble ────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0 ${
          isUser ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600'
        }`}
      >
        {isUser ? '👤' : '🤖'}
      </div>

      {/* Bubble */}
      <div className={`max-w-[80%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        {!isUser && <IntentBadge intent={msg.intent} />}
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? 'bg-blue-500 text-white rounded-tr-sm'
              : 'bg-white border border-gray-100 text-gray-800 rounded-tl-sm shadow-sm'
          }`}
        >
          {isUser ? (
            <p>{msg.content}</p>
          ) : (
            <div className="prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-900">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          )}
        </div>
        <span className="text-xs text-gray-400 mt-1 px-1">
          {msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>
    </div>
  );
}

// ── Loading Indicator ─────────────────────────────────────────

function ThinkingBubble() {
  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-sm flex-shrink-0">
        🤖
      </div>
      <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce [animation-delay:0ms]" />
          <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce [animation-delay:150ms]" />
          <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────

function BossAssistantPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '你好！我是你的 AI 经营顾问 🤖\n\n我可以帮你分析销售数据、库存状况、商品表现等经营问题。直接问我吧，或者选择下方的快捷问题。',
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => `boss-${Date.now()}`);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [input]);

  const sendMessage = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || loading) return;

      const userMsg: Message = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: question,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setInput('');
      setLoading(true);

      try {
        const res = await sendBossMessage({ session_id: sessionId, message: question });
        const assistantMsg: Message = {
          id: `ai-${Date.now()}`,
          role: 'assistant',
          content: res.reply || '（无回答）',
          timestamp: new Date(),
          intent: res.intent,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err) {
        const errorMsg: Message = {
          id: `err-${Date.now()}`,
          role: 'assistant',
          content: '⚠️ 请求失败，请检查网络后重试。',
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMsg]);
        console.error('[BossAssistant] sendMessage error:', err);
      } finally {
        setLoading(false);
      }
    },
    [loading, sessionId],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-500 rounded-xl flex items-center justify-center text-xl">
            🤖
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900">老板助手</h1>
            <p className="text-sm text-gray-500">用自然语言问任何经营问题</p>
          </div>
          <div className="ml-auto">
            <span className="inline-flex items-center gap-1.5 text-xs text-green-600 bg-green-50 border border-green-100 rounded-full px-3 py-1">
              <span className="w-1.5 h-1.5 bg-green-500 rounded-full" />
              AI 在线
            </span>
          </div>
        </div>
      </div>

      {/* Quick Questions */}
      <div className="bg-white border-b border-gray-100 px-6 py-3 flex-shrink-0">
        <div className="flex flex-wrap gap-2">
          {QUICK_QUESTIONS.map((q) => (
            <button
              key={q.label}
              onClick={() => sendMessage(q.label)}
              disabled={loading}
              className="inline-flex items-center gap-1.5 text-sm text-gray-600 bg-gray-50 hover:bg-blue-50 hover:text-blue-600 border border-gray-200 hover:border-blue-200 rounded-full px-3 py-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span>{q.icon}</span>
              <span>{q.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {loading && <ThinkingBubble />}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="bg-white border-t border-gray-200 px-6 py-4 flex-shrink-0">
        <div className="flex gap-3 items-end">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="问我任何经营问题... （Enter 发送，Shift+Enter 换行）"
              rows={1}
              disabled={loading}
              className="w-full resize-none rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-300 disabled:opacity-50 transition-all"
              style={{ minHeight: '48px', maxHeight: '160px' }}
            />
          </div>
          <Button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
            className="h-12 px-5 rounded-xl bg-blue-500 hover:bg-blue-600 text-white flex-shrink-0 transition-colors"
          >
            {loading ? (
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                思考中
              </span>
            ) : (
              '发送 ↑'
            )}
          </Button>
        </div>
        <p className="text-xs text-gray-400 mt-2 text-center">
          AI 回答基于实时经营数据，仅供参考。重要决策请结合实际情况判断。
        </p>
      </div>
    </div>
  );
}

export default withErrorBoundary(BossAssistantPage, '老板助手');
