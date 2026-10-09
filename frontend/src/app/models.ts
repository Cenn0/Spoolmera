import type { ApiOverview, ApiProduct, ApiSpool, ApiCapabilities } from './core/api/generated-contracts';

export interface Overview {
  total_spools: number;
  remaining_g: number;
  opened_spools: number;
  sealed_spools: number;
  empty_spools: number;
  low_spools: number;
  total_products: number;
}
export interface Product {
  id: number;
  uid: string;
  brand: string;
  name: string;
  material: string;
  color_name: string;
  color_hex: string;
  diameter_mm: number;
  notes: string;
  density_g_cm3: number | null;
  nozzle_min_c: number | null;
  nozzle_max_c: number | null;
  bed_min_c: number | null;
  bed_max_c: number | null;
  gtin: string;
  manufacturer_sku: string;
  slicer_preset: string;
  low_stock_threshold_g: number;
  spool_count: number;
  total_remaining_g: number;
  created_at: string;
  updated_at: string;
}
export interface ProductInput {
  brand: string;
  name: string;
  material: string;
  color_name: string;
  color_hex: string;
  diameter_mm: number;
  notes: string;
  density_g_cm3: number | null;
  nozzle_min_c: number | null;
  nozzle_max_c: number | null;
  bed_min_c: number | null;
  bed_max_c: number | null;
  gtin: string;
  manufacturer_sku: string;
  slicer_preset: string;
  low_stock_threshold_g: number;
}
export interface Spool {
  id: number;
  uid: string;
  product_id: number;
  brand: string;
  product_name: string;
  material: string;
  color_name: string;
  color_hex: string;
  diameter_mm: number;
  initial_g: number;
  remaining_g: number;
  opened: boolean;
  status: 'sealed' | 'opened' | 'empty';
  location: string;
  notes: string;
  created_at: string;
  archived_at: string | null;
  tare_g: number;
  purchase_price_cents: number | null;
  purchase_currency: string;
  purchased_on: string | null;
  batch: string;
  low_stock_threshold_g: number;
}
export interface SpoolInput {
  product_id: number;
  initial_g: number;
  remaining_g: number | null;
  opened: boolean;
  location: string;
  notes: string;
  tare_g: number;
  purchase_price_cents: number | null;
  purchase_currency: string;
  purchased_on: string | null;
  batch: string;
}
export interface Movement {
  id: number;
  spool_id: number;
  kind: 'initial' | 'consume' | 'adjust';
  delta_g: number;
  remaining_after_g: number;
  note: string;
  created_at: string;
  brand?: string;
  product_name?: string;
  material?: string;
  color_name?: string;
  color_hex?: string;
}
export interface CsvPreview {
  dry_run: boolean;
  products_created: number;
  products_skipped: number;
  spools_created: number;
  spools_skipped: number;
}
export interface Capabilities {
  schema_version: string;
  inventory_read: boolean;
  usage_write: boolean;
  printer_connections: boolean;
  slicer_connections: boolean;
}
export const EMPTY_OVERVIEW: Overview = {
  total_spools: 0, remaining_g: 0, opened_spools: 0, sealed_spools: 0,
  empty_spools: 0, low_spools: 0, total_products: 0
};
export function grams(value: number): string {
  return Math.abs(value) >= 1000
    ? new Intl.NumberFormat('en-US', {maximumFractionDigits: 2}).format(value / 1000) + ' kg'
    : new Intl.NumberFormat('en-US').format(value) + ' g';
}
export function stockPercent(spool: Spool): number {
  return spool.initial_g > 0 ? Math.max(0, Math.min(100, 100 * spool.remaining_g / spool.initial_g)) : 0;
}
export function dateText(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('en-US', {dateStyle:'medium', timeStyle:'short'});
}

// Statically validate that the handcrafted UI models satisfy generated API contracts.
const _overviewContract: ApiOverview = {} as Overview;
const _productContract: ApiProduct = {} as Product;
const _spoolContract: ApiSpool = {} as Spool;
const _capabilitiesContract: ApiCapabilities = {} as Capabilities;
void [_overviewContract, _productContract, _spoolContract, _capabilitiesContract];
