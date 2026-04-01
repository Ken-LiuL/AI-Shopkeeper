'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { usePathname } from 'next/navigation';
import { fetchAPI } from '@/lib/api';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

const PAGE_CONTEXT_MAP: Record<string, string> = {
  '/alerts': '我在看告警页面',
  '/selection': '我在看重点运营候选池页面',
  '/bundles': '我在看套餐候选池页面',
  '/listing': '我在看已暂停的上架页面',
  '/pricing': '我在看价格复核页面',
  '/chat': '我在看AI客服页面',
  '/competitors': '我在看未启用的竞品页面',
  '/imports': '我在看数据导入页面',
  '/settings/sync': '我在看数据导入页面',
  '/products': '我在看商品修复页面',
  '/orders': '我在看异常订单页面',
  '/inventory': '我在看库存修复页面',
};

function getPageContext(pathname: string): string {
  for (const [path, ctx] of Object.entries(PAGE_CONTEXT_MAP)) {
    if (pathname.startsWith(path)) return ctx;
  }
  return '';
}

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export function AIAssistantFAB() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: '您好，我会基于当前真实导入的数据回答经营问题。没有真实数据支撑的内容，我会直接说明。',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const pathname = usePathname();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const sessionIdRef = useRef<string>('fab_' + generateId());

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    if (open) {
      scrollToBottom();
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open, messages, scrollToBottom]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const pageCtx = getPageContext(pathname ?? '');
    const userContent = pageCtx ? `[${pageCtx}] ${text}` : text;

    const userMsg: Message = { id: generateId(), role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const response = await fetchAPI<{ reply?: string; message?: string; response?: string }>(
        '/customer-service/chat',
        {
          method: 'POST',
          body: JSON.stringify({
            message: userContent,
            session_id: sessionIdRef.current,
          }),
        }
      );
      const reply =
        response.reply ?? response.message ?? response.response ?? '抱歉，我暂时无法回答这个问题。';
      const assistantMsg: Message = { id: generateId(), role: 'assistant', content: reply };
      setMessages(prev => [...prev, assistantMsg]);
    } catch {
      const errMsg: Message = {
        id: generateId(),
        role: 'assistant',
        content: '抱歉，服务暂时不可用，请稍后再试。',
      };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* FAB Button */}
      <button
        onClick={() => setOpen(v => !v)}
        aria-label="打开AI助手"
        className={`fixed bottom-6 right-6 w-14 h-14 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full shadow-lg hover:shadow-xl transition-all duration-300 z-50 flex items-center justify-center text-white text-2xl ${open ? '' : 'animate-pulse'} hover:animate-none`}
      >
        {open ? '✕' : '🤖'}
      </button>

      {/* Chat Window */}
      {open && (
        <div className="fixed bottom-24 right-6 w-96 h-[500px] bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col z-50 overflow-hidden">
          {/* Header */}
          <div className="bg-gradient-to-r from-blue-500 to-purple-600 text-white px-4 py-3 flex items-start justify-between flex-shrink-0">
            <div>
              <div className="font-bold">🤖 AI 店长助手</div>
              <div className="text-xs text-blue-100">随时为您解答经营问题</div>
            </div>
            <button
              onClick={() => setOpen(false)}
              aria-label="关闭"
              className="text-white/80 hover:text-white text-lg leading-none mt-0.5"
            >
              ✕
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.map(msg => (
              <div
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-gradient-to-r from-blue-500 to-purple-600 text-white rounded-br-sm'
                      : 'bg-gray-100 text-gray-800 rounded-bl-sm'
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 text-gray-500 rounded-2xl rounded-bl-sm px-3 py-2 text-sm">
                  <span className="inline-flex gap-1">
                    <span className="animate-bounce" style={{ animationDelay: '0ms' }}>•</span>
                    <span className="animate-bounce" style={{ animationDelay: '150ms' }}>•</span>
                    <span className="animate-bounce" style={{ animationDelay: '300ms' }}>•</span>
                  </span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="border-t border-gray-100 p-3 flex gap-2 flex-shrink-0 bg-white">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入问题，按 Enter 发送…"
              disabled={loading}
              className="flex-1 text-sm border border-gray-200 rounded-xl px-3 py-2 outline-none focus:ring-2 focus:ring-blue-300 focus:border-transparent disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={loading || !input.trim()}
              className="bg-gradient-to-r from-blue-500 to-purple-600 text-white rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-40 hover:opacity-90 transition-opacity flex-shrink-0"
            >
              发送
            </button>
          </div>
        </div>
      )}
    </>
  );
}
