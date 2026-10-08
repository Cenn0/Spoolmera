import { Component, ElementRef, effect, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DialogRequest, DialogService, NoticeService } from './dialog.service';
import { AuthService } from './auth.service';
import { InventoryService, apiError } from './inventory.service';
import { CsvPreview, Movement, ProductInput, SpoolInput, dateText, grams, stockPercent } from './models';

function blankProduct(): ProductInput {
  return {brand:'',name:'',material:'PLA',color_name:'',color_hex:'#64748b',diameter_mm:1.75,notes:'',density_g_cm3:null,nozzle_min_c:null,nozzle_max_c:null,
    bed_min_c:null,bed_max_c:null,gtin:'',manufacturer_sku:'',slicer_preset:'',low_stock_threshold_g:200};
}
function blankSpool(): SpoolInput {
  return {product_id:0,initial_g:1000,remaining_g:null,opened:false,location:'',notes:'',tare_g:0,purchase_price_cents:null,
    purchase_currency:'EUR',purchased_on:null,batch:''};
}

@Component({
  selector:'fm-dialogs',
  standalone:true,
  imports:[FormsModule],
  templateUrl:'./dialogs.component.html',
})
export class DialogsComponent {
  readonly dialogs=inject(DialogService);
  readonly auth=inject(AuthService);
  readonly data=inject(InventoryService);
  readonly notices=inject(NoticeService);
  readonly grams=grams;
  readonly dateText=dateText;
  readonly percent=stockPercent;
  readonly modal=viewChild<ElementRef<HTMLDialogElement>>('dialog');
  readonly busy=signal(false);
  readonly error=signal('');
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
  detail={location:'',notes:'',opened:false};
  movement={kind:'consume' as 'consume'|'adjust',grams:0,note:''};
  csvFile:File|null=null;
  weighing={gross_g:0,tare_g:0,note:'Physical scale measurement'};
  drying={temperature_c:50,duration_minutes:240,note:''};

  constructor() {
    effect(() => {
      const active=this.dialogs.active();
      if (!active) return;
      this.error.set('');
      this.busy.set(false);
      this.history.set([]);
      this.dryingHistory.set([]);
      this.tags.set([]);this.tagValue='';this.tagNamespace='nfc';
      this.archiveCheck.set(false);
      this.importCheck.set(false);
      this.csvPreview.set(null);
      this.csvFile=null;
      if (active.kind==='product') {
        const p=this.data.products().find(x=>x.id===active.id);
        this.product=active.catalog ? {...blankProduct(),...active.catalog} : p ? {
          brand:p.brand,name:p.name,material:p.material,color_name:p.color_name,
          color_hex:p.color_hex,diameter_mm:p.diameter_mm,notes:p.notes,
          density_g_cm3:p.density_g_cm3,nozzle_min_c:p.nozzle_min_c,
          nozzle_max_c:p.nozzle_max_c,bed_min_c:p.bed_min_c,bed_max_c:p.bed_max_c,
          gtin:p.gtin,manufacturer_sku:p.manufacturer_sku,slicer_preset:p.slicer_preset,
          low_stock_threshold_g:p.low_stock_threshold_g
        } : blankProduct();
      }
      if (active.kind==='spool') {
        this.spool=blankSpool();
        this.spool.product_id=active.productId || this.data.products()[0]?.id || 0;
      }
      if (active.kind==='details') {
        const s=this.data.spools().find(x=>x.id===active.id);
        if (s) {
          this.detail={location:s.location || '',notes:s.notes || '',opened:s.opened};
          void this.loadHistory(s.id);
          void this.loadDrying(s.id);
          void this.loadTags(s.id);
        }
      }
      if (active.kind==='weigh') {
        const s=this.data.spools().find(x=>x.id===active.id);
        if(s) this.weighing={gross_g:s.remaining_g+s.tare_g,tare_g:s.tare_g,
          note:'Physical scale measurement'};
      }
      if (active.kind==='drying') {
        this.drying={temperature_c:50,duration_minutes:240,note:''};
      }
      if (active.kind==='movement') {
        this.movement={kind:active.mode || 'consume',grams:0,note:''};
      }
    });
    effect(() => {
      const element=this.modal()?.nativeElement;
      if (element && this.dialogs.active() && !element.open) element.showModal();
    });
  }

  get selected() {
    const active=this.dialogs.active();
    return active?.id ? this.data.spools().find(s=>s.id===active.id) : undefined;
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
  private async loadHistory(id:number):Promise<void> {
    try { this.history.set(await this.data.movementsFor(id)); }
    catch(error){ this.error.set(apiError(error)); }
  }
  private async loadTags(id:number):Promise<void> {
    try{this.tags.set(await this.data.identifiers(id));}
    catch(error){this.error.set(apiError(error));}
  }
  async addTag():Promise<void> {
    const s=this.selected;if(!s||this.busy())return;
    if(!/^[A-Za-z0-9:_-]{8,128}$/.test(this.tagValue.trim())){
      this.error.set('Tag ID must contain 8–128 letters, digits, underscores, dashes or colons.');return;
    }
    this.busy.set(true);this.error.set('');
    try{
      await this.data.registerIdentifier(s.id,this.tagNamespace,this.tagValue.trim());
      this.tagValue='';await this.loadTags(s.id);
      this.notices.show('Tag linked to this physical spool.');
    }catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
  async unlinkTag(namespace:string,value:string):Promise<void>{
    const s=this.selected;if(!s||this.busy())return;
    this.busy.set(true);this.error.set('');
    try{
      await this.data.deleteIdentifier(s.id,namespace,value);
      await this.loadTags(s.id);
      this.notices.show('Tag mapping removed.');
    }catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
  private async loadDrying(id:number):Promise<void> {
    try {this.dryingHistory.set(await this.data.dryingRecords(id));}
    catch(error){this.error.set(apiError(error));}
  }
  private async run(operation:()=>Promise<void>,success:string, next?:DialogRequest):Promise<void> {
    if(this.busy())return;
    this.busy.set(true);
    this.error.set('');
    try {
      await operation();
      this.dialogs.close();
      this.notices.show(success);
      if(next) this.dialogs.open(next);
    } catch(error) {
      this.error.set(apiError(error));
    } finally {
      this.busy.set(false);
    }
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
    await this.run(()=>this.data.createSpool({...this.spool}), 'Physical spool registered.');
  }
  async saveDetails():Promise<void>{
    const current=this.selected;
    if(!current)return;
    await this.run(()=>this.data.updateSpool(current.id,{...this.detail}), 'Spool details updated.');
  }
  async saveMovement():Promise<void>{
    const current=this.selected;
    if(!current)return;
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
    const s=this.selected;if(!s)return;
    if(!Number.isInteger(this.weighing.gross_g) || !Number.isInteger(this.weighing.tare_g)
       || this.weighing.gross_g<this.weighing.tare_g ||
       this.weighing.gross_g-this.weighing.tare_g>s.initial_g){
      this.error.set('Gross and empty-spool weights must result in 0 to original filament grams.');return;
    }
    await this.run(()=>this.data.weigh(s.id,this.weighing.gross_g,
      this.weighing.tare_g,this.weighing.note),'Scale measurement recorded.');
  }
  async saveDrying():Promise<void>{
    const s=this.selected;if(!s)return;
    if(!Number.isInteger(this.drying.temperature_c)||!Number.isInteger(this.drying.duration_minutes)){
      this.error.set('Enter whole-number temperature and duration.');return;
    }
    await this.run(()=>this.data.dry(s.id,this.drying.temperature_c,
      this.drying.duration_minutes,this.drying.note),'Drying recorded.');
  }
  async archive():Promise<void>{
    const current=this.selected;
    if(!current||!this.archiveCheck())return;
    await this.run(()=>this.data.archive(current.id),'Spool archived. Its movement history is preserved.');
  }
  async pickCsv(event:Event):Promise<void>{
    const input=event.target as HTMLInputElement;
    const file=input.files?.[0] || null;
    this.csvFile=file;
    this.csvPreview.set(null);
    this.importCheck.set(false);
    this.error.set('');
    if(!file)return;
    if(file.size>2*1024*1024){this.error.set('CSV exceeds the 2 MiB import limit.');return;}
    this.readingCsv.set(true);
    try {
      const preview=await this.data.previewCsv(file);
      if(this.csvFile===file) this.csvPreview.set(preview);
    } catch(error) {
      if(this.csvFile===file)this.error.set('CSV validation failed: '+apiError(error));
    } finally {
      if(this.csvFile===file)this.readingCsv.set(false);
    }
  }
  async importCsv():Promise<void>{
    if(!this.csvFile||!this.csvPreview()||!this.importCheck())return;
    const file=this.csvFile;
    if(this.busy())return;
    this.busy.set(true);
    this.error.set('');
    try {
      const result=await this.data.importCsv(file);
      this.dialogs.close();
      this.notices.show('Imported '+result.products_created+' products and '+result.spools_created+' spools. Existing UUIDs were skipped.');
    } catch(error) {
      this.error.set('Import failed: '+apiError(error));
    } finally {
      this.busy.set(false);
    }
  }
}
