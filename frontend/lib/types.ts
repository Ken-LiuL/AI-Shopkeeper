export interface APIResponse<T> {
  success: boolean;
  data: T | null;
  message: string;
}

export interface PaginatedResponse<T> {
  success: boolean;
  data: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface DashboardOverview {
  total_products: number;
  today_orders: number;
  pending_alerts: number;
  pending_tasks: number;
}

export interface SalesTrendPoint {
  date: string;
  quantity: number;
  revenue: number;
}

export interface TopProduct {
  product_id: string;
  name: string;
  total_sales: number;
  revenue: number;
}

export interface Product {
  product_id: string;
  name: string;
  barcode: string | null;
  category: string | null;
  brand: string | null;
  description: string | null;
  cost_price: number | null;
  retail_price: number | null;
  stock: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface SelectionRunSummary {
  run_id: string;
  status: string;
  keywords: string[];
  categories: string[];
  result_count: number;
  created_at: string | null;
}

export interface Recommendation {
  rank?: number;
  product_name?: string;
  name?: string;
  score?: number;
  total_score?: number;
  breakdown?: Record<string, number>;
  suggestion?: string;
  [key: string]: unknown;
}

export interface Alert {
  alert_id: string;
  product_id: string | null;
  product_name?: string;
  alert_type: string;
  severity: string;
  status: string;
  title?: string;
  description?: string;
  root_cause?: string;
  suggestion?: string;
  created_at: string;
  resolved_at: string | null;
}

export interface Bundle {
  bundle_id: string;
  name: string;
  tagline?: string;
  products: BundleItem[];
  original_price: number;
  bundle_price: number;
  discount_percent?: number;
  confidence?: number;
  lift?: number;
  status: string;
  created_at: string;
}

export interface BundleItem {
  product_id: string;
  name: string;
  unit_price: number;
  role?: string;
}

export interface TaskCreatedResponse {
  success: boolean;
  task_id: string;
  message: string;
}
