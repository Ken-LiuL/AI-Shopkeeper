'use client';

import { useState } from 'react';

export interface ReasoningStep {
  icon: string;
  title: string;
  detail: string;
  status: 'completed' | 'running' | 'pending';
}

export interface AIReasoningPanelProps {
  steps: ReasoningStep[];
  confidence?: number; // 0-100
  reflectionRounds?: number;
  isExpanded?: boolean;
  className?: string;
}

const statusIcon = (status: ReasoningStep['status']) => {
  switch (status) {
    case 'completed': return '✅';
    case 'running':   return '⏳';
    case 'pending':   return '⬜';
  }
};

const statusColor = (status: ReasoningStep['status']) => {
  switch (status) {
    case 'completed': return 'text-green-700 bg-green-50 border-green-200';
    case 'running':   return 'text-blue-700 bg-blue-50 border-blue-200';
    case 'pending':   return 'text-gray-400 bg-gray-50 border-gray-200';
  }
};

export function AIReasoningPanel({
  steps,
  confidence,
  reflectionRounds,
  isExpanded: defaultExpanded = false,
  className = '',
}: AIReasoningPanelProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const completedCount = steps.filter(s => s.status === 'completed').length;
  const allDone = completedCount === steps.length && steps.length > 0;

  return (
    <div className={`rounded-lg border border-gray-200 bg-gray-50 text-sm ${className}`}>
      {/* Collapsed header – always visible */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-gray-100 rounded-lg transition-colors"
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-2 text-gray-600 font-medium">
          <span className="text-base">🤖</span>
          {allDone ? 'AI 分析完成' : 'AI 分析中'}
          {confidence != null && (
            <span className="text-xs text-green-700 bg-green-100 px-2 py-0.5 rounded-full font-semibold">
              信心度 {confidence}%
            </span>
          )}
          {reflectionRounds != null && reflectionRounds > 0 && (
            <span className="text-xs text-blue-700 bg-blue-100 px-2 py-0.5 rounded-full">
              自检 {reflectionRounds} 轮
            </span>
          )}
          <span className="text-xs text-gray-400 font-normal">· 查看推理过程</span>
        </span>
        <span className="text-gray-400 text-xs">{expanded ? '▲' : '▼'}</span>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="px-4 pb-4 pt-1">
          {/* Pipeline row */}
          <div className="flex flex-wrap items-center gap-1.5 mb-3">
            {steps.map((step, i) => (
              <span key={i} className="flex items-center gap-1">
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium ${statusColor(step.status)}`}
                >
                  {statusIcon(step.status)} {step.icon} {step.title}
                </span>
                {i < steps.length - 1 && (
                  <span className="text-gray-300 text-xs">→</span>
                )}
              </span>
            ))}
          </div>

          {/* Detail cards */}
          <div className="space-y-1.5">
            {steps.map((step, i) => (
              <div
                key={i}
                className={`flex items-start gap-2 px-3 py-2 rounded-md border text-xs ${statusColor(step.status)}`}
              >
                <span className="mt-0.5 shrink-0">{statusIcon(step.status)}</span>
                <div>
                  <span className="font-semibold">{step.icon} {step.title}：</span>
                  <span className="opacity-80">{step.detail}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Footer metrics */}
          {(confidence != null || (reflectionRounds != null && reflectionRounds > 0)) && (
            <div className="flex gap-4 mt-3 text-xs text-gray-500">
              {confidence != null && (
                <span>信心度：<strong className="text-green-700">{confidence}%</strong></span>
              )}
              {reflectionRounds != null && reflectionRounds > 0 && (
                <span>自检轮数：<strong className="text-blue-700">{reflectionRounds}</strong></span>
              )}
              <span>步骤：{completedCount}/{steps.length} 完成</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
