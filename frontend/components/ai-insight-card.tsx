import { Card, CardContent } from '@/components/ui/card';

interface AIInsightCardProps {
  loading?: boolean;
  insight?: string | null;
  actions?: Array<{ label: string; type: 'warning' | 'info' | 'success' }>;
  title?: string;
}

export function AIInsightCard({ loading, insight, actions = [], title = '🤖 AI 分析' }: AIInsightCardProps) {
  if (loading) {
    return (
      <Card className="mb-4 border-blue-100 bg-blue-50/50">
        <CardContent className="py-3 px-4">
          <div className="flex items-center gap-2 text-sm text-blue-600">
            <span className="animate-pulse">⚡</span>
            <span>AI 分析中...</span>
          </div>
        </CardContent>
      </Card>
    );
  }
  if (!insight) return null;
  return (
    <Card className="mb-4 border-blue-100 bg-blue-50/50">
      <CardContent className="py-3 px-4">
        <div className="text-xs font-semibold text-blue-500 mb-1">{title}</div>
        <p className="text-sm text-gray-700 leading-relaxed">{insight}</p>
        {actions.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {actions.map((a, i) => (
              <span
                key={i}
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  a.type === 'warning'
                    ? 'bg-amber-100 text-amber-700'
                    : a.type === 'success'
                      ? 'bg-green-100 text-green-700'
                      : 'bg-blue-100 text-blue-700'
                }`}
              >
                {a.label}
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
