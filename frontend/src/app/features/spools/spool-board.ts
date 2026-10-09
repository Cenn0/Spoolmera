import type { Spool } from '../../models';

export type SpoolSort = 'newest' | 'name' | 'remaining-low' | 'remaining-high' | 'location';
export interface StorageLane { location: string; spools: Spool[]; totalG: number; }

export function spoolSort(value: unknown): SpoolSort {
  return value === 'name' || value === 'remaining-low' || value === 'remaining-high' || value === 'location'
    ? value : 'newest';
}

/** Sort visible rows without mutating the API response or the shared inventory. */
export function orderSpools(spools: readonly Spool[], mode: SpoolSort, locale: string): Spool[] {
  if(mode === 'newest') return [...spools]; // API already supplies newest first.
  const collator = new Intl.Collator(locale, {numeric: true, sensitivity: 'base'});
  const byName = (a: Spool, b: Spool) => collator.compare(a.brand, b.brand) ||
    collator.compare(a.product_name, b.product_name) || collator.compare(a.color_name, b.color_name) || a.id - b.id;
  return [...spools].sort((a, b) => {
    if(mode === 'name') return byName(a, b);
    if(mode === 'remaining-low') return a.remaining_g - b.remaining_g || byName(a, b);
    if(mode === 'remaining-high') return b.remaining_g - a.remaining_g || byName(a, b);
    return collator.compare(a.location || '', b.location || '') || byName(a, b);
  });
}

/** Location columns reflect the loaded page; globally known labels remain available as drop targets. */
export function storageLanes(spools: readonly Spool[], locations: readonly string[], locale: string): StorageLane[] {
  const names = new Set<string>(['']);
  for (const name of locations) names.add(name.trim());
  for (const spool of spools) names.add((spool.location || '').trim());
  const lanes = new Map([...names].map(location => [location, {location, spools: [] as Spool[], totalG: 0}]));
  for(const spool of spools){
    const lane = lanes.get((spool.location || '').trim())!;
    lane.spools.push(spool); lane.totalG += spool.remaining_g;
  }
  const collator = new Intl.Collator(locale, {numeric: true, sensitivity: 'base'});
  return [...lanes.values()].sort((a,b) => !a.location ? -1 : !b.location ? 1 : collator.compare(a.location,b.location));
}
