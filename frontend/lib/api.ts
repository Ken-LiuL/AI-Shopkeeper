// API client for AI店长 backend
const BASE_URL = process.env.NODE_ENV === 'development' ? '' : '';

async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`/api${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }

    return response.json();
  } catch (error) {
    console.error(`Error fetching ${endpoint}:`, error);
    throw error;
  }
}

// Dashboard API
export interface DashboardOverview {
  today_gmv: number;
  orders: number;
  avg_order_value: number;
  total_customers: number;
  pending_alerts: number;
}

export async function getDashboardOverview(): Promise<DashboardOverview> {
  return fetchAPI<DashboardOverview>('/dashboard/overview');
}

// Analytics API
export interface SalesTrendData {
  date: string;
  gmv: number;
  orders: number;
}

export interface ProductPerformance {
  name: string;
  revenue: number;
  orders: number;
  category: string;
}

export async function getSalesTrend(): Promise<SalesTrendData[]> {
  return fetchAPI<SalesTrendData[]>('/analytics/sales-trend');
}

export async function getProductPerformance(): Promise<ProductPerformance[]> {
  return fetchAPI<ProductPerformance[]>('/analytics/product-performance');
}

// Competitors API
export interface CompetitorOverview {
  summary: string;
  top_categories: string[];
}

export interface PriceComparison {
  name: string;
  our_price: number;
  competitor_price: number;
  competitor_store: string;
  price_diff_pct: number;
}

export async function getCompetitorOverview(): Promise<CompetitorOverview> {
  return fetchAPI<CompetitorOverview>('/competitors/overview');
}

export async function getPriceComparison(limit: number = 20): Promise<PriceComparison[]> {
  return fetchAPI<PriceComparison[]>(`/competitors/price-comparison?limit=${limit}`);
}

// Reports API
export interface ReportData {
  period: string;
  metrics: Record<string, number>;
  top_products: Array<{name: string, value: number}>;
}

export async function getDailyReport(): Promise<ReportData> {
  return fetchAPI<ReportData>('/reports/daily');
}

// Alerts API
export interface Alert {
  type: string;
  severity: 'low' | 'medium' | 'high';
  message: string;
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
  response: string;
  sources: string[];
}

export async function sendChatMessage(data: ChatMessage): Promise<ChatResponse> {
  return fetchAPI<ChatResponse>('/customer-service/chat', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

// Products API
export interface Product {
  id: string;
  name: string;
  price: number;
  inventory: number;
  category: string;
  status: 'active' | 'inactive' | 'out_of_stock';
}

export interface ProductsResponse {
  products: Product[];
  total: number;
  page: number;
  limit: number;
}

export async function getProducts(page: number = 1, limit: number = 20): Promise<ProductsResponse> {
  return fetchAPI<ProductsResponse>(`/products/inventory?page=${page}&limit=${limit}`);
}

// Store KPIs API
export interface StoreKPIs {
  [key: string]: number | string;
}

export async function getStoreKPIs(): Promise<StoreKPIs> {
  return fetchAPI<StoreKPIs>('/dashboard/store-kpis');
}
