function getBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem('app-settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        if (settings.apiUrl) return settings.apiUrl;
      } catch {}
    }
  }
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
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

// Customer Service
export const createChatSession = (customerId?: string) =>
  request<any>('/api/customer-service/sessions', {
    method: 'POST',
    body: JSON.stringify({ customer_id: customerId }),
  });
export const sendChatMessage = (message: string, sessionId: string) =>
  request<any>('/api/customer-service/chat', {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId }),
  });
export const getChatSessions = (customerId?: string) => {
  const sp = new URLSearchParams();
  if (customerId) sp.set('customer_id', customerId);
  return request<any>(`/api/customer-service/sessions?${sp.toString()}`);
};
export const getChatHistory = (sessionId: string) =>
  request<any>(`/api/customer-service/sessions/${sessionId}/messages`);
export const deleteChatSession = (sessionId: string) =>
  request<any>(`/api/customer-service/sessions/${sessionId}`, { method: 'DELETE' });

// Replenishment
export const getReplenishmentSuggestions = () => request<any>('/api/replenishment/suggestions');
export const getReplenishmentSafetyStock = () => request<any>('/api/replenishment/safety-stock');
export const createPurchaseOrder = (items: any[]) =>
  request<any>('/api/replenishment/purchase-order', { method: 'POST', body: JSON.stringify(items) });

// Pricing
export const getPricingSuggestions = () => request<any>('/api/pricing/suggestions');
export const getPricingAnalysis = (id: string) => request<any>(`/api/pricing/analysis/${id}`);
export const applyPriceChanges = (changes: any[]) =>
  request<any>('/api/pricing/apply', { method: 'POST', body: JSON.stringify({ changes }) });

// Reports
export const getDailyReport = (date?: string) => {
  const sp = new URLSearchParams();
  if (date) sp.set('date', date);
  return request<any>(`/api/reports/daily?${sp.toString()}`);
};
export const getWeeklyReport = () => request<any>('/api/reports/weekly');
export const getMonthlyReport = () => request<any>('/api/reports/monthly');

// Analytics
export const getCSAnalytics = (params?: { start_date?: string; end_date?: string }) => {
  const sp = new URLSearchParams();
  if (params?.start_date) sp.set('start_date', params.start_date);
  if (params?.end_date) sp.set('end_date', params.end_date);
  return request<any>(`/api/analytics/customer-service?${sp.toString()}`);
};
export const getConversionTracking = (days?: number) =>
  request<any>(`/api/analytics/conversion?days=${days || 7}`);

// Listing
export const getListings = (params?: { status?: string; page?: number; page_size?: number }) => {
  const sp = new URLSearchParams();
  if (params?.status) sp.set('status', params.status);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  return request<any>(`/api/listing?${sp.toString()}`);
};
export const getListing = (id: string) => request<any>(`/api/listing/${id}`);
export const generateListing = (sourceUrl: string) =>
  request<any>('/api/listing/generate', {
    method: 'POST',
    body: JSON.stringify({ source_url: sourceUrl }),
  });
export const updateListing = (id: string, data: any) =>
  request<any>(`/api/listing/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
export const publishListing = (id: string) =>
  request<any>(`/api/listing/${id}/publish`, { method: 'POST' });
