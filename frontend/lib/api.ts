// API client for AI店长 backend
const BASE_URL = process.env.NODE_ENV === 'development'
  ? 'https://ai-shopkeeper-kk.fly.dev'
  : '';

interface APIResponse<T> {
  success: boolean;
  data: T;
  message: string;
}

async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${BASE_URL}/api${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

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
    throw error;
  }
}

// Dashboard API
export interface DashboardOverview {
  total_products: number;
  today_orders: number;
  today_gmv: string;
  avg_order_value: string;
  total_customers: number;
  conversion_rate: number;
  pending_alerts: number;
  pending_tasks: number;
}

export async function getDashboardOverview(): Promise<DashboardOverview> {
  return fetchAPI<DashboardOverview>('/dashboard/overview');
}

// Analytics API
export interface SalesTrendData {
  date: string;
  quantity: number;
  revenue: number;
}

export interface ProductPerformance {
  product_id: string;
  name: string;
  category: string;
  retail_price: number;
  channel_price: number;
  status: string;
  performance_score: number;
}

export async function getSalesTrend(): Promise<SalesTrendData[]> {
  return fetchAPI<SalesTrendData[]>('/analytics/sales-trend');
}

export async function getProductPerformance(): Promise<ProductPerformance[]> {
  return fetchAPI<ProductPerformance[]>('/analytics/product-performance');
}

// Category Analysis API
export interface CategoryAnalysis {
  category: string;
  product_count: number;
  active_products: number;
  avg_price: number;
  min_price: number;
  max_price: number;
  price_range: string;
}

export async function getCategoryAnalysis(): Promise<CategoryAnalysis[]> {
  return fetchAPI<CategoryAnalysis[]>('/analytics/category-analysis');
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

export async function getCompetitorOverview(): Promise<CompetitorOverview> {
  return fetchAPI<CompetitorOverview>('/competitors/overview');
}

export async function getPriceComparison(limit: number = 20): Promise<PriceComparison[]> {
  return fetchAPI<PriceComparison[]>(`/competitors/price-comparison?limit=${limit}`);
}

// Reports API
export interface ReportData {
  order_count: number;
  total_revenue: number;
  avg_order_value_gmv: number;
  avg_order_value_paid: number;
  avg_order_value: number;
  refund_count: number;
  refund_rate: number;
  cs_responses: number;
  data_period?: string;
  // Backward compatibility
  period?: string;
  metrics?: Record<string, number>;
  top_products?: Array<{name: string, value: number}>;
}

export async function getDailyReport(): Promise<ReportData> {
  return fetchAPI<ReportData>('/reports/daily');
}

export async function getWeeklyReport(): Promise<ReportData> {
  return fetchAPI<ReportData>('/reports/weekly');
}

export async function getMonthlyReport(): Promise<ReportData> {
  return fetchAPI<ReportData>('/reports/monthly');
}

// Alerts API
export interface Alert {
  alert_id: string;
  type: string;
  severity: 'low' | 'medium' | 'high';
  title: string;
  description: string;
  product_id?: string;
  status: string;
  created_at: string;
  resolved_at?: string;
  // Backward compatibility
  message?: string;
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
  category: string;
  status?: 'active' | 'inactive' | 'out_of_stock';
  // Backward compatibility
  id?: string;
  price?: number;
  inventory?: number;
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

export async function getProducts(page: number = 1, limit: number = 20): Promise<ProductsResponse> {
  const response = await fetchAPI<ProductsResponse>(`/products/inventory?page=${page}&limit=${limit}`);
  // Transform for backward compatibility
  if (response.low_stock_items && !response.products) {
    response.products = response.low_stock_items.map(item => ({
      ...item,
      id: item.product_id,
      name: item.name,
      price: item.retail_price,
      inventory: item.estimated_stock || 0,
      category: item.category,
      status: item.estimated_stock && item.estimated_stock <= 10 ? 'out_of_stock' as const : 'active' as const
    }));
    response.total = response.summary.total_products;
    response.page = page;
    response.limit = limit;
  }
  return response;
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
  status: 'pending' | 'processing' | 'completed' | 'refunded';
  created_at: string;
}

export interface OrderStats {
  today_orders: number;
  completion_rate: number;
  refund_rate: number;
  avg_delivery_time: number;
}

export async function getOrders(page: number = 1, limit: number = 20, status: string = 'all'): Promise<{
  orders: Order[];
  total: number;
  page: number;
  limit: number;
}> {
  return fetchAPI(`/orders/list?page=${page}&limit=${limit}&status=${status}`);
}

export async function getOrderStats(): Promise<OrderStats> {
  return fetchAPI<OrderStats>('/orders/stats');
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
  return fetchAPI<PricingSuggestion[]>('/pricing/suggestions', {
    method: 'POST',
  });
}

export async function getPricingRules(): Promise<PricingRule[]> {
  return fetchAPI<PricingRule[]>('/pricing/rules');
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
  return fetchAPI<RestockSuggestion[]>('/inventory/restock-suggestions');
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
