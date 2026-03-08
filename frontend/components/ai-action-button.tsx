'use client';

import { useState } from 'react';

export interface AIActionButtonProps {
  label: string;         // e.g. "采纳建议" / "立即调价" / "创建套餐"
  onAction: () => void | Promise<void>;
  variant?: 'primary' | 'secondary';
  loading?: boolean;
  confirmed?: boolean;   // externally controlled "already done" state
  disabled?: boolean;
  className?: string;
}

/**
 * Two-step confirmation button:
 *   Idle  → click → Confirm state
 *   Confirm → click → executes onAction()
 *   After execution → shows ✅ 已采纳 (or resets on error)
 */
export function AIActionButton({
  label,
  onAction,
  variant = 'primary',
  loading: externalLoading = false,
  confirmed = false,
  disabled = false,
  className = '',
}: AIActionButtonProps) {
  const [phase, setPhase] = useState<'idle' | 'confirm' | 'running' | 'done'>('idle');

  // Externally confirmed overrides local state
  const isDone = confirmed || phase === 'done';
  const isRunning = externalLoading || phase === 'running';

  const handleClick = async () => {
    if (isDone || isRunning || disabled) return;

    if (phase === 'idle') {
      setPhase('confirm');
      return;
    }

    // phase === 'confirm' → execute
    setPhase('running');
    try {
      await onAction();
      setPhase('done');
    } catch {
      setPhase('idle'); // reset on error so user can retry
    }
  };

  const handleCancel = (e: React.MouseEvent) => {
    e.stopPropagation();
    setPhase('idle');
  };

  if (isDone) {
    return (
      <span className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-green-700 bg-green-100 rounded-md ${className}`}>
        ✅ 已采纳
      </span>
    );
  }

  const baseStyle =
    variant === 'primary'
      ? 'bg-blue-600 hover:bg-blue-700 text-white border-transparent'
      : 'bg-white hover:bg-gray-50 text-gray-700 border-gray-300';

  const confirmStyle = 'bg-orange-500 hover:bg-orange-600 text-white border-transparent';

  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      <button
        onClick={handleClick}
        disabled={disabled || isRunning}
        className={`
          inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-md border
          transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed
          ${phase === 'confirm' ? confirmStyle : baseStyle}
        `}
      >
        {isRunning ? (
          <>
            <span className="animate-spin inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full"></span>
            执行中...
          </>
        ) : phase === 'confirm' ? (
          '确认执行？'
        ) : (
          label
        )}
      </button>

      {phase === 'confirm' && !isRunning && (
        <button
          onClick={handleCancel}
          className="px-2 py-1.5 text-xs text-gray-500 hover:text-gray-700 rounded-md hover:bg-gray-100 transition-colors"
        >
          取消
        </button>
      )}
    </span>
  );
}
