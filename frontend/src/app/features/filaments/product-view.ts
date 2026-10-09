import type { Product } from '../../models';

export type ProductOrder = 'name' | 'material' | 'stock-low' | 'stock-high';
export interface ProductFilters {
  query: string;
  material: string;
  stockOnly: boolean;
  order: ProductOrder;
}

export function productOrder(value: unknown): ProductOrder {
  return value === 'material' || value === 'stock-low' || value === 'stock-high' ? value : 'name';
}

/** Derive a view without reordering the shared inventory or modifying user data. */
export function selectProducts(products: readonly Product[], filters: ProductFilters, locale: string): Product[] {
  const normalize = (text: string): string => text.normalize('NFC').toLocaleLowerCase(locale);
  const terms = normalize(filters.query.trim()).split(/\s+/u).filter(Boolean);
  const collator = new Intl.Collator(locale, {numeric: true, sensitivity: 'base'});
  const byName = (left: Product, right: Product): number =>
    collator.compare(left.brand, right.brand) || collator.compare(left.name, right.name) ||
    collator.compare(left.color_name, right.color_name) || left.id - right.id;

  return products.filter(product => {
    const text = normalize([product.brand, product.name, product.material, product.color_name, product.color_hex].join(' '));
    return terms.every(term => text.includes(term)) && (!filters.material || product.material === filters.material) &&
      (!filters.stockOnly || product.total_remaining_g > 0);
  }).sort((left, right) => {
    if (filters.order === 'stock-low') return left.total_remaining_g - right.total_remaining_g || byName(left, right);
    if (filters.order === 'stock-high') return right.total_remaining_g - left.total_remaining_g || byName(left, right);
    if (filters.order === 'material') return collator.compare(left.material, right.material) || byName(left, right);
    return byName(left, right);
  });
}

/** All three values describe the same filtered products, never the global overview. */
export function summarizeProducts(products: readonly Product[]): {products: number; spools: number; remaining_g: number} {
  return products.reduce((total, product) => ({
    products: total.products + 1,
    spools: total.spools + product.spool_count,
    remaining_g: total.remaining_g + product.total_remaining_g,
  }), {products: 0, spools: 0, remaining_g: 0});
}

/** Display stock against an optional product target, without changing inventory values. */
export function targetStockPercent(product: Pick<Product,'target_stock_g'|'total_remaining_g'>): number {
  return product.target_stock_g > 0 ? Math.max(0, Math.min(100, 100 * product.total_remaining_g / product.target_stock_g)) : 0;
}
export function belowWarning(product: Pick<Product,'low_stock_threshold_g'|'total_remaining_g'>): boolean {
  return product.low_stock_threshold_g > 0 && product.total_remaining_g <= product.low_stock_threshold_g;
}
