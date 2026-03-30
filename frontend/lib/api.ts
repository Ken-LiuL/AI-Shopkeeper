// API client for AI店长 backend
// When NEXT_PUBLIC_API_URL is set, Next.js rewrites proxy /api/* → backend server-side.
// Client always uses relative /api/... paths to avoid mixed-content (HTTPS→HTTP) blocks.
// When NEXT_PUBLIC_API_URL is set, Next.js rewrites proxy /api/* → backend.
// Client always uses relative /api/... paths.
const BASE_URL = '';

// Error mapping for user-friendly messages
const getErrorMessage = (error: unknown, endpoint: string): string => {
  if (!error) return '未知错误';
  const err = error as Error;

  // Network errors
  if (err.name === 'AbortError' || err.message?.includes('aborted')) {
    return '请求超时，请检查网络或稍后重试';
  }
  if (err.message?.includes('Failed to fetch')) {
    return '网络连接失败，请检查网络连接后重试';
  }

  // API-specific error mappings
  const endpointErrors: Record<string, Record<number, string>> = {
    '/dashboard/overview': {
      500: '数据服务暂时不可用，请稍后重试',
      404: '数据不存在，请联系技术支持',
    },
    '/products/inventory': {
      500: '商品数据加载失败，请稍后重试',
      403: '没有访问商品数据的权限',
    },
    '/pricing/suggestions': {
      500: '定价分析服务暂时不可用，请稍后重试',
      429: '请求过于频繁，请稍后重试',
    },
    '/customer-service/chat': {
      500: 'AI 客服暂时不可用，请稍后重试或联系人工客服',
      429: '请求过于频繁，请稍等片刻后再发送消息',
    }
  };

  // Extract status code from error
  const statusMatch = err.message?.match(/API Error: (\d+)/);
  const status = statusMatch ? parseInt(statusMatch[1]) : 0;

  // Look for specific endpoint error mapping
  const specificError = endpointErrors[endpoint]?.[status];
  if (specificError) {
    return specificError;
  }

  // General status code mapping
  switch (status) {
    case 400:
      return '请求参数错误，请检查输入信息';
    case 401:
      return '登录已过期，请重新登录';
    case 403:
      return '没有访问权限，请联系管理员';
    case 404:
      return '请求的数据不存在';
    case 429:
      return '请求过于频繁，请稍后重试';
    case 500:
      return '服务器内部错误，请稍后重试';
    case 502:
    case 503:
    case 504:
      return '服务暂时不可用，请稍后重试';
    default:
      // For other cases, return a generic but helpful message
      if (err.message?.includes('API Error')) {
        return '服务暂时不可用，请稍后重试';
      }
      return err.message || '操作失败，请稍后重试';
  }
};

const DEFAULT_API_TIMEOUT_MS = 15000;

export async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_API_TIMEOUT_MS);

  try {
    const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
    const authHeaders: Record<string, string> = token ? { 'Authorization': `Bearer ${token}` } : {};

    const response = await fetch(`${BASE_URL}/api${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
        ...options?.headers,
      },
      ...options,
      signal: options?.signal ?? controller.signal,
    });

    if (response.status === 401) {
      if (typeof window !== 'undefined') {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_username');
        window.location.href = '/login';
      }
      throw new Error('登录已过期，请重新登录');
    }

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }

    const json = await response.json();
    // Unwrap APIResponse wrapper if present
    if (json && typeof json === 'object' && 'success' in json && 'data' in json) {
      if (!json.success) {
        throw new Error(json.message || 'API returned error');
      }
      return json.data as T;
    }
    return json as T;
  } catch (error) {
    console.error(`Error fetching ${endpoint}:`, error);
    // Transform error to user-friendly message
    const userMessage = getErrorMessage(error, endpoint);
    throw new Error(userMessage);
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetchAPIFormData<T>(
  endpoint: string,
  formData: FormData,
  options?: Omit<RequestInit, 'body'>
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_API_TIMEOUT_MS);

  try {
    const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
    const authHeaders: Record<string, string> = token ? { 'Authorization': `Bearer ${token}` } : {};

    const response = await fetch(`${BASE_URL}/api${endpoint}`, {
      ...options,
      headers: {
        ...authHeaders,
        ...options?.headers,
      },
      body: formData,
      signal: options?.signal ?? controller.signal,
    });

    if (response.status === 401) {
      if (typeof window !== 'undefined') {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_username');
        window.location.href = '/login';
      }
      throw new Error('登录已过期，请重新登录');
    }

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }

    const json = await response.json();
    if (json && typeof json === 'object' && 'success' in json && 'data' in json) {
      if (!json.success) {
        throw new Error(json.message || 'API returned error');
      }
      return json.data as T;
    }
    return json as T;
  } catch (error) {
    console.error(`Error fetching ${endpoint}:`, error);
    const userMessage = getErrorMessage(error, endpoint);
    throw new Error(userMessage);
  } finally {
    clearTimeout(timeout);
  }
}

// Dashboard API
export interface DashboardOverview {
  total_products: number;
  today_orders: number;
  today_gmv: string;
  yesterday_orders: number;
  yesterday_gmv: string;
  avg_rating: number;
  avg_order_value: string;
  total_customers: number;
  conversion_rate: number;
  pending_alerts: number;
  pending_tasks: number;
  low_stock_count: number;
  recent_sync_state?: SyncerStatus[];
  action_items?: Array<{
    priority: 'high' | 'medium' | 'low';
    action: string;
    detail: string;
    link: string;
  }>;
  recent_outcomes?: Array<{
    title: string;
    detail: string;
    category: string;
    link: string;
    happened_at: string;
    next_check: string;
  }>;
}

export async function getDashboardOverview(): Promise<DashboardOverview> {
  return fetchAPI<DashboardOverview>('/dashboard/overview');
}

// Competitors API
export interface CompetitorOverview {
  summary: {
    total_stores: number;
    active_stores: number;
    total_products: number;
    active_products: number;
    total_keywords: number;
    avg_product_price: number;
  };
  top_categories: Array<{
    category: string;
    product_count: number;
    avg_price: number;
  }>;
  last_updated: string;
}

export interface PriceComparison {
  product_id: string;
  name: string;
  our_price: number | string;
  competitor_name: string;
  competitor_price: number;
  competitor_store: string;
  price_diff_pct: number | string;
}

export interface CompetitorPriceChange {
  product_id: string;
  product_name: string;
  competitor_name: string;
  old_price: number;
  new_price: number;
  change_pct: number;
  changed_at: string | null;
}

export async function getCompetitorOverview(): Promise<CompetitorOverview> {
  return fetchAPI<CompetitorOverview>('/competitors/overview');
}

export async function getPriceComparison(limit: number = 20): Promise<PriceComparison[]> {
  return fetchAPI<PriceComparison[]>(`/competitors/price-comparison?limit=${limit}`);
}

export async function getCompetitorPriceChanges(limit: number = 50): Promise<CompetitorPriceChange[]> {
  return fetchAPI<CompetitorPriceChange[]>(`/competitors/price-changes?limit=${limit}`);
}

export interface InventoryListItem {
  product_id: string;
  name: string;
  stock: number;
  available_stock?: number | null;
  locked_stock?: number | null;
  category?: string | null;
  monthly_sales?: number;
  retail_price?: number | null;
  stock_value?: number | null;
  coverage_days?: number | null;
  risk_level?: 'normal' | 'medium' | 'high' | 'stockout' | 'stockout_but_selling';
  status: 'normal' | 'low_stock' | 'out_of_stock';
  source: string;
}

export async function getInventoryList(limit: number = 200): Promise<InventoryListItem[]> {
  return fetchAPI<InventoryListItem[]>(`/inventory/list?limit=${limit}&low_stock_first=true`);
}

export interface SyncerStatus {
  syncer_name: string;
  last_sync_status: string;
  last_sync_time: string | null;
  records_synced: number;
  duration_ms: number;
}

export interface SyncStatusResponse {
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
  syncers: SyncerStatus[];
  checked_at: string;
}

export async function getSyncStatus(): Promise<SyncStatusResponse> {
  return fetchAPI<SyncStatusResponse>('/sync/status');
}

export type ManualImportType = 'products' | 'orders' | 'inventory';

export interface ManualImportQualityIssue {
  severity: 'critical' | 'warning' | 'info';
  code: string;
  message: string;
  count: number;
  samples: string[];
}

export interface ManualImportQualityReport {
  score: number;
  stats: Record<string, number | string>;
  issues: ManualImportQualityIssue[];
  suggestions: string[];
}

export interface ManualImportPreview {
  import_type: ManualImportType;
  filename: string;
  detected_sheets: string[];
  total_rows: number;
  normalized_preview: Record<string, Array<Record<string, unknown>>>;
  quality_report: ManualImportQualityReport;
}

export interface ManualImportResult extends ManualImportPreview {
  run_id: string;
  imported_rows: number;
  skipped_rows: number;
  import_summary: Record<string, number | string>;
}

export interface ManualImportRun {
  run_id: string;
  import_type: ManualImportType;
  filename: string;
  status: string;
  total_rows: number;
  imported_rows: number;
  skipped_rows: number;
  quality_score: number;
  quality_report: ManualImportQualityReport;
  import_summary: Record<string, number | string>;
  created_at: string;
  updated_at: string;
}

export interface ManualImportOverview {
  latest_run: {
    import_type: ManualImportType;
    filename: string;
    quality_score: number;
    created_at: string;
  } | null;
  by_type: Array<{
    import_type: ManualImportType;
    run_count: number;
    imported_rows: number;
  }>;
}

export interface ManualImportReviewIssue {
  key: string;
  title: string;
  severity: 'critical' | 'warning' | 'info';
  count: number;
  description: string;
  recommended_action: string;
}

export interface ManualImportReview {
  summary: Record<string, number>;
  open_summary?: Record<string, number>;
  issues: ManualImportReviewIssue[];
  tables: Record<string, Array<Record<string, unknown>>>;
}

export interface ManualImportComparisonIssue {
  key: string;
  title: string;
  current: number;
  previous: number;
  delta: number;
}

export interface ManualImportComparison {
  import_type?: ManualImportType;
  latest_run: ManualImportRun | null;
  previous_run: ManualImportRun | null;
  delta: {
    imported_rows?: number;
    total_rows?: number;
    quality_score?: number;
    open_issues?: number;
  };
  review_delta: {
    available: boolean;
    new_issues: ManualImportComparisonIssue[];
    resolved_issues: ManualImportComparisonIssue[];
    worsened_issues: ManualImportComparisonIssue[];
    improved_issues: ManualImportComparisonIssue[];
  };
}

export interface IssueActionRecord {
  issue_type: string;
  issue_key: string;
  title?: string;
  status: 'acknowledged' | 'resolved' | 'ignored';
  notes?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export async function previewManualImport(
  file: File,
  importType?: ManualImportType
): Promise<ManualImportPreview> {
  const formData = new FormData();
  formData.append('file', file);
  if (importType) {
    formData.append('import_type', importType);
  }
  return fetchAPIFormData<ManualImportPreview>('/manual-import/preview', formData, {
    method: 'POST',
  });
}

export async function commitManualImport(
  file: File,
  importType?: ManualImportType
): Promise<ManualImportResult> {
  const formData = new FormData();
  formData.append('file', file);
  if (importType) {
    formData.append('import_type', importType);
  }
  return fetchAPIFormData<ManualImportResult>('/manual-import/commit', formData, {
    method: 'POST',
  });
}

export async function getManualImportRuns(limit: number = 20): Promise<ManualImportRun[]> {
  return fetchAPI<ManualImportRun[]>(`/manual-import/runs?limit=${limit}`);
}

export async function getManualImportOverview(): Promise<ManualImportOverview> {
  return fetchAPI<ManualImportOverview>('/manual-import/overview');
}

export async function getManualImportReview(limit: number = 20): Promise<ManualImportReview> {
  return fetchAPI<ManualImportReview>(`/manual-import/review?limit=${limit}`);
}

export async function getManualImportComparison(importType?: ManualImportType): Promise<ManualImportComparison> {
  const params = new URLSearchParams();
  if (importType) {
    params.set('import_type', importType);
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return fetchAPI<ManualImportComparison>(`/manual-import/comparison${suffix}`);
}

export async function lookupIssueActions(
  issues: Array<{ issue_type: string; issue_key: string }>
): Promise<IssueActionRecord[]> {
  return fetchAPI<IssueActionRecord[]>('/issue-actions/lookup', {
    method: 'POST',
    body: JSON.stringify({ issues }),
  });
}

export async function updateIssueAction(body: {
  issue_type: string;
  issue_key: string;
  title?: string;
  status: 'acknowledged' | 'resolved' | 'ignored';
  notes?: string;
  metadata?: Record<string, unknown>;
}): Promise<IssueActionRecord> {
  return fetchAPI<IssueActionRecord>('/issue-actions', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// Reports API
// Alerts API
export interface Alert {
  alert_id: string;
  type: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'warning' | 'info';
  title: string;
  description: string;
  product_id?: string;
  status: string;
  created_at: string;
  resolved_at?: string;
  // Backward compatibility
  message?: string;
  action_suggestions?: string[];
  recommended_action?: string;
}

export async function getAlerts(): Promise<Alert[]> {
  return fetchAPI<Alert[]>('/dashboard/alerts');
}

// Customer Service API
export interface ChatMessage {
  message: string;
  session_id: string;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  intent: string;
  sources: Array<{
    id: string;
    name: string;
    category: string;
    brand: string;
    price: number;
    score: number;
    description: string;
  }>;
  needs_human: boolean;
}

export async function sendChatMessage(data: ChatMessage): Promise<ChatResponse> {
  return fetchAPI<ChatResponse>('/customer-service/chat', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

// Products API
export interface Product {
  product_id: string;
  name: string;
  retail_price: number;
  estimated_stock?: number;
  stock?: number;
  monthly_sales?: number;
  threshold?: number;
  cost_price?: number;
  brand?: string | null;
  category: string;
  status?: 'active' | 'inactive' | 'out_of_stock' | 'low_stock';
  // Backward compatibility
  id?: string;
  price?: number;
  inventory?: number;
}

export interface ProductDetail extends Product {
  barcode?: string | null;
  description?: string | null;
  stock?: number;
}

export interface ProductUpdatePayload {
  name?: string;
  barcode?: string | null;
  category?: string | null;
  brand?: string | null;
  description?: string | null;
  cost_price?: number | null;
  retail_price?: number | null;
  stock?: number | null;
  status?: string | null;
}

export interface ProductsResponse {
  summary: {
    total_products: number;
    active_products: number;
    inactive_products: number;
    low_stock_count: number;
  };
  category_breakdown: Array<{
    category: string;
    total_count: number;
    active_count: number;
    inactive_count: number;
  }>;
  low_stock_items: Product[];
  // For backward compatibility
  products?: Product[];
  total?: number;
  page?: number;
  limit?: number;
}

export async function getProducts(
  page: number = 1,
  limit: number = 20,
  search: string = '',
  status: string = '',
): Promise<ProductsResponse> {
  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  });
  if (search.trim()) params.set('search', search.trim());
  if (status.trim()) params.set('status', status.trim());
  const response = await fetchAPI<ProductsResponse>(`/products/inventory?${params.toString()}`);
  if (response.products) {
    response.products = response.products.map(item => ({
      ...item,
      id: item.product_id,
      price: item.retail_price,
      inventory: item.estimated_stock || 0,
    }));
  }
  return response;
}

export async function getProduct(productId: string): Promise<ProductDetail> {
  return fetchAPI<Record<string, unknown>>(`/products/${productId}`).then((item) => ({
    product_id: String(item.product_id || productId),
    name: String(item.name || '未命名商品'),
    retail_price: Number(item.retail_price || 0),
    estimated_stock: Number(item.stock || 0),
    stock: Number(item.stock || 0),
    monthly_sales: Number(item.monthly_sales || 0),
    threshold: Number(item.threshold || 0),
    cost_price: Number(item.cost_price || 0),
    brand: item.brand ? String(item.brand) : null,
    category: String(item.category || '未分类'),
    status: String(item.status || 'active') as Product['status'],
    barcode: item.barcode ? String(item.barcode) : null,
    description: item.description ? String(item.description) : null,
    id: String(item.product_id || productId),
    price: Number(item.retail_price || 0),
    inventory: Number(item.stock || 0),
  }));
}

export async function updateProduct(
  productId: string,
  payload: ProductUpdatePayload,
): Promise<ProductDetail> {
  return fetchAPI<Record<string, unknown>>(`/products/${productId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }).then((item) => ({
    product_id: String(item.product_id || productId),
    name: String(item.name || '未命名商品'),
    retail_price: Number(item.retail_price || 0),
    estimated_stock: Number(item.stock || 0),
    stock: Number(item.stock || 0),
    monthly_sales: Number(item.monthly_sales || 0),
    threshold: Number(item.threshold || 0),
    cost_price: Number(item.cost_price || 0),
    brand: item.brand ? String(item.brand) : null,
    category: String(item.category || '未分类'),
    status: String(item.status || 'active') as Product['status'],
    barcode: item.barcode ? String(item.barcode) : null,
    description: item.description ? String(item.description) : null,
    id: String(item.product_id || productId),
    price: Number(item.retail_price || 0),
    inventory: Number(item.stock || 0),
  }));
}

// Store KPIs API
export interface StoreKPIs {
  orders: number;
  gmv: number;
  actual_revenue: number;
  product_sales: number;
  avg_order_value: number;
  actual_avg_order_value: number;
  net_profit: number;
  customers: number;
  delivery_fee: number;
  package_fee: number;
  stockout_loss: number;
}

export async function getStoreKPIs(): Promise<StoreKPIs> {
  return fetchAPI<StoreKPIs>('/dashboard/store-kpis');
}

// Orders API
export interface Order {
  order_id: string;
  product_name: string;
  amount: number;
  status: 'pending' | 'processing' | 'completed' | 'refunded' | 'cancelled';
  created_at: string;
}

export interface OrderStats {
  today_orders: number;
  completion_rate: number;
  refund_rate: number;
  avg_delivery_time: number;
}

export async function getOrders(
  page: number = 1,
  limit: number = 20,
  status: string = 'all',
  date?: string,
): Promise<{
  orders: Order[];
  total: number;
  page: number;
  limit: number;
}> {
  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
    status,
  });
  if (date) params.set('date', date);
  return fetchAPI<{
    data: Array<Record<string, unknown>>;
    total: number;
    page: number;
    page_size: number;
  }>(`/orders/list?${params.toString()}`).then((response) => ({
    orders: (response.data || []).map((item) => ({
      order_id: String(item.order_id || ''),
      product_name: String(item.product_name || '—'),
      amount: Number(item.amount || item.customer_paid || item.total_amount || 0),
      status: String(item.status || 'pending') as Order['status'],
      created_at: String(item.created_at || item.order_time || ''),
    })),
    total: Number(response.total || 0),
    page: Number(response.page || page),
    limit: Number(response.page_size || limit),
  }));
}

export async function getOrderStats(): Promise<OrderStats> {
  return fetchAPI<Record<string, unknown>>('/orders/stats').then((response) => ({
    today_orders: Number(response.today_orders || 0),
    completion_rate: Number(response.completion_rate || 0),
    refund_rate: Number(response.refund_rate || 0),
    avg_delivery_time: Number(response.avg_delivery_time || 0),
  }));
}

// Pricing API
export interface PricingSuggestion {
  product_id: string;
  product_name: string;
  current_price: number;
  suggested_price: number;
  reason: string;
  confidence: number;
  expected_impact: string;
  status?: 'pending' | 'adopted';
}

export interface PricingRule {
  rule_id: string;
  name: string;
  description: string;
  enabled: boolean;
  priority: number;
}

export async function getPricingSuggestions(): Promise<PricingSuggestion[]> {
  return fetchAPI<Array<Record<string, unknown>>>('/pricing/suggestions', {
    method: 'POST',
  }).then((rows) =>
    rows.map((item) => ({
      product_id: String(item.product_id || ''),
      product_name: String(item.product_name || item.name || '未命名商品'),
      current_price: Number(item.current_price || 0),
      suggested_price: Number(item.suggested_price || 0),
      reason: String(item.reason || ''),
      confidence: Number(item.confidence || 0),
      expected_impact: String(item.expected_impact || item.potential_impact || ''),
      status: item.status === 'adopted' ? 'adopted' : 'pending',
    })),
  );
}

export async function getPricingRules(): Promise<PricingRule[]> {
  return fetchAPI<Array<Record<string, unknown>>>('/pricing/rules').then((rows) =>
    rows.map((item, index) => ({
      rule_id: String(item.rule_id || `rule_${index}`),
      name: String(item.name || '未命名规则'),
      description: String(item.description || ''),
      enabled: Boolean(item.enabled ?? item.is_active ?? false),
      priority: Number(item.priority || index + 1),
    })),
  );
}

export async function adoptPricingSuggestion(suggestionId: string): Promise<void> {
  return fetchAPI(`/pricing/suggestions/${suggestionId}/adopt`, {
    method: 'POST',
  });
}

// Batch pricing operations
export interface BatchPriceUpdateRequest {
  product_ids: string[];
  operation: 'multiply' | 'add' | 'set';
  value: number;
  reason?: string;
}

export interface BatchPriceUpdateResult {
  success: boolean;
  updated_count: number;
  failed_count: number;
  results: Array<{
    product_id: string;
    product_name?: string;
    success: boolean;
    old_price?: number;
    new_price?: number;
    change_percent?: number;
    error?: string;
  }>;
}

export async function batchUpdatePrices(request: BatchPriceUpdateRequest): Promise<BatchPriceUpdateResult> {
  return fetchAPI<BatchPriceUpdateResult>('/pricing/batch-update', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

// Apply AI pricing suggestions directly to products
export interface ApplySuggestionItem {
  product_id: string;
  new_price: number;
}

export interface ApplySuggestionsResult {
  updated_count: number;
  failed_count: number;
}

export async function applyPricingSuggestions(
  suggestions: ApplySuggestionItem[],
): Promise<ApplySuggestionsResult> {
  return fetchAPI<ApplySuggestionsResult>('/pricing/apply', {
    method: 'POST',
    body: JSON.stringify({ suggestions }),
  });
}

// Inventory Restock API
export interface RestockSuggestion {
  product_id: string;
  product_name: string;
  current_stock: number;
  daily_avg_sales: number;
  remaining_days: number;
  suggested_restock: number;
  urgency: 'normal' | 'warning' | 'urgent';
}

export async function getRestockSuggestions(): Promise<RestockSuggestion[]> {
  return fetchAPI<Array<Record<string, unknown>>>('/inventory/restock-suggestions').then((rows) =>
    rows.map((item) => ({
      product_id: String(item.product_id || ''),
      product_name: String(item.name || item.product_name || '未命名商品'),
      current_stock: Number(item.current_stock || 0),
      daily_avg_sales: Number(item.avg_daily_sales || item.daily_avg_sales || 0),
      remaining_days: Number(item.days_remaining || item.remaining_days || 0),
      suggested_restock: Number(item.suggested_restock_qty || item.suggested_restock || 0),
      urgency: String(item.urgency || 'low') === 'high'
        ? 'urgent'
        : String(item.urgency || 'low') === 'medium'
          ? 'warning'
          : 'normal',
    })),
  );
}

// AI Insights API
export interface DailyInsight {
  date: string;
  sales_anomalies: string;
  hot_products_changes: string;
  competitor_dynamics: string;
  actionable_suggestions: string;
}

export async function getDailyInsights(): Promise<DailyInsight> {
  return fetchAPI<DailyInsight>('/insights/daily');
}

// AI Work Stats API
export interface AIWorkStats {
  totalActions: number;
  alertsHandled: number;
  csReplies: number;
  pricingAdj: number;
  selectionRuns: number;
  bundlesCreated: number;
  dataImports: number;
  estimatedSaved: string;  // 预估增收金额
  reflectionRounds: number;  // AI自检次数
  factChecks: number;  // 事实核查次数
}

export async function getAIWorkStats(): Promise<AIWorkStats> {
  return fetchAPI<AIWorkStats>('/dashboard/ai-stats');
}

// Listing API
export interface ListingHistoryItem {
  listing_id?: string;
  source_url?: string;
  platform?: string;
  status?: string;
  created_at?: string;
  product_data?: Record<string, unknown>;
}

export interface ListingCreateTaskResponse {
  task_id?: string;
}

export async function getListingHistory(): Promise<ListingHistoryItem[]> {
  return fetchAPI<ListingHistoryItem[]>('/listing');
}

export async function parseListingProduct(
  url: string,
  platform: 'alibaba' | 'pdd',
): Promise<Record<string, unknown>> {
  return fetchAPI<Record<string, unknown>>('/listing/parse', {
    method: 'POST',
    body: JSON.stringify({ url, platform }),
  });
}

export async function createListingTask(
  source_url: string,
  platform: 'alibaba' | 'pdd',
  raw_product_data: string,
): Promise<ListingCreateTaskResponse> {
  return fetchAPI<ListingCreateTaskResponse>('/listing/create', {
    method: 'POST',
    body: JSON.stringify({ source_url, platform, raw_product_data }),
  });
}

// Stores API
export interface StoreOverview {
  store_id: string;
  name: string;
  status: 'active' | 'inactive';
  today_orders: number;
  today_gmv: number;
}

export async function getStoresOverview(): Promise<StoreOverview[]> {
  return fetchAPI<StoreOverview[]>('/stores/overview');
}
