'use client';
import { ResponsiveContainer, LineChart as RLineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';

export function LineChart({ data, xKey, yKey, label }: { data: any[]; xKey: string; yKey: string; label?: string }) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <RLineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
        <XAxis dataKey={xKey} tick={{ fill: '#666', fontSize: 12 }} tickLine={false} axisLine={{ stroke: 'rgba(255,255,255,0.08)' }} />
        <YAxis tick={{ fill: '#666', fontSize: 12 }} tickLine={false} axisLine={{ stroke: 'rgba(255,255,255,0.08)' }} />
        <Tooltip
          contentStyle={{ background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff' }}
          labelStyle={{ color: '#999' }}
        />
        <Line type="monotone" dataKey={yKey} stroke="#FFB300" strokeWidth={2} dot={false} name={label || yKey} />
      </RLineChart>
    </ResponsiveContainer>
  );
}
