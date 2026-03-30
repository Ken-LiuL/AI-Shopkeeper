'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type OnboardingStep = {
  id: 'import' | 'discover' | 'alert' | 'pricing';
  title: string;
  description: string;
  href: string;
  actionLabel: string;
};

const STORAGE_KEY = 'ai-shopkeeper-onboarding-10min-steps';
const COMPLETED_KEY = 'ai-shopkeeper-onboarding-10min-completed';

const STEPS: OnboardingStep[] = [
  {
    id: 'import',
    title: '1. 导入样例数据',
    description: '先把商品/订单/库存数据导入，系统才会生成可执行的经营动作。',
    href: '/settings/sync',
    actionLabel: '去导入数据',
  },
  {
    id: 'discover',
    title: '2. 查看今日 3 件事',
    description: '回到 AI 指挥台，确认系统给出的今日优先动作。',
    href: '/',
    actionLabel: '去看今日动作',
  },
  {
    id: 'alert',
    title: '3. 处理一个预警',
    description: '进入预警页，关闭一个高风险预警，完成一次真实执行。',
    href: '/alerts',
    actionLabel: '去处理预警',
  },
  {
    id: 'pricing',
    title: '4. 应用一个定价建议',
    description: '进入价格复核，执行一条建议，完成动作闭环。',
    href: '/pricing',
    actionLabel: '去应用建议',
  },
];

export default function OnboardingPage() {
  const router = useRouter();
  const [completed, setCompleted] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        setCompleted(JSON.parse(raw));
      }
    } catch {
      setCompleted({});
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(completed));
    const allDone = STEPS.every((step) => completed[step.id]);
    localStorage.setItem(COMPLETED_KEY, allDone ? 'true' : 'false');
  }, [completed]);

  const doneCount = useMemo(
    () => STEPS.filter((step) => completed[step.id]).length,
    [completed]
  );

  const handleStartStep = (step: OnboardingStep) => {
    const next = { ...completed, [step.id]: true };
    setCompleted(next);
    router.push(step.href);
  };

  const handleReset = () => {
    const empty = {};
    setCompleted(empty);
    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(empty));
      localStorage.setItem(COMPLETED_KEY, 'false');
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-3">
        <Badge variant="outline" className="text-xs">🚀 10分钟试用闭环</Badge>
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">新用户快速上手</h1>
        <p className="text-sm text-slate-600">
          按顺序完成 4 步：导入数据 → 发现问题 → 执行动作 → 看到结果。
          <span className="ml-2 font-medium text-slate-800">已完成 {doneCount} / {STEPS.length}</span>
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {STEPS.map((step) => {
          const done = Boolean(completed[step.id]);
          return (
            <Card key={step.id} className={cn('border-slate-200', done && 'border-emerald-200 bg-emerald-50/30')}>
              <CardHeader className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-lg">{step.title}</CardTitle>
                  {done ? <Badge className="bg-emerald-100 text-emerald-800">已完成</Badge> : <Badge variant="outline">待完成</Badge>}
                </div>
                <CardDescription>{step.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button onClick={() => handleStartStep(step)} className="w-full">
                  {done ? '再次进入' : step.actionLabel}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={() => router.push('/')}>
          返回 AI 指挥台
        </Button>
        <Button variant="ghost" onClick={handleReset}>
          重置进度
        </Button>
      </div>
    </div>
  );
}
