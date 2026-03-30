interface AICapabilityHeaderProps {
  capabilities: string[];
  description: string;
}

export function AICapabilityHeader({ capabilities, description }: AICapabilityHeaderProps) {
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mt-2">
        {capabilities.map(cap => (
          <span
            key={cap}
            className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700"
          >
            {cap}
          </span>
        ))}
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
