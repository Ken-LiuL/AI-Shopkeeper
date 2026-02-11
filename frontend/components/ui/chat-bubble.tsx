'use client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function ChatBubble({ role, content, intent, confidence, timestamp }: {
  role: 'user' | 'assistant';
  content: string;
  intent?: string;
  confidence?: number;
  timestamp?: string;
}) {
  const isUser = role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`max-w-[75%] ${isUser ? 'order-1' : 'order-1'}`}>
        <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-amber-500 text-black rounded-br-md'
            : 'bg-[#1e1e1e] border border-white/[0.08] text-gray-200 rounded-bl-md'
        }`}>
          {isUser ? (
            <p>{content}</p>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none prose-p:my-1 prose-pre:bg-black/30 prose-pre:border prose-pre:border-white/10 prose-code:text-amber-400">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          )}
        </div>
        <div className={`flex items-center gap-2 mt-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
          {timestamp && <span className="text-[10px] text-gray-600">{timestamp}</span>}
          {intent && (
            <span className="text-[10px] bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded">
              {intent}{confidence != null ? ` ${(confidence * 100).toFixed(0)}%` : ''}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
