import { describe, expect, it } from 'vitest';
import { product } from '../../testing/fixtures';
import { ProductFilters, productOrder, selectProducts, summarizeProducts } from './product-view';

const products = [
  product({id: 1, brand: 'Maker 10', name: 'Matte', material: 'PLA', color_name: 'Grün', color_hex: '#227755', total_remaining_g: 2500, spool_count: 3}),
  product({id: 2, brand: 'Maker 2', name: 'Basic', material: 'PLA', color_name: 'Black', total_remaining_g: 0, spool_count: 2}),
  product({id: 3, brand: 'Maker 2', name: 'Clear', material: 'PETG', color_name: 'Ocean', color_hex: '#337799', total_remaining_g: 310, spool_count: 1}),
];
const defaults: ProductFilters = {query: '', material: '', stockOnly: false, order: 'name'};
const select = (overrides: Partial<ProductFilters> = {}) => selectProducts(products, {...defaults, ...overrides}, 'de-DE');

describe('filament gallery view', () => {
  it('sorts names naturally without changing inventory order or records', () => {
    const before = JSON.stringify(products);
    expect(select().map(item => item.id)).toEqual([2, 3, 1]);
    expect(JSON.stringify(products)).toBe(before);
    expect(select().find(item => item.id === 1)).toBe(products[0]);
  });
  it.each([
    ['stock-low', [2, 3, 1]], ['stock-high', [1, 3, 2]], ['material', [3, 2, 1]],
  ] as const)('supports %s ordering across all products', (order, ids) => {
    expect(select({order}).map(item => item.id)).toEqual(ids);
  });
  it('matches multiple search terms across fields regardless of word order', () => {
    expect(select({query: '  OCEAN   maker PETG  '}).map(item => item.id)).toEqual([3]);
  });
  it('normalizes equivalent Unicode without rewriting the stored color name', () => {
    const result = select({query: 'Gru\u0308n'});
    expect(result.map(item => item.id)).toEqual([1]);
    expect(result[0].color_name).toBe('Grün');
  });
  it('can find a recorded hex color', () => {
    expect(select({query: '#337799'}).map(item => item.id)).toEqual([3]);
  });
  it('combines text, exact material and nonzero-stock filters', () => {
    expect(select({query: 'Maker', material: 'PLA', stockOnly: true}).map(item => item.id)).toEqual([1]);
    expect(select({material: 'PET'})).toEqual([]);
  });
  it('keeps zero-stock products unless explicitly filtered', () => {
    expect(select().length).toBe(3);
    expect(select({stockOnly: true, order: 'stock-low'}).map(item => item.id)).toEqual([3, 1]);
  });
  it('derives roll and gram totals from the same filtered products', () => {
    expect(summarizeProducts(select({query: 'Ocean'}))).toEqual({products: 1, spools: 1, remaining_g: 310});
    expect(summarizeProducts(select())).toEqual({products: 3, spools: 6, remaining_g: 2810});
    expect(summarizeProducts(select({query: 'missing'}))).toEqual({products: 0, spools: 0, remaining_g: 0});
  });
  it('uses stable identity as a final tie breaker', () => {
    const same = [product({id: 4}), product({id: 2})];
    expect(selectProducts(same, {...defaults, order: 'stock-low'}, 'en-US').map(item => item.id)).toEqual([2, 4]);
  });
  it.each([null, undefined, '', '<script>', 'unexpected', 42])('falls back for malformed stored preferences: %s', value => {
    expect(productOrder(value)).toBe('name');
  });
  it.each(['name', 'material', 'stock-low', 'stock-high'])('retains valid preference %s', value => {
    expect(productOrder(value)).toBe(value);
  });
});
