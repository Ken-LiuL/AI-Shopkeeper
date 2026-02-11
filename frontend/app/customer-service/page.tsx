'use client';
import { useEffect, useState, useRef, useCallback } from 'react';
import { Header } from '@/components/layout/header';
import { ChatBubble } from '@/components/ui/chat-bubble';
import { Loading } from '@/components/ui/loading';
import { sendChatMessage, getChatSessions, getChatHistory, createChatSession, deleteChatSession } from '@/lib/api';
import type { ChatMessage, ChatSession } from '@/lib/types';

export default function CustomerServicePage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => { scrollToBottom(); }, [messages]);

  const loadSessions = useCallback(async () => {
    try {
      const res = await getChatSessions();
      setSessions(res.data || []);
    } catch {} finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  const loadHistory = async (sessionId: string) => {
    setActiveSession(sessionId);
    try {
      const res = await getChatHistory(sessionId);
      setMessages(res.data?.messages || []);
    } catch {
      setMessages([]);
    }
  };

  const ensureSession = async (): Promise<string> => {
    if (activeSession) return activeSession;
    const res = await createChatSession();
    const newId = res.data.session_id;
    setActiveSession(newId);
    loadSessions();
    return newId;
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;

    const userMsg: ChatMessage = { role: 'user', content: text, timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setSending(true);

    try {
      const sessionId = await ensureSession();
      const res = await sendChatMessage(text, sessionId);
      const data = res.data;
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: data.reply,
        intent: data.intent,
        confidence: data.confidence,
        timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      loadSessions();
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: '⚠️ 请求失败，请稍后重试。' }]);
    } finally {
      setSending(false);
    }
  };

  const handleNewChat = async () => {
    setActiveSession(null);
    setMessages([]);
    setInput('');
  };

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteChatSession(sessionId);
      if (activeSession === sessionId) {
        setActiveSession(null);
        setMessages([]);
      }
      loadSessions();
    } catch {}
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="h-screen flex flex-col">
      <Header title="智能客服" />
      <div className="flex flex-1 overflow-hidden">
        {/* Session list */}
        <div className="w-72 border-r border-white/[0.08] flex flex-col bg-[#0c0c0c]">
          <div className="p-3">
            <button
              onClick={handleNewChat}
              className="w-full px-4 py-2.5 rounded-lg border border-white/[0.08] text-sm text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2"
            >
              <span>✨</span> 新对话
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
            {loadingSessions ? (
              <Loading text="加载会话..." />
            ) : sessions.length === 0 ? (
              <p className="text-center text-gray-600 text-xs py-8">暂无历史对话</p>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.session_id}
                  onClick={() => loadHistory(s.session_id)}
                  className={`group w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer flex items-center ${
                    activeSession === s.session_id
                      ? 'bg-amber-500/10 text-amber-400'
                      : 'text-gray-400 hover:bg-white/[0.04] hover:text-white'
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="truncate font-medium">{s.last_message || '新对话'}</div>
                    <div className="truncate text-xs text-gray-600 mt-0.5">
                      {s.message_count} 条消息
                    </div>
                  </div>
                  <button
                    onClick={(e) => handleDeleteSession(s.session_id, e)}
                    className="opacity-0 group-hover:opacity-100 ml-2 text-gray-500 hover:text-red-400 transition-all text-xs"
                    title="删除会话"
                  >
                    ✕
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Chat area */}
        <div className="flex-1 flex flex-col">
          <div className="flex-1 overflow-y-auto p-6">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center gap-4">
                <span className="text-5xl">💬</span>
                <h3 className="text-white font-semibold text-lg">AI 智能客服</h3>
                <p className="text-gray-500 text-sm max-w-md text-center">
                  你可以问我关于商品、订单、库存、配送等任何问题。我会根据店铺数据为你提供精准回答。
                </p>
                <div className="flex flex-wrap gap-2 mt-2">
                  {['今天销量怎么样？', '库存不足的商品有哪些？', '推荐一个促销方案'].map((q) => (
                    <button
                      key={q}
                      onClick={() => { setInput(q); }}
                      className="px-3 py-1.5 rounded-full border border-white/[0.08] text-xs text-gray-400 hover:text-amber-400 hover:border-amber-500/30 transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.map((msg, i) => (
                  <ChatBubble
                    key={i}
                    role={msg.role as 'user' | 'assistant'}
                    content={msg.content}
                    intent={msg.intent}
                    confidence={msg.confidence}
                    timestamp={msg.timestamp}
                  />
                ))}
                {sending && (
                  <div className="flex justify-start mb-4">
                    <div className="bg-[#1e1e1e] border border-white/[0.08] rounded-2xl rounded-bl-md px-4 py-3">
                      <div className="flex gap-1.5">
                        <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                        <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                        <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          {/* Input */}
          <div className="border-t border-white/[0.08] p-4">
            <div className="flex gap-3 items-end max-w-4xl mx-auto">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
                rows={1}
                className="flex-1 bg-[#1a1a1a] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 outline-none focus:border-amber-500/50 resize-none max-h-32"
                style={{ minHeight: '44px' }}
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || sending}
                className="px-4 py-3 bg-amber-500 hover:bg-amber-600 text-black rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
              >
                发送
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
