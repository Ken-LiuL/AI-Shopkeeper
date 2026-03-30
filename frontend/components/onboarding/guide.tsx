'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

interface OnboardingStep {
  title: string;
  content: string;
  icon: string;
  action?: string;
  actionUrl?: string;
}

const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    title: '欢迎使用AI店长',
    content: 'AI店长是专为医疗器械即时零售设计的智能管理系统，帮助您提升经营效率，优化库存管理。',
    icon: '🤖',
  },
  {
    title: '查看今日待办',
    content: 'AI 指挥台会把导入后的真实数据转成今天最该处理的动作，例如断货热销、主档缺口和异常订单。',
    icon: '⚡',
    action: '查看AI指挥台',
    actionUrl: '/',
  },
  {
    title: '设置智能预警',
    content: '系统会自动监控缺货、异常订单、价格异常等问题，并提供具体的解决建议。',
    icon: '🔔',
    action: '查看预警',
    actionUrl: '/alerts',
  },
  {
    title: '使用AI客服',
    content: '点击"AI客服"即可咨询业务问题，如"血压计哪个型号卖得好？"、"今天销量为什么下降？"',
    icon: '💬',
    action: '体验AI客服',
    actionUrl: '/chat',
  },
  {
    title: '复核商品价格',
    content: '价格复核基于当前商品、订单和库存数据给出建议，帮助您先处理毛利过低、动销偏弱和库存积压商品。',
    icon: '💰',
    action: '查看价格复核',
    actionUrl: '/pricing',
  },
];

interface OnboardingGuideProps {
  onComplete?: () => void;
}

export function OnboardingGuide({ onComplete }: OnboardingGuideProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [isVisible, setIsVisible] = useState(() => {
    if (typeof window === 'undefined') return false;
    return !localStorage.getItem('ai-store-manager-onboarding-completed');
  });

  const handleNext = () => {
    if (currentStep < ONBOARDING_STEPS.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      handleComplete();
    }
  };

  const handlePrevious = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleComplete = () => {
    localStorage.setItem('ai-store-manager-onboarding-completed', 'true');
    setIsVisible(false);
    onComplete?.();
  };

  const handleSkip = () => {
    handleComplete();
  };

  const handleAction = () => {
    const step = ONBOARDING_STEPS[currentStep];
    if (step.actionUrl) {
      window.location.href = step.actionUrl;
    }
  };

  if (!isVisible) {
    return null;
  }

  const currentStepData = ONBOARDING_STEPS[currentStep];

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <Card className="max-w-md mx-4 shadow-xl">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <span className="text-2xl">{currentStepData.icon}</span>
              {currentStepData.title}
            </CardTitle>
            <Badge variant="outline">
              {currentStep + 1} / {ONBOARDING_STEPS.length}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground leading-relaxed">
            {currentStepData.content}
          </p>

          {currentStepData.action && (
            <Button
              onClick={handleAction}
              variant="outline"
              className="w-full"
            >
              {currentStepData.action}
            </Button>
          )}

          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              <Button
                onClick={handlePrevious}
                disabled={currentStep === 0}
                variant="ghost"
                size="sm"
              >
                上一步
              </Button>
              <Button onClick={handleSkip} variant="ghost" size="sm">
                跳过引导
              </Button>
            </div>

            <Button onClick={handleNext} size="sm">
              {currentStep === ONBOARDING_STEPS.length - 1 ? '完成' : '下一步'}
            </Button>
          </div>

          {/* Progress indicator */}
          <div className="flex gap-1">
            {ONBOARDING_STEPS.map((_, index) => (
              <div
                key={index}
                className={`h-2 flex-1 rounded-full transition-colors ${
                  index <= currentStep ? 'bg-blue-500' : 'bg-gray-200'
                }`}
              />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

interface TooltipProps {
  text: string;
  children: React.ReactNode;
}

export function Tooltip({ text, children }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <div className="relative inline-block">
      <div
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        className="cursor-help"
      >
        {children}
      </div>
      {isVisible && (
        <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-sm rounded-lg whitespace-nowrap z-10">
          {text}
          <div className="absolute top-full left-1/2 transform -translate-x-1/2 border-4 border-transparent border-t-gray-900"></div>
        </div>
      )}
    </div>
  );
}
