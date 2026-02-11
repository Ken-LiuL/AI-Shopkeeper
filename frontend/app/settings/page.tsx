'use client';
import { Header } from '@/components/layout/header';
import { Card } from '@/components/ui/card';

const configs = [
  { section: '选品参数', items: [
    { label: '最低评分阈值', value: '60', desc: '推荐商品的最低综合评分' },
    { label: '评估维度', value: '6 维度', desc: '销量趋势/利润率/库存周转/品类适配/季节性/竞争力' },
    { label: '推荐数量上限', value: '50', desc: '单次选品最大推荐数' },
  ]},
  { section: '预警规则', items: [
    { label: '库存预警阈值', value: '10', desc: '库存低于此值触发预警' },
    { label: '销量下降预警', value: '-30%', desc: '周销量下降超过此比例' },
    { label: '扫描频率', value: '每日', desc: '自动扫描频率' },
  ]},
  { section: '套餐生成', items: [
    { label: '最小支持度', value: '0.01', desc: '关联规则最小支持度' },
    { label: '最小置信度', value: '0.3', desc: '关联规则最小置信度' },
    { label: '最大套餐数', value: '20', desc: '单次生成最大套餐数' },
  ]},
  { section: '系统配置', items: [
    { label: 'API 地址', value: 'http://localhost:8000', desc: '后端 API 服务地址' },
    { label: 'LLM 模型', value: 'GPT-4', desc: 'AI 代理使用的语言模型' },
    { label: '数据库', value: 'PostgreSQL', desc: '主数据存储' },
  ]},
];

export default function SettingsPage() {
  return (
    <div>
      <Header title="系统设置" />
      <div className="p-6 space-y-6">
        {configs.map((group) => (
          <Card key={group.section}>
            <h3 className="text-white font-semibold mb-4">{group.section}</h3>
            <div className="space-y-4">
              {group.items.map((item) => (
                <div key={item.label} className="flex items-center justify-between py-2 border-b border-white/[0.04] last:border-0">
                  <div>
                    <div className="text-sm text-gray-200">{item.label}</div>
                    <div className="text-xs text-gray-500">{item.desc}</div>
                  </div>
                  <span className="text-sm text-amber-400 font-mono">{item.value}</span>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
