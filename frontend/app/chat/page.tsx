'use client';
import { useState, useRef, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { withErrorBoundary } from '@/components/error-boundary';
import { fetchAPI, sendChatMessage } from '@/lib/api';
import type { ChatMessage, ChatResponse } from '@/lib/api';

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
}

interface Session {
  id: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
}

function generateSessionId() {
  return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: '您好！我是AI店长助手，可以帮助您解答客服问题、分析业务数据、提供经营建议等。请问有什么可以帮助您的吗？',
      timestamp: new Date(),
    }
  ]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => generateSessionId());

  // Session history state
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Load session list on mount
  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    setSessionsLoading(true);
    try {
      const data = await fetchAPI<any>('/customer-service/sessions');
      const list: Session[] = Array.isArray(data) ? data : data.sessions || [];
      setSessions(list);
    } catch (err) {
      console.error('Error loading sessions:', err);
      // silently fail - session list is non-critical
    } finally {
      setSessionsLoading(false);
    }
  };

  const handleNewSession = async () => {
    setCreatingSession(true);
    try {
      const data = await fetchAPI<any>('/customer-service/sessions', { method: 'POST' });
      const newId = data.id || data.session_id || generateSessionId();
      setCurrentSessionId(newId);
      setMessages([{
        id: 'welcome',
        role: 'assistant',
        content: '您好！我是AI店长助手，可以帮助您解答客服问题、分析业务数据、提供经营建议等。请问有什么可以帮助您的吗？',
        timestamp: new Date(),
      }]);
      await loadSessions();
    } catch (err) {
      console.error('Error creating session:', err);
      // Fallback: just create local session
      const newId = generateSessionId();
      setCurrentSessionId(newId);
      setMessages([{
        id: 'welcome',
        role: 'assistant',
        content: '您好！我是AI店长助手，可以帮助您解答客服问题、分析业务数据、提供经营建议等。请问有什么可以帮助您的吗？',
        timestamp: new Date(),
      }]);
    } finally {
      setCreatingSession(false);
    }
  };

  const handleSwitchSession = async (sessionId: string) => {
    if (sessionId === currentSessionId) return;
    setCurrentSessionId(sessionId);
    setLoading(true);
    try {
      const data = await fetchAPI<any>(`/customer-service/sessions/${sessionId}/messages`);
      const rawMessages = Array.isArray(data) ? data : data.messages || [];
      const restored: Message[] = rawMessages.map((m: any) => ({
        id: m.id || String(Date.now() + Math.random()),
        role: m.role || (m.is_user ? 'user' : 'assistant'),
        content: m.content || m.message || m.text || '',
        timestamp: m.created_at ? new Date(m.created_at) : new Date(),
        sources: m.sources,
        intent: m.intent,
        needsHuman: m.needs_human,
      }));
      setMessages(restored.length > 0 ? restored : [{
        id: 'welcome',
        role: 'assistant',
        content: '已切换到该会话。',
        timestamp: new Date(),
      }]);
    } catch (err) {
      console.error('Error loading session messages:', err);
      setMessages([{
        id: 'error',
        role: 'assistant',
        content: '加载会话历史失败，请稍后重试。',
        timestamp: new Date(),
      }]);
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

    setMessages(prev => [...prev, userMessage]);
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

      setMessages(prev => [...prev, assistantMessage]);
      // Refresh session list after new message
      loadSessions();
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: '抱歉，发送消息时出现错误。请稍后重试。',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const quickQuestions = [
    '今日销售情况如何？',
    '有哪些商品需要补货？',
    '客户满意度怎么样？',
    '竞争对手价格如何？',
    '推荐一些营销策略',
  ];

  const formatSessionTime = (dateStr?: string) => {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  return (
    <div className="h-[calc(100vh-7rem)] flex flex-col space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">AI 客服</h1>
          <p className="text-muted-foreground">智能助手帮您解答各种业务问题</p>
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-6 min-h-0">
        {/* Left Sidebar: Sessions + Quick Questions */}
        <div className="lg:col-span-1 flex flex-col gap-4 min-h-0">
          {/* Session History */}
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
                  {[1, 2, 3].map(i => (
                    <div key={i} className="h-12 bg-muted animate-pulse rounded"></div>
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

          {/* Quick Actions */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <span>⚡</span>
                快速提问
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {quickQuestions.map((question, index) => (
                <Button
                  key={index}
                  variant="outline"
                  className="w-full text-left h-auto py-2 px-3 text-sm"
                  onClick={() => setInputText(question)}
                  disabled={loading}
                >
                  {question}
                </Button>
              ))}
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
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex ${
                      message.role === 'user' ? 'justify-end' : 'justify-start'
                    }`}
                  >
                    <div
                      className={`max-w-[80%] rounded-lg px-4 py-3 ${
                        message.role === 'user'
                          ? 'bg-blue-500 text-white'
                          : 'bg-muted'
                      }`}
                    >
                      <div className="text-sm">{message.content}</div>
                      <div className="text-xs opacity-70 mt-2">
                        {message.timestamp.toLocaleTimeString('zh-CN', {
                          hour: '2-digit',
                          minute: '2-digit'
                        })}
                      </div>
                      {message.sources && message.sources.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-white/20">
                          <div className="text-xs opacity-70 mb-1">相关商品：</div>
                          <div className="space-y-1">
                            {message.sources.slice(0, 3).map((source, index) => (
                              <div key={index} className="text-xs bg-white/10 rounded p-2">
                                <div className="font-medium">{source.name}</div>
                                <div className="text-xs opacity-70">
                                  {source.category} | ¥{Number(source.price).toFixed(2)}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {message.needsHuman && (
                        <div className="mt-2 pt-2 border-t border-white/20">
                          <div className="text-xs text-yellow-200 flex items-center gap-1">
                            <span>⚠️</span>
                            建议转人工客服
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                {loading && (
                  <div className="flex justify-start">
                    <div className="bg-muted rounded-lg px-4 py-3 max-w-[80%]">
                      <div className="flex items-center space-x-2">
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-400"></div>
                        <span className="text-sm text-muted-foreground">AI 正在思考...</span>
                      </div>
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
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
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
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
