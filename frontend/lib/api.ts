const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// Dashboard
export const getDashboardOverview = () => request<any>('/api/dashboard/overview');
export const getSalesTrend = () => request<any>('/api/dashboard/sales-trend');
export const getTopProducts = () => request<any>('/api/dashboard/top-products');

// Products
export const getProducts = (params?: { page?: number; page_size?: number; search?: string; status?: string }) => {
  const sp = new URLSearchParams();
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  if (params?.search) sp.set('search', params.search);
  if (params?.status) sp.set('status', params.status);
  return request<any>(`/api/products?${sp.toString()}`);
};
export const getProduct = (id: string) => request<any>(`/api/products/${id}`);
export const createProduct = (data: any) => request<any>('/api/products', { method: 'POST', body: JSON.stringify(data) });
export const updateProduct = (id: string, data: any) => request<any>(`/api/products/${id}`, { method: 'PUT', body: JSON.stringify(data) });

// Selection
export const triggerSelection = (data?: { keywords?: string[]; categories?: string[] }) =>
  request<any>('/api/selection/run', { method: 'POST', body: JSON.stringify(data || {}) });
export const getSelectionRuns = () => request<any>('/api/selection/runs');
export const getSelectionRun = (id: string) => request<any>(`/api/selection/runs/${id}`);
export const getRecommendations = () => request<any>('/api/selection/recommendations');

// Alerts
export const getAlerts = (params?: { severity?: string; status?: string }) => {
  const sp = new URLSearchParams();
  if (params?.severity) sp.set('severity', params.severity);
  if (params?.status) sp.set('status', params.status);
  return request<any>(`/api/alerts?${sp.toString()}`);
};
export const updateAlertStatus = (id: string, status: string) =>
  request<any>(`/api/alerts/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) });

// Bundles
export const getBundles = () => request<any>('/api/bundles');
export const generateBundles = (data?: any) =>
  request<any>('/api/bundles/generate', { method: 'POST', body: JSON.stringify(data || {}) });
export const updateBundle = (id: string, data: any) =>
  request<any>(`/api/bundles/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
export const deleteBundle = (id: string) =>
  request<any>(`/api/bundles/${id}`, { method: 'DELETE' });
