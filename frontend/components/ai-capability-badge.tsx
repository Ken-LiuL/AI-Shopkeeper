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
            className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gradient-to-r from-blue-50 to-purple-50 text-blue-700 border border-blue-200"
          >
            ✨ {cap}
          </span>
        ))}
      </div>
      <p className="text-sm text-muted-foreground mt-1">{description}</p>
    </div>
  );
}
