import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { Capabilities, CsvPreview, EMPTY_OVERVIEW, Movement, Overview, Product, ProductInput, Spool, SpoolInput } from './models';

export function apiError(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    const detail: unknown = error.error?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((item: {loc?: string[]; msg?: string}) =>
      (item.loc || []).slice(1).join('.') + ': ' + (item.msg || 'Invalid field')).join(' · ');
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
  readonly loading = signal(true);
  readonly ready = signal(false);
  readonly error = signal('');
  readonly lowStock = computed(() => this.spools().filter(item => item.remaining_g > 0 && item.remaining_g <= 200)
    .sort((a, b) => a.remaining_g - b.remaining_g));
  readonly available = computed(() => this.spools().filter(item => item.remaining_g > 0));

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    try {
      const [overview, products, spools, movements] = await Promise.all([
        firstValueFrom(this.http.get<Overview>('/api/overview')),
        firstValueFrom(this.http.get<Product[]>('/api/products')),
        firstValueFrom(this.http.get<Spool[]>('/api/spools')),
        firstValueFrom(this.http.get<Movement[]>('/api/movements?limit=200')),
      ]);
      this.overview.set(overview);
      this.products.set(products);
      this.spools.set(spools);
      this.movements.set(movements);
      this.ready.set(true);
    } catch (error) {
      this.error.set(apiError(error));
    } finally {
      this.loading.set(false);
    }
  }

  async createProduct(payload: ProductInput): Promise<void> {
    await firstValueFrom(this.http.post('/api/products', payload));
    await this.load();
  }
  async updateProduct(id: number, payload: ProductInput): Promise<void> {
    await firstValueFrom(this.http.put('/api/products/' + id, payload));
    await this.load();
  }
  async createSpool(payload: SpoolInput): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools', payload));
    await this.load();
  }
  async updateSpool(id: number, payload: {location: string; notes: string; opened: boolean}): Promise<void> {
    await firstValueFrom(this.http.patch('/api/spools/' + id, payload));
    await this.load();
  }
  async move(id: number, kind: 'consume' | 'adjust', grams: number, note: string): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/movements', {kind, grams, note}));
    await this.load();
  }
  async archive(id: number): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/archive', {}));
    await this.load();
  }
  movementsFor(id: number): Promise<Movement[]> {
    return firstValueFrom(this.http.get<Movement[]>('/api/spools/' + id + '/movements'));
  }
  capabilities(): Promise<Capabilities> {
    return firstValueFrom(this.http.get<Capabilities>('/api/integrations/v1/capabilities'));
  }
  private csv(file: Blob, dryRun: boolean): Promise<CsvPreview> {
    return firstValueFrom(this.http.post<CsvPreview>(
      '/api/import/inventory.csv?dry_run=' + (dryRun ? 'true' : 'false'),
      file, {headers: new HttpHeaders({'Content-Type':'text/csv'})}
    ));
  }
  previewCsv(file: Blob): Promise<CsvPreview> { return this.csv(file, true); }
  async importCsv(file: Blob): Promise<CsvPreview> {
    const result = await this.csv(file, false);
    await this.load();
    return result;
  }
}
