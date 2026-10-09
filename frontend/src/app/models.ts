import type {
  ApiOverview, ApiProduct, ApiSpool, ApiCapabilities, ApiMovement,
  ApiProductInput, ApiSpoolInput, ApiSpoolUpdate, ApiCsvPreview,
} from './core/api/generated-contracts';

export type Overview = ApiOverview;
export type Product = ApiProduct;
export type Spool = ApiSpool;
export type Movement = ApiMovement;
export type Capabilities = ApiCapabilities;
// Forms explicitly initialize optional API fields. They use the generated
// contract rather than a second set of independently maintained properties.
export type ProductInput = Required<ApiProductInput>;
export type SpoolInput = Required<ApiSpoolInput>;
export type SpoolUpdate = ApiSpoolUpdate;
export type CsvPreview=ApiCsvPreview;
export const EMPTY_OVERVIEW: Overview = {
  total_spools: 0, remaining_g: 0, opened_spools: 0, sealed_spools: 0,
  empty_spools: 0, low_spools: 0, total_products: 0,
};
export function grams(value: number): string {
  return Math.abs(value) >= 1000
    ? new Intl.NumberFormat('en-US', {maximumFractionDigits: 2}).format(value / 1000) + ' kg'
    : new Intl.NumberFormat('en-US').format(value) + ' g';
}
export function stockPercent(spool: Pick<Spool, 'initial_g' | 'remaining_g'>): number {
  return spool.initial_g > 0 ? Math.max(0, Math.min(100, 100 * spool.remaining_g / spool.initial_g)) : 0;
}
export function isLowStock(spool: Pick<Spool, 'remaining_g' | 'low_stock_threshold_g'>): boolean {
  return spool.remaining_g > 0 && spool.remaining_g <= spool.low_stock_threshold_g;
}
export function dateText(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('en-US', {dateStyle: 'medium', timeStyle: 'short'});
}
export function money(cents: number | null | undefined, currency: string): string {
  if (cents == null) return 'Not recorded';
  return new Intl.NumberFormat('en-US', {style: 'currency', currency}).format(cents / 100);
}
