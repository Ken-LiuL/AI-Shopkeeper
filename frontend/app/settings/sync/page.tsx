'use client';

import { useState, useEffect, useCallback } from 'react';
import { fetchAPI } from '@/lib/api';

interface SyncStatus {
  healthy: boolean;
  cookie: {
    configured: boolean;
    merchant_id?: string;
    last_verified_at?: string;
    last_sync_at?: string;
    last_sync_status?: string;
    last_sync_error?: string;
    records_synced_total?: number;
    cookie_updated_at?: string;
  };
  data_counts: Record<string, { count: number; last_sync: string | null }>;
  checked_at: string;
}

const SOURCE_LABELS: Record<string, string> = {
  products: '商品数据',
  orders: '订单数据',
  metrics: '指标数据',
  customers: '客户数据',
  traffic: '流量数据',
  channels: '渠道数据',
};

export default function SyncSettingsPage() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [cookieInput, setCookieInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState<{ ok: boolean; msg: string } | null>(null);

  const [triggering, setTriggering] = useState(false);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const json = await fetchAPI<any>('/sync/status');
      if (json?.data) {
        setStatus(json.data);
      } else if (json) {
        setStatus(json as SyncStatus);
      } else {
        setError('获取状态失败');
      }
    } catch (e: any) {
      setError(`网络错误: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const timer = setInterval(fetchStatus, 30000);
    return () => clearInterval(timer);
  }, [fetchStatus]);

  const handleCookieSubmit = async () => {
    if (!cookieInput.trim()) {
      setSubmitMsg({ ok: false, msg: 'Cookie 不能为空' });
      return;
    }
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      const json = await fetchAPI<any>('/sync/cookie', {
        method: 'POST',
        body: JSON.stringify({ cookie_string: cookieInput.trim() }),
      });
      if (json?.ok ?? true) {
        setSubmitMsg({ ok: true, msg: `✅ ${json.message}` });
        setCookieInput('');
        fetchStatus();
      } else {
        setSubmitMsg({ ok: false, msg: `❌ ${json.detail || json.message || '提交失败'}` });
      }
    } catch (e: any) {
      setSubmitMsg({ ok: false, msg: `❌ 网络错误: ${e.message}` });
    } finally {
      setSubmitting(false);
    }
  };

  const handleTriggerSync = async () => {
    setTriggering(true);
    setTriggerMsg(null);
    try {
      const json = await fetchAPI<any>('/sync/trigger', { method: 'POST' });
      setTriggerMsg(json.message || '同步已触发，请稍后刷新状态');
      setTimeout(fetchStatus, 5000);
    } catch (e: any) {
      setTriggerMsg(`错误: ${e.message}`);
    } finally {
      setTriggering(false);
    }
  };

  const formatTime = (ts?: string | null) => {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
    } catch {
      return ts;
    }
  };

  const statusBadge = (s?: string) => {
    const m: Record<string, string> = {
      success: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      running: 'bg-blue-100 text-blue-800',
      ready: 'bg-gray-100 text-gray-700',
    };
    return m[s || ''] || 'bg-gray-100 text-gray-700';
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">数据采集设置</h1>
        <p className="text-sm text-gray-500 mt-1">
          数据由后端采集服务自动执行，无需 Chrome 扩展。请提交可用 Cookie 供 nodriver 采集链路使用。
        </p>
      </div>

      {/* ── 当前状态 ── */}
      <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-800">同步状态</h2>
          <button
            onClick={fetchStatus}
            disabled={loading}
            className="text-sm text-blue-600 hover:underline disabled:opacity-40"
          >
            {loading ? '刷新中...' : '刷新'}
          </button>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">{error}</div>
        )}

        {status && (
          <>
            {/* 整体健康 */}
            <div className={`rounded-lg p-3 text-sm flex items-center gap-2 ${status.healthy ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-yellow-50 text-yellow-800 border border-yellow-200'}`}>
              <span className="text-lg">{status.healthy ? '✅' : '⚠️'}</span>
              <span>{status.healthy ? '同步正常运行' : 'Cookie 未配置或同步异常，请检查'}</span>
            </div>

            {/* Cookie 状态 */}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="bg-gray-50 rounded-lg p-3">
                <div className="text-gray-500 text-xs mb-1">Cookie 状态</div>
                <div className={`font-medium ${status.cookie.configured ? 'text-green-700' : 'text-red-600'}`}>
                  {status.cookie.configured ? '✅ 已配置' : '❌ 未配置'}
                </div>
              </div>
              <div className="bg-gray-50 rounded-lg p-3">
                <div className="text-gray-500 text-xs mb-1">最后同步</div>
                <div className="font-medium text-gray-800">{formatTime(status.cookie.last_sync_at)}</div>
              </div>
              {status.cookie.last_sync_status && (
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="text-gray-500 text-xs mb-1">同步结果</div>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusBadge(status.cookie.last_sync_status)}`}>
                    {status.cookie.last_sync_status}
                  </span>
                </div>
              )}
              {status.cookie.records_synced_total !== undefined && (
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="text-gray-500 text-xs mb-1">累计同步记录</div>
                  <div className="font-medium text-gray-800">{status.cookie.records_synced_total}</div>
                </div>
              )}
            </div>

            {status.cookie.last_sync_error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-xs font-mono whitespace-pre-wrap">
                {status.cookie.last_sync_error}
              </div>
            )}

            {/* 数据量 */}
            <div>
              <div className="text-xs text-gray-500 mb-2">各数据源同步情况</div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {Object.entries(status.data_counts).map(([src, info]) => (
                  <div key={src} className="bg-gray-50 rounded-lg p-2 text-xs">
                    <div className="text-gray-500">{SOURCE_LABELS[src] || src}</div>
                    <div className="font-semibold text-gray-800 mt-0.5">{info.count} 条</div>
                    {info.last_sync && (
                      <div className="text-gray-400 text-xs mt-0.5">
                        {formatTime(info.last_sync)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </section>

      {/* ── Cookie 配置 ── */}
      <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <h2 className="text-lg font-semibold text-gray-800">配置美团商家后台 Cookie</h2>
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-700 space-y-1">
          <p className="font-medium">如何获取 Cookie？</p>
          <ol className="list-decimal list-inside space-y-1 text-blue-600">
            <li>在 Chrome 中登录 <a href="https://yiyao.meituan.com" target="_blank" rel="noreferrer" className="underline">yiyao.meituan.com</a></li>
            <li>按 F12 打开开发者工具 → Application → Cookies</li>
            <li>复制所有 <code className="bg-blue-100 px-1 rounded">yiyao.meituan.com</code> 的 Cookie</li>
            <li>粘贴到下方输入框，点击「保存 Cookie」</li>
          </ol>
        </div>

        <div className="space-y-3">
          <label className="block">
            <span className="text-sm font-medium text-gray-700">Cookie 字符串</span>
            <textarea
              className="mt-1 w-full border border-gray-300 rounded-lg p-3 text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 h-28"
              placeholder="示例：token=xxx; session=yyy; uid=zzz; ..."
              value={cookieInput}
              onChange={(e) => setCookieInput(e.target.value)}
            />
          </label>
          <button
            onClick={handleCookieSubmit}
            disabled={submitting || !cookieInput.trim()}
            className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            {submitting ? '保存中...' : '保存 Cookie'}
          </button>
          {submitMsg && (
            <div className={`text-sm rounded-lg p-2 ${submitMsg.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
              {submitMsg.msg}
            </div>
          )}
        </div>
      </section>

      {/* ── 手动同步 ── */}
      <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
        <h2 className="text-lg font-semibold text-gray-800">手动触发同步</h2>
        <p className="text-sm text-gray-500">
          点击「立即同步」可立即触发一次后端全量采集（需要 Cookie 已配置）。任务在后台运行，约需 1-3 分钟。
        </p>
        <button
          onClick={handleTriggerSync}
          disabled={triggering}
          className="bg-gray-900 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {triggering ? '触发中...' : '⚡ 立即同步'}
        </button>
        {triggerMsg && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm text-gray-700">
            {triggerMsg}
          </div>
        )}
      </section>

      <p className="text-xs text-gray-400 text-center">
        调度由后端服务托管：商品每日 02:00，订单每小时，评价每 6 小时，统计每日 06:00。
      </p>
    </div>
  );
}
