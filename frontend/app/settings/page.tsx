'use client';
import { useEffect, useState } from 'react';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { AppSettings } from '@/lib/types';

const defaults: AppSettings = {
  apiUrl: 'http://localhost:8000',
  refreshInterval: 30,
  selectionMinScore: 60,
  selectionMaxResults: 50,
  alertStockThreshold: 10,
  alertSalesDropThreshold: 30,
  bundleMinSupport: 0.01,
  bundleMinConfidence: 0.3,
  bundleMaxCount: 20,
  llmModel: 'GPT-4',
};

interface ConfigField {
  key: keyof AppSettings;
  label: string;
  desc: string;
  type: 'text' | 'number';
  suffix?: string;
}

const sections: { title: string; fields: ConfigField[] }[] = [
  {
    title: '系统配置',
    fields: [
      { key: 'apiUrl', label: 'API 地址', desc: '后端 API 服务地址', type: 'text' },
      { key: 'refreshInterval', label: '刷新频率', desc: '自动刷新间隔（秒）', type: 'number', suffix: '秒' },
      { key: 'llmModel', label: 'LLM 模型', desc: 'AI 代理使用的语言模型', type: 'text' },
    ],
  },
  {
    title: '选品参数',
    fields: [
      { key: 'selectionMinScore', label: '最低评分阈值', desc: '推荐商品的最低综合评分', type: 'number' },
      { key: 'selectionMaxResults', label: '推荐数量上限', desc: '单次选品最大推荐数', type: 'number' },
    ],
  },
  {
    title: '预警规则',
    fields: [
      { key: 'alertStockThreshold', label: '库存预警阈值', desc: '库存低于此值触发预警', type: 'number' },
      { key: 'alertSalesDropThreshold', label: '销量下降预警', desc: '周销量下降超过此比例(%)', type: 'number', suffix: '%' },
    ],
  },
  {
    title: '套餐生成',
    fields: [
      { key: 'bundleMinSupport', label: '最小支持度', desc: '关联规则最小支持度', type: 'number' },
      { key: 'bundleMinConfidence', label: '最小置信度', desc: '关联规则最小置信度', type: 'number' },
      { key: 'bundleMaxCount', label: '最大套餐数', desc: '单次生成最大套餐数', type: 'number' },
    ],
  },
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>(defaults);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem('app-settings');
    if (stored) {
      try {
        setSettings({ ...defaults, ...JSON.parse(stored) });
      } catch {}
    }
  }, []);

  const handleChange = (key: keyof AppSettings, value: string) => {
    setSettings((prev) => ({
      ...prev,
      [key]: typeof defaults[key] === 'number' ? Number(value) || 0 : value,
    }));
    setSaved(false);
  };

  const handleSave = () => {
    localStorage.setItem('app-settings', JSON.stringify(settings));
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleReset = () => {
    setSettings(defaults);
    localStorage.removeItem('app-settings');
    setSaved(false);
  };

  return (
    <div>
      <Header title="系统设置" />
      <div className="p-6 space-y-6">
        {sections.map((section) => (
          <Card key={section.title}>
            <h3 className="text-white font-semibold mb-4">{section.title}</h3>
            <div className="space-y-4">
              {section.fields.map((field) => (
                <div key={field.key} className="flex items-center justify-between py-2 border-b border-white/[0.04] last:border-0 gap-4">
                  <div className="shrink-0">
                    <div className="text-sm text-gray-200">{field.label}</div>
                    <div className="text-xs text-gray-500">{field.desc}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type={field.type}
                      value={String(settings[field.key])}
                      onChange={(e) => handleChange(field.key, e.target.value)}
                      className="bg-white/5 border border-white/[0.08] rounded-lg px-3 py-1.5 text-sm text-amber-400 font-mono outline-none focus:border-amber-500/50 w-48 text-right"
                      step={field.type === 'number' ? (field.key.includes('Min') ? '0.01' : '1') : undefined}
                    />
                    {field.suffix && <span className="text-xs text-gray-500">{field.suffix}</span>}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))}

        <div className="flex gap-3 justify-end">
          <Button variant="secondary" onClick={handleReset}>恢复默认</Button>
          <Button onClick={handleSave}>
            {saved ? '✓ 已保存' : '💾 保存设置'}
          </Button>
        </div>
      </div>
    </div>
  );
}
