import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { DialogService } from '../../dialog.service';
import { AuthService } from '../../auth.service';
import { apiError } from '../../inventory.service';
import { ProductInput } from '../../models';
import { RequestOwner } from '../../core/request-owner';

interface Entry {name:string;slug:string;}
interface MaterialEntry {material:string;slug:string;filament_count:number;}
interface FilamentEntry {name:string;slug:string;variant_count:number;}
interface VariantEntry {name:string;color_hex:string;slug:string;}
interface CatalogBrand {name:string;materials:MaterialEntry[];}
interface CatalogMaterial {material:string;filaments:FilamentEntry[];}
interface CatalogFilament {name:string;density?:number;min_print_temperature?:number;
  max_print_temperature?:number;min_bed_temperature?:number;max_bed_temperature?:number;
  variants:VariantEntry[];}
interface CatalogVariant {name:string;color_hex:string;sizes:CatalogSize[];}
interface CatalogSize {diameter:number;filament_weight:number;empty_spool_weight?:number;
  gtin?:string|number;article_number?:string;}

@Component({standalone:true,imports:[FormsModule],templateUrl:'./catalog.component.html'})
export class CatalogComponent implements OnInit, OnDestroy {
  readonly http=inject(HttpClient);readonly dialogs=inject(DialogService);
  readonly auth=inject(AuthService);readonly loading=signal(false);
  readonly error=signal('');readonly info=signal('');
  readonly brands=signal<Entry[]>([]);readonly brand=signal<CatalogBrand|null>(null);
  readonly material=signal<CatalogMaterial|null>(null);
  readonly filament=signal<CatalogFilament|null>(null);
  readonly variant=signal<CatalogVariant|null>(null);
  brandSlug='';materialSlug='';filamentSlug='';variantSlug='';sizeIndex=0;
  query='';
  private readonly requests=new RequestOwner();
  ngOnDestroy():void{this.requests.invalidate();}
  private async choose<T>(route:string,target:{set(value:T):void}):Promise<void>{
    const owner=this.requests.begin();this.loading.set(true);
    try{const result=await this.get<T>(route);if(this.requests.owns(owner))target.set(result);}
    catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
  private invalidate():void{this.requests.invalidate();this.loading.set(false);}
  get matches():Entry[] {
    const search=this.query.trim().toLowerCase();
    return this.brands().filter(b=>b.name.toLowerCase().includes(search)).slice(0,80);
  }
  private async get<T>(route:string):Promise<T> {
    return firstValueFrom(this.http.get<T>('/api/catalog/'+route));
  }
  async ngOnInit():Promise<void>{
    this.loading.set(true);this.error.set('');
    try{
      const result=await this.get<{version:string;brands:Entry[]}>('brands');
      this.brands.set(result.brands);this.info.set('Catalog '+(result.version||'unknown'));
    }catch(err){this.error.set(apiError(err));}
    finally{this.loading.set(false);}
  }
  async selectBrand():Promise<void>{
    this.invalidate();this.brand.set(null);this.material.set(null);this.filament.set(null);this.variant.set(null);
    this.materialSlug='';this.filamentSlug='';this.variantSlug='';this.error.set('');
    if(this.brandSlug)await this.choose('brands/'+encodeURIComponent(this.brandSlug),this.brand);
  }
  async selectMaterial():Promise<void>{
    this.invalidate();this.material.set(null);this.filament.set(null);this.variant.set(null);
    this.filamentSlug='';this.variantSlug='';this.error.set('');
    if(this.materialSlug)await this.choose('brands/'+encodeURIComponent(this.brandSlug)+'/materials/'+encodeURIComponent(this.materialSlug),this.material);
  }
  async selectFilament():Promise<void>{
    this.invalidate();this.filament.set(null);this.variant.set(null);this.variantSlug='';this.error.set('');
    if(this.filamentSlug)await this.choose('brands/'+encodeURIComponent(this.brandSlug)+'/materials/'+encodeURIComponent(this.materialSlug)+'/filaments/'+encodeURIComponent(this.filamentSlug),this.filament);
  }
  async selectVariant():Promise<void>{
    this.invalidate();this.variant.set(null);this.sizeIndex=0;this.error.set('');
    if(this.variantSlug)await this.choose('brands/'+encodeURIComponent(this.brandSlug)+'/materials/'+encodeURIComponent(this.materialSlug)+'/filaments/'+encodeURIComponent(this.filamentSlug)+'/variants/'+encodeURIComponent(this.variantSlug),this.variant);
  }
  useProduct():void{
    const b=this.brand(),m=this.material(),f=this.filament(),v=this.variant();
    if(!this.auth.canEdit()||!b||!m||!f||!v)return;
    const size=v.sizes?.[this.sizeIndex];
    const color=/^#[0-9A-Fa-f]{6}$/.test(v.color_hex||'')?v.color_hex:'#64748b';
    const num=(value:unknown,min:number,max:number):number|null=>
      typeof value==='number' && Number.isFinite(value) && value>=min && value<=max ? value : null;
    const values:Partial<ProductInput>={
      brand:b.name,name:f.name,material:m.material,color_name:v.name,color_hex:color,
      diameter_mm:num(size?.diameter,1,3.5)??1.75,
      density_g_cm3:num(f.density,0.01,10),
      nozzle_min_c:num(f.min_print_temperature,0,400),
      nozzle_max_c:num(f.max_print_temperature,0,400),
      bed_min_c:num(f.min_bed_temperature,0,200),
      bed_max_c:num(f.max_bed_temperature,0,200),
      gtin:size?.gtin!=null?String(size.gtin):'',
      manufacturer_sku:size?.article_number||'',
    };
    this.dialogs.open({kind:'product',catalog:values});
  }
}
