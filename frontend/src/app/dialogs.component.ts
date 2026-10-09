import { FileDropComponent } from './core/ui/file-drop.component';
import { I18nService, LocalizedMessage, TranslatePipe } from './core/i18n';
import { Component, OnDestroy, ElementRef, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { RequestOwner } from './core/request-owner';
import { DialogRequest, DialogService, NoticeService } from './dialog.service';
import { AuthService } from './auth.service';
import { InventoryService, apiError } from './inventory.service';
import { CsvPreview, Movement, ProductInput, SpoolInput, stockPercent } from './models';

function blankProduct(): ProductInput {
  return {brand:'',name:'',material:'PLA',color_name:'',color_hex:'#64748b',diameter_mm:1.75,notes:'',density_g_cm3:null,nozzle_min_c:null,nozzle_max_c:null,
    bed_min_c:null,bed_max_c:null,gtin:'',manufacturer_sku:'',slicer_preset:'',low_stock_threshold_g:200,target_stock_g:0};
}
function blankSpool(): SpoolInput {
  return {product_id:0,initial_g:1000,remaining_g:null,opened:false,location:'',notes:'',tare_g:0,purchase_price_cents:null,
    purchase_currency:'EUR',purchased_on:null,batch:''};
}

@Component({
  selector:'fm-dialogs',
  standalone:true,
  imports:[TranslatePipe,FormsModule,RouterLink,FileDropComponent],
  templateUrl:'./dialogs.component.html',
})
export class DialogsComponent implements OnDestroy {
  readonly i18n=inject(I18nService);
  readonly dialogs=inject(DialogService);
  readonly auth=inject(AuthService);
  readonly data=inject(InventoryService);
  readonly notices=inject(NoticeService);
  readonly grams=(value:number)=>this.i18n.grams(value);
  readonly money=(cents:number|null|undefined,currency:string)=>this.i18n.money(cents,currency);
  readonly detailsLoading=signal(false);
  readonly weighingConflict=signal(false);
  private readonly requests=new RequestOwner();
  private activeRevision=0;
  readonly dateText=(value:string|null|undefined)=>this.i18n.dateText(value);
  readonly percent=stockPercent;
  readonly modal=viewChild<ElementRef<HTMLDialogElement>>('dialog');
  readonly busy=signal(false);
  readonly error=signal<string|LocalizedMessage>('');
  readonly history=signal<Movement[]>([]);
  readonly tags=signal<{namespace:string;external_id:string;created_at:string}[]>([]);
  tagNamespace='nfc';tagValue='';
  readonly dryingHistory=signal<{id:number;temperature_c:number;duration_minutes:number;dried_at:string;note:string}[]>([]);
  readonly archiveCheck=signal(false);
  readonly importCheck=signal(false);
  readonly csvPreview=signal<CsvPreview|null>(null);
  readonly readingCsv=signal(false);
  product=blankProduct();
  spool=blankSpool();
  detail={location:'',notes:'',opened:false,batch:'',purchase_price_cents:null as number|null,purchase_currency:'EUR',purchased_on:null as string|null};
  movement={kind:'consume' as 'consume'|'adjust',grams:0,note:''};
  csvFile:File|null=null;
  weighing={gross_g:0,tare_g:0,note:this.i18n.t('Physical scale measurement'),stock_revision:0,remaining_g:0};
  drying={temperature_c:50,duration_minutes:240,note:'',dried_at:this.localNow()};

  constructor() {
    effect(() => {
      const active=this.dialogs.active();
      this.activeRevision=this.requests.begin();
      if (!active) return;
      untracked(()=>{
      this.error.set('');this.weighingConflict.set(false);this.detailsLoading.set(false);
      this.busy.set(false);
      this.history.set([]);
      this.dryingHistory.set([]);
      this.tags.set([]);this.tagValue='';this.tagNamespace='nfc';
      this.archiveCheck.set(false);
      this.importCheck.set(false);
      this.csvPreview.set(null);this.readingCsv.set(false);
      this.csvFile=null;
      if (active.kind==='product') {
        const p=this.data.products().find(x=>x.id===active.id);
        this.product=active.catalog ? {...blankProduct(),...active.catalog} : p ? {
          brand:p.brand,name:p.name,material:p.material,color_name:p.color_name,
          color_hex:p.color_hex,diameter_mm:p.diameter_mm,notes:p.notes,
          density_g_cm3:p.density_g_cm3,nozzle_min_c:p.nozzle_min_c,
          nozzle_max_c:p.nozzle_max_c,bed_min_c:p.bed_min_c,bed_max_c:p.bed_max_c,
          gtin:p.gtin,manufacturer_sku:p.manufacturer_sku,slicer_preset:p.slicer_preset,
          low_stock_threshold_g:p.low_stock_threshold_g,target_stock_g:p.target_stock_g
        } : blankProduct();
      }
      if (active.kind==='spool') {
        this.spool=blankSpool();
        this.spool.product_id=active.productId || this.data.products()[0]?.id || 0;
      }
      if (active.kind==='details') {
        const s=this.selected;
        if (s) {
          this.detail={location:s.location || '',notes:s.notes || '',opened:s.opened,batch:s.batch,
            purchase_price_cents:s.purchase_price_cents,purchase_currency:s.purchase_currency,purchased_on:s.purchased_on};
          this.detailsLoading.set(true);
          const owner=this.activeRevision;
          void Promise.all([this.loadHistory(s.id),this.loadDrying(s.id),this.loadTags(s.id)])
            .finally(()=>{if(this.requests.owns(owner))this.detailsLoading.set(false);});
        }
      }
      if (active.kind==='weigh') {
        const s=this.selected;
        if(s) this.weighing={gross_g:s.remaining_g+s.tare_g,tare_g:s.tare_g,
          note:this.i18n.t('Physical scale measurement'),stock_revision:s.stock_revision,remaining_g:s.remaining_g};
      }
      if (active.kind==='drying') {
        this.drying={temperature_c:50,duration_minutes:240,note:'',dried_at:this.localNow()};
      }
      if (active.kind==='movement') {
        this.movement={kind:active.mode || 'consume',grams:0,note:''};
      }
      });
    });
    effect(() => {
      const element=this.modal()?.nativeElement;
      if (element && this.dialogs.active() && !element.open) element.showModal();
    });
  }

  ngOnDestroy():void{this.requests.invalidate();this.csvFile=null;}

  get selected() {
    const active=this.dialogs.active();
    return active?.id ? this.data.spools().find(s=>s.id===active.id) || active.spool : undefined;
  }
  get heading(): string {
    const active=this.dialogs.active();
    if (!active) return '';
    switch(active.kind) {
      case 'product': return active.id ? 'Edit filament' : 'Add filament';
      case 'spool': return 'Register a spool';
      case 'details': return 'Spool details';
      case 'movement': return active.mode==='adjust' ? 'Adjust stock' : 'Record consumption';
      case 'csv': return 'Import inventory';
      case 'weigh': return 'Weigh spool';
      case 'drying': return 'Record drying';
    }
  }

  onCancel(event: Event): void {
    if (this.busy()) event.preventDefault();
    else this.close();
  }
  close(): void { if (!this.busy()) this.dialogs.close(); }
  private localNow():string{const now=new Date();return new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,16);}
  private async loadHistory(id:number):Promise<void> {
    const owner=this.activeRevision;
    try {const entries=await this.data.movementsFor(id);if(this.requests.owns(owner))this.history.set(entries);}
    catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
  }
  private async loadTags(id:number):Promise<void> {
    const owner=this.activeRevision;
    try{const entries=await this.data.identifiers(id);if(this.requests.owns(owner))this.tags.set(entries);}
    catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
  }
  async addTag():Promise<void> {
    const s=this.selected;if(!s||s.archived_at||!this.auth.canEdit()||this.busy())return;
    if(!/^[A-Za-z0-9:_-]{8,128}$/.test(this.tagValue.trim())){
      this.error.set('Tag ID must contain 8–128 letters, digits, underscores, dashes or colons.');return;
    }
    const owner=this.activeRevision;this.busy.set(true);this.error.set('');
    try{
      await this.data.registerIdentifier(s.id,this.tagNamespace,this.tagValue.trim());
      if(!this.requests.owns(owner))return;
      this.tagValue='';await this.loadTags(s.id);
      this.notices.show('Tag linked to this physical spool.');
    }catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.busy.set(false);}
  }
  async unlinkTag(namespace:string,value:string):Promise<void>{
    const s=this.selected;if(!s||s.archived_at||!this.auth.canEdit()||this.busy())return;
    const owner=this.activeRevision;this.busy.set(true);this.error.set('');
    try{
      await this.data.deleteIdentifier(s.id,namespace,value);
      if(!this.requests.owns(owner))return;
      await this.loadTags(s.id);
      this.notices.show('Tag mapping removed.');
    }catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.busy.set(false);}
  }
  private async loadDrying(id:number):Promise<void> {
    const owner=this.activeRevision;
    try {const entries=await this.data.dryingRecords(id);if(this.requests.owns(owner))this.dryingHistory.set(entries);}
    catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
  }
  private async run(operation:()=>Promise<void>,success:string, next?:DialogRequest):Promise<void> {
    if(this.busy()||!this.auth.canEdit())return;
    const owner=this.activeRevision;this.busy.set(true);this.error.set('');
    try {
      await operation();
      if(!this.requests.owns(owner))return;
      this.dialogs.close();this.notices.show(success);
      if(next)this.dialogs.open(next);
    } catch(error) {
      if(this.requests.owns(owner)){
        this.error.set(apiError(error));
        if(this.dialogs.active()?.kind==='weigh'&&(error as {status?:number}).status===409)this.weighingConflict.set(true);
      }
    } finally {if(this.requests.owns(owner))this.busy.set(false);}
  }

  async saveProduct():Promise<void>{
    const active=this.dialogs.active();
    if(!active)return;
    const payload={...this.product,material:this.product.material.trim().toUpperCase()};
    await this.run(
      ()=>active.id ? this.data.updateProduct(active.id,payload) : this.data.createProduct(payload),
      active.id?'Filament updated.':'Filament added. You can now register a physical spool.'
    );
  }
  async saveSpool():Promise<void>{
    if(!this.spool.product_id){this.error.set('Choose a filament product first.');return;}
    if(this.spool.remaining_g!==null && this.spool.remaining_g>this.spool.initial_g){
      this.error.set('Remaining weight cannot exceed original weight.');return;
    }
    await this.run(()=>this.data.createSpool({...this.spool,purchased_on:this.spool.purchased_on||null}), 'Physical spool registered.');
  }
  async saveDetails():Promise<void>{
    const current=this.selected;
    if(!current||current.archived_at)return;
    await this.run(()=>this.data.updateSpool(current.id,{...this.detail,purchased_on:this.detail.purchased_on||null,purchase_price_cents:this.detail.purchase_price_cents??null}), 'Spool details updated.');
  }
  async saveMovement():Promise<void>{
    const current=this.selected;
    if(!current||current.archived_at)return;
    const {kind,grams,note}=this.movement;
    if(!Number.isInteger(grams)||grams===0||(kind==='consume'&&grams<0)) {
      this.error.set('Enter a valid, non-zero number of grams.');return;
    }
    if(kind==='adjust'&&!note.trim()){this.error.set('A reason is required for stock adjustments.');return;}
    const change=kind==='consume'?-grams:grams;
    if(current.remaining_g+change<0||current.remaining_g+change>current.initial_g){
      this.error.set('The movement would exceed the allowed stock range.');return;
    }
    await this.run(()=>this.data.move(current.id,kind,grams,note),kind==='consume'?'Consumption recorded.':'Stock adjustment recorded.');
  }
  async saveWeighing():Promise<void>{
    const s=this.selected;if(!s||s.archived_at)return;
    if(!Number.isInteger(this.weighing.gross_g) || !Number.isInteger(this.weighing.tare_g)
       || this.weighing.gross_g<this.weighing.tare_g ||
       this.weighing.gross_g-this.weighing.tare_g>s.initial_g){
      this.error.set('Gross and empty-spool weights must result in 0 to original filament grams.');return;
    }
    await this.run(()=>this.data.weigh(s.id,this.weighing.gross_g,
      this.weighing.tare_g,this.weighing.note,this.weighing.stock_revision),'Scale measurement recorded.');
  }
  async saveDrying():Promise<void>{
    const s=this.selected;if(!s||s.archived_at)return;
    if(!Number.isInteger(this.drying.temperature_c)||!Number.isInteger(this.drying.duration_minutes)||!this.drying.dried_at||!Number.isFinite(new Date(this.drying.dried_at).getTime())){
      this.error.set('Enter whole-number temperature and duration.');return;
    }
    await this.run(()=>this.data.dry(s.id,this.drying.temperature_c,
      this.drying.duration_minutes,this.drying.note,new Date(this.drying.dried_at).toISOString()),'Drying recorded.');
  }
  async unarchive():Promise<void>{
    const current=this.selected;if(!current)return;
    await this.run(()=>this.data.unarchive(current.id),'Spool restored to active inventory.');
  }
  async reloadWeighing():Promise<void>{
    const spool=this.selected;if(!spool||this.busy())return;
    await this.data.load();
    this.dialogs.open({kind:'weigh',id:spool.id});
  }
  async archive():Promise<void>{
    const current=this.selected;
    if(!current||!this.archiveCheck())return;
    await this.run(()=>this.data.archive(current.id),'Spool archived. Its movement history is preserved.');
  }
  async pickCsv(event:Event):Promise<void>{
    const input=event.target as HTMLInputElement;
    const file=input.files?.[0] || null;
    input.value='';
    await this.selectCsv(file);
  }
  rejectCsv(message:string):void{void this.selectCsv(null);this.error.set(message);}
  async selectCsv(file:File|null):Promise<void>{
    if(this.busy())return;
    this.csvFile=file;
    this.csvPreview.set(null);this.readingCsv.set(false);
    this.importCheck.set(false);
    this.error.set('');
    if(!file)return;
    if(file.size>2*1024*1024){this.error.set('CSV exceeds the 2 MiB import limit.');return;}
    this.readingCsv.set(true);
    const owner=this.activeRevision;
    try {
      const preview=await this.data.previewCsv(file);
      if(this.requests.owns(owner)&&this.csvFile===file) this.csvPreview.set(preview);
    } catch(error) {
      if(this.requests.owns(owner)&&this.csvFile===file)this.error.set(this.i18n.message('CSV validation failed: {error}',{error:this.i18n.message(apiError(error))}));
    } finally {
      if(this.requests.owns(owner)&&this.csvFile===file)this.readingCsv.set(false);
    }
  }
  async importCsv():Promise<void>{
    if(!this.csvFile||!this.csvPreview()||!this.importCheck())return;
    const file=this.csvFile,owner=this.activeRevision;
    if(this.busy())return;
    this.busy.set(true);
    this.error.set('');
    try {
      const result=await this.data.importCsv(file);
      if(!this.requests.owns(owner))return;
      this.dialogs.close();
      this.notices.show(this.i18n.message('Imported {products} products and {spools} spools. Skipped {skippedProducts} existing products and {skippedSpools} existing spools.',{products:result.products_created,spools:result.spools_created,skippedProducts:result.products_skipped,skippedSpools:result.spools_skipped}));
    } catch(error) {
      if(this.requests.owns(owner))this.error.set(this.i18n.message('Import failed: {error}',{error:this.i18n.message(apiError(error))}));
    } finally {
      if(this.requests.owns(owner))this.busy.set(false);
    }
  }
}
