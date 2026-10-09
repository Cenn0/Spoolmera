import { HttpClient, HttpErrorResponse, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiMovementPage, ApiRestock, ApiSpoolBatch, ApiSpoolPage, ApiSpoolBatchInput, ApiMovementInput, ApiWeighInput, ApiDryingInput } from './core/api/generated-contracts';
import { Capabilities, CsvPreview, EMPTY_OVERVIEW, Movement, Overview, Product, ProductInput, Spool, SpoolInput, SpoolUpdate, isLowStock } from './models';

type Section = 'overview' | 'products' | 'spools' | 'movements';
const ALL_SECTIONS: Section[] = ['overview', 'products', 'spools', 'movements'];
export interface MovementFilters {
  spool_id?: number; job_id?: number; actor_id?: number;
  source?: string; from_date?: string; to_date?: string; kind?: string;
}
export function apiError(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    const detail: unknown = error.error?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((item: {loc?: string[]; msg?: string}) =>
      (item.loc || []).slice(1).join('.') + ': ' + (item.msg || 'Invalid field')).join(' · ');
    if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message;
    return error.status ? 'Request failed (HTTP ' + error.status + ').' : 'Unable to connect to the server.';
  }
  return error instanceof Error ? error.message : 'Unexpected error.';
}

@Injectable({providedIn: 'root'})
export class InventoryService {
  private readonly http = inject(HttpClient);
  readonly overview = signal<Overview>(EMPTY_OVERVIEW);
  readonly products = signal<Product[]>([]);
  readonly spools = signal<Spool[]>([]);
  readonly movements = signal<Movement[]>([]);
  private readonly requests = signal(0);
  private readonly failures = signal<Partial<Record<Section, string>>>({});
  readonly loading = computed(() => this.requests() > 0);
  readonly ready = signal(false);
  readonly error = computed(() => [...new Set(Object.values(this.failures()))].filter(Boolean).join(' · '));
  readonly changed = signal(0);
  readonly lastUpdated = signal<string | null>(null);
  readonly lowStock = computed(() => this.spools().filter(isLowStock).sort((a, b) => a.remaining_g - b.remaining_g));
  readonly available = computed(() => this.spools().filter(item => item.remaining_g > 0));
  private lifecycle=0;
  private readonly versions: Record<Section, number> = {overview: 0, products: 0, spools: 0, movements: 0};

  async load(sections: Section[] = ALL_SECTIONS): Promise<boolean> {
    const lifecycle=this.lifecycle;
    const work = [...new Set(sections)].map(async section => {
      const version = ++this.versions[section];
      this.requests.update(count => count + 1);
      try {
        switch (section) {
          case 'overview': {
            const value = await firstValueFrom(this.http.get<Overview>('/api/overview'));
            if (this.versions[section] === version) this.overview.set(value); break;
          }
          case 'products': {
            const value = await firstValueFrom(this.http.get<Product[]>('/api/products'));
            if (this.versions[section] === version) this.products.set(value); break;
          }
          case 'spools': {
            const value = await firstValueFrom(this.http.get<Spool[]>('/api/spools'));
            if (this.versions[section] === version) this.spools.set(value); break;
          }
          case 'movements': {
            const value = await firstValueFrom(this.http.get<Movement[]>('/api/movements?limit=200'));
            if (this.versions[section] === version) this.movements.set(value); break;
          }
        }
        if (this.versions[section] === version) this.failures.update(old => ({...old, [section]: ''}));
        return this.versions[section]===version;
      } catch (error) {
        if (this.versions[section] === version) this.failures.update(old => ({...old, [section]: apiError(error)}));
        return false;
      } finally { this.requests.update(count => count - 1); }
    });
    const results = await Promise.all(work);
    if (this.lifecycle===lifecycle && results.every(Boolean)) { this.ready.set(true); this.lastUpdated.set(new Date().toISOString()); }
    return this.lifecycle===lifecycle&&results.every(Boolean);
  }
  reset(): void {
    ++this.lifecycle;
    for (const section of ALL_SECTIONS) ++this.versions[section];
    this.overview.set(EMPTY_OVERVIEW); this.products.set([]); this.spools.set([]); this.movements.set([]);
    this.failures.set({}); this.ready.set(false); this.lastUpdated.set(null);
  }
  private async afterChange(sections: Section[] = ALL_SECTIONS): Promise<void> {
    this.changed.update(value => value + 1);
    await this.load(sections);
  }
  async createProduct(payload: ProductInput): Promise<void> {
    await firstValueFrom(this.http.post('/api/products', payload));
    await this.afterChange(['overview', 'products']);
  }
  async updateProduct(id: number, payload: ProductInput): Promise<void> {
    await firstValueFrom(this.http.put('/api/products/' + id, payload));
    await this.afterChange();
  }
  async createSpool(payload: SpoolInput): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools', payload)); await this.afterChange();
  }
  async createBatch(count: number, spool: SpoolInput, request_id?: string): Promise<ApiSpoolBatch> {
    const result = await firstValueFrom(this.http.post<ApiSpoolBatch>('/api/spools/batch', {count, spool, request_id} satisfies ApiSpoolBatchInput));
    await this.afterChange(); return result;
  }
  async updateSpool(id: number, payload: SpoolUpdate): Promise<void> {
    await firstValueFrom(this.http.patch('/api/spools/' + id, payload)); await this.afterChange();
  }
  async move(id: number, kind: 'consume' | 'adjust', grams: number, note: string): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/movements', {kind, grams, note} satisfies ApiMovementInput)); await this.afterChange();
  }
  async weigh(id: number, gross_g: number, tare_g: number, note: string, expected_stock_revision?: number): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/weigh', {gross_g, tare_g, note, expected_stock_revision} satisfies ApiWeighInput));
    await this.afterChange();
  }
  async dry(id: number, temperature_c: number, duration_minutes: number, note: string, dried_at: string): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/drying', {temperature_c, duration_minutes, note, dried_at} satisfies ApiDryingInput));
    this.changed.update(value => value + 1);
  }
  dryingRecords(id: number): Promise<{id: number; temperature_c: number; duration_minutes: number; dried_at: string; note: string}[]> {
    return firstValueFrom(this.http.get<{id: number; temperature_c: number; duration_minutes: number; dried_at: string; note: string}[]>('/api/spools/' + id + '/drying'));
  }
  identifiers(id: number): Promise<{namespace: string; external_id: string; created_at: string}[]> {
    return firstValueFrom(this.http.get<{namespace: string; external_id: string; created_at: string}[]>('/api/spools/' + id + '/identifiers'));
  }
  registerIdentifier(id: number, namespace: string, external_id: string): Promise<void> {
    return firstValueFrom(this.http.post<void>('/api/spools/' + id + '/identifiers', {namespace, external_id}));
  }
  deleteIdentifier(id: number, namespace: string, external_id: string): Promise<void> {
    return firstValueFrom(this.http.delete<void>('/api/spools/' + id + '/identifiers/' + encodeURIComponent(namespace) + '/' + encodeURIComponent(external_id)));
  }
  resolveIdentifier(namespace: string, external_id: string): Promise<{id: number; uid: string}> {
    return firstValueFrom(this.http.get<{id: number; uid: string}>('/api/identifiers/' + encodeURIComponent(namespace) + '/' + encodeURIComponent(external_id)));
  }
  spoolByUid(uid: string): Promise<Spool> {
    return firstValueFrom(this.http.get<Spool>('/api/spools/by-uid/' + encodeURIComponent(uid)));
  }
  async archive(id: number): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/archive', {})); await this.afterChange();
  }
  async unarchive(id: number): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/unarchive', {})); await this.afterChange();
  }
  spoolPage(archived: 'active' | 'archived' | 'all', cursor?: number, query = '', material = '', status = '', productId?: number): Promise<ApiSpoolPage> {
    let params = new HttpParams().set('archived', archived).set('limit', 100);
    if (cursor) params = params.set('before_id', cursor);
    if (query.trim()) params = params.set('q', query.trim());
    if (material) params = params.set('material',material);
    if (status) params = params.set('status',status);
    if (productId) params = params.set('product_id', productId);
    return firstValueFrom(this.http.get<ApiSpoolPage>('/api/spools/page', {params}));
  }
  movementsFor(id: number): Promise<Movement[]> {
    return firstValueFrom(this.http.get<Movement[]>('/api/spools/' + id + '/movements'));
  }
  movementPage(filters: MovementFilters, before?: number): Promise<ApiMovementPage> {
    let params = new HttpParams().set('limit', 50);
    if (before) params = params.set('before_id', before);
    for (const [key, value] of Object.entries(filters)) if (value !== '' && value != null) params = params.set(key, value);
    return firstValueFrom(this.http.get<ApiMovementPage>('/api/movements/page', {params}));
  }
  restock(): Promise<ApiRestock> { return firstValueFrom(this.http.get<ApiRestock>('/api/inventory/restock')); }
  capabilities(): Promise<Capabilities> { return firstValueFrom(this.http.get<Capabilities>('/api/integrations/v1/capabilities')); }
  private csv(file: Blob, dryRun: boolean): Promise<CsvPreview> {
    return firstValueFrom(this.http.post<CsvPreview>('/api/import/inventory.csv?dry_run=' + dryRun, file,
      {headers: new HttpHeaders({'Content-Type': 'text/csv'})}));
  }
  previewCsv(file: Blob): Promise<CsvPreview> { return this.csv(file, true); }
  async importCsv(file: Blob): Promise<CsvPreview> {
    const result = await this.csv(file, false); await this.afterChange(); return result;
  }
}
