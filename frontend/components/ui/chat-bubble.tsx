'use client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useState } from 'react';

interface ChatBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  intent?: string;
  confidence?: number;
  timestamp?: string;
  images?: string[];
  messageId?: string;
  feedback?: 'good' | 'bad' | null;
  onFeedback?: (messageId: string, rating: 'good' | 'bad') => void;
}

export function ChatBubble({
  role,
  content,
  intent,
  confidence,
  timestamp,
  images = [],
  messageId,
  feedback,
  onFeedback
}: ChatBubbleProps) {
  const isUser = role === 'user';
  const [currentFeedback, setCurrentFeedback] = useState<'good' | 'bad' | null>(feedback || null);

  const handleFeedback = (rating: 'good' | 'bad') => {
    if (currentFeedback || !messageId || !onFeedback) return;
    setCurrentFeedback(rating);
    onFeedback(messageId, rating);
  };

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`max-w-[75%] ${isUser ? 'order-1' : 'order-1'}`}>
        <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-amber-500 text-black rounded-br-md'
            : 'bg-[#1e1e1e] border border-white/[0.08] text-gray-200 rounded-bl-md'
        }`}>
          {/* Images for user messages */}
          {isUser && images.length > 0 && (
            <div className="mb-3 grid grid-cols-2 gap-2">
              {images.map((img, idx) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={idx}
                  src={img.startsWith('data:') ? img : `data:image/jpeg;base64,${img}`}
                  alt={`Uploaded image ${idx + 1}`}
                  className="rounded-lg max-w-full h-auto max-h-32 object-cover"
                  loading="lazy"
                />
              ))}
            </div>
          )}

          {isUser ? (
            <p>{content}</p>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none prose-p:my-1 prose-pre:bg-black/30 prose-pre:border prose-pre:border-white/10 prose-code:text-amber-400">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          )}
        </div>

        {/* Metadata and feedback */}
        <div className={`flex items-center gap-2 mt-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
          {timestamp && <span className="text-[10px] text-gray-600">{timestamp}</span>}
          {intent && (
            <span className="text-[10px] bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded">
              {intent}{confidence != null ? ` ${(confidence * 100).toFixed(0)}%` : ''}
            </span>
          )}

          {/* Feedback buttons for assistant messages */}
          {!isUser && messageId && onFeedback && (
            <div className="flex gap-1 ml-2">
              <button
                onClick={() => handleFeedback('good')}
                disabled={currentFeedback !== null}
                className={`p-1 rounded-full text-xs transition-colors ${
                  currentFeedback === 'good'
                    ? 'text-green-400 bg-green-500/20'
                    : currentFeedback === 'bad'
                      ? 'text-gray-600 cursor-not-allowed'
                      : 'text-gray-500 hover:text-green-400 hover:bg-green-500/20'
                }`}
                title={currentFeedback ? '已反馈' : '好评'}
              >
                👍
              </button>
              <button
                onClick={() => handleFeedback('bad')}
                disabled={currentFeedback !== null}
                className={`p-1 rounded-full text-xs transition-colors ${
                  currentFeedback === 'bad'
                    ? 'text-red-400 bg-red-500/20'
                    : currentFeedback === 'good'
                      ? 'text-gray-600 cursor-not-allowed'
                      : 'text-gray-500 hover:text-red-400 hover:bg-red-500/20'
                }`}
                title={currentFeedback ? '已反馈' : '差评'}
              >
                👎
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
