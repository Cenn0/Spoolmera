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
  readonly lowStock = computed(() => this.spools().filter(item => item.remaining_g > 0 && item.remaining_g <= item.low_stock_threshold_g)
    .sort((a, b) => a.remaining_g - b.remaining_g));
  readonly available = computed(() => this.spools().filter(item => item.remaining_g > 0));

  private readonly versions: Record<'overview'|'products'|'spools'|'movements',number> =
    {overview:0,products:0,spools:0,movements:0};

  async load(sections: ('overview'|'products'|'spools'|'movements')[] =
      ['overview','products','spools','movements']): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    // Per-slice request generations avoid overwriting a newer completed refresh.
    const requests=sections.map(section=>{
      const version=++this.versions[section];
      switch(section){
        case 'overview':
          return firstValueFrom(this.http.get<Overview>('/api/overview'))
            .then(value=>{if(this.versions.overview===version)this.overview.set(value);});
        case 'products':
          return firstValueFrom(this.http.get<Product[]>('/api/products'))
            .then(value=>{if(this.versions.products===version)this.products.set(value);});
        case 'spools':
          return firstValueFrom(this.http.get<Spool[]>('/api/spools'))
            .then(value=>{if(this.versions.spools===version)this.spools.set(value);});
        case 'movements':
          return firstValueFrom(this.http.get<Movement[]>('/api/movements?limit=200'))
            .then(value=>{if(this.versions.movements===version)this.movements.set(value);});
      }
    });
    try{await Promise.all(requests);this.ready.set(true);}
    catch(error){this.error.set(apiError(error));}
    finally{this.loading.set(false);}
  }

  async createProduct(payload: ProductInput): Promise<void> {
    await firstValueFrom(this.http.post('/api/products', payload));
    await this.load(['overview','products']);
  }
  async updateProduct(id: number, payload: ProductInput): Promise<void> {
    await firstValueFrom(this.http.put('/api/products/' + id, payload));
    await this.load(['products','spools','movements']);
  }
  async createSpool(payload: SpoolInput): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools', payload));
    await this.load();
  }
  async updateSpool(id: number, payload: {location: string; notes: string; opened: boolean}): Promise<void> {
    await firstValueFrom(this.http.patch('/api/spools/' + id, payload));
    await this.load(['overview','spools']);
  }
  async move(id: number, kind: 'consume' | 'adjust', grams: number, note: string): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/movements', {kind, grams, note}));
    await this.load();
  }
  async weigh(id: number, gross_g: number, tare_g: number, note: string): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/weigh', {gross_g,tare_g,note}));
    await this.load();
  }
  async dry(id: number, temperature_c: number, duration_minutes: number, note: string): Promise<void> {
    await firstValueFrom(this.http.post('/api/spools/' + id + '/drying',
      {temperature_c,duration_minutes,note,dried_at:new Date().toISOString()}));
  }
  dryingRecords(id: number): Promise<{id:number;temperature_c:number;duration_minutes:number;dried_at:string;note:string}[]> {
    return firstValueFrom(this.http.get<{id:number;temperature_c:number;duration_minutes:number;dried_at:string;note:string}[]>('/api/spools/' + id + '/drying'));
  }
  identifiers(id:number):Promise<{namespace:string;external_id:string;created_at:string}[]> {
    return firstValueFrom(this.http.get<{namespace:string;external_id:string;created_at:string}[]>('/api/spools/'+id+'/identifiers'));
  }
  registerIdentifier(id:number,namespace:string,external_id:string):Promise<void> {
    return firstValueFrom(this.http.post<void>('/api/spools/'+id+'/identifiers',{namespace,external_id}));
  }
  deleteIdentifier(id:number,namespace:string,external_id:string):Promise<void> {
    return firstValueFrom(this.http.delete<void>('/api/spools/'+id+'/identifiers/'
      +encodeURIComponent(namespace)+'/'+encodeURIComponent(external_id)));
  }
  resolveIdentifier(namespace:string,external_id:string):Promise<{id:number;uid:string}> {
    return firstValueFrom(this.http.get<{id:number;uid:string}>('/api/identifiers/'
      +encodeURIComponent(namespace)+'/'+encodeURIComponent(external_id)));
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
