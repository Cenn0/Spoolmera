import { I18nService, TranslatePipe } from '../../core/i18n';
import { Component, DestroyRef, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { InventoryService, MovementFilters, apiError } from '../../inventory.service';
import { Movement } from '../../models';
import { RequestOwner } from '../../core/request-owner';

@Component({standalone:true,imports:[TranslatePipe,FormsModule,RouterLink],templateUrl:'./history.component.html',styleUrl:'./history.component.css'})
export class HistoryComponent implements OnInit, OnDestroy {
  readonly i18n=inject(I18nService);
  readonly data=inject(InventoryService);readonly route=inject(ActivatedRoute);private readonly destroy=inject(DestroyRef);
  readonly dateText=(value:string|null|undefined)=>this.i18n.dateText(value);readonly grams=(value:number)=>this.i18n.grams(value);readonly items=signal<Movement[]>([]);
  readonly loading=signal(false);readonly error=signal('');readonly nextCursor=signal<number|null>(null);
  readonly kind=signal('');query='';private readonly requests=new RequestOwner();
  spoolId:number|null=null;jobId:number|null=null;actorId:number|null=null;source='';fromDate='';toDate='';
  private filters:MovementFilters={};
  ngOnInit():void{this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroy)).subscribe(params=>{
    this.spoolId=this.positive(params.get('spool'));this.jobId=this.positive(params.get('job'));this.actorId=this.positive(params.get('actor'));this.source=params.get('source')||'';void this.apply();
  });}
  ngOnDestroy():void{this.requests.invalidate();}
  private positive(value:string|null):number|null{const num=Number(value);return Number.isInteger(num)&&num>0?num:null;}
  sourceLabel(source:string):string{return ({manual:'Manual entry',registration:'Registration',print_job:'Print job',job:'Print job',job_correction:'Job correction',scale:'Scale measurement',weighing:'Scale measurement',csv_import:'CSV import',spoolman_import:'Spoolman import',measurement_reconciliation:'Measurement reconciliation',import:'Inventory import'} as Record<string,string>)[source]||source.replaceAll('_',' ');}
  async apply():Promise<void>{
    if(this.fromDate&&this.toDate&&this.fromDate>this.toDate){this.error.set('The start date must be on or before the end date.');return;}
    this.filters={kind:this.kind(),q:this.query.trim(),spool_id:this.spoolId||undefined,job_id:this.jobId||undefined,actor_id:this.actorId||undefined,
      source:this.source.trim(),from_date:this.fromDate||undefined,to_date:this.toDate||undefined};
    await this.load();
  }
  exportUrl():string{
    // Export the last applied server filters, not unsubmitted form edits.
    const params=new URLSearchParams();
    for(const [key,value] of Object.entries(this.filters)){
      if(value!==undefined&&value!==null&&value!=='')params.set(key,String(value));
    }
    const query=params.toString();
    return '/api/movements/export.csv'+(query?'?'+query:'');
  }
  reset():void{this.kind.set('');this.query='';this.spoolId=null;this.jobId=null;this.actorId=null;this.source='';this.fromDate='';this.toDate='';void this.apply();}
  async load(more=false):Promise<void>{
    if(more&&(this.loading()||!this.nextCursor()))return;
    const owner=this.requests.begin();this.loading.set(true);this.error.set('');
    if(!more){this.items.set([]);this.nextCursor.set(null);}
    try{const page=await this.data.movementPage({...this.filters},more?this.nextCursor()!:undefined);
      if(!this.requests.owns(owner))return;
      this.items.update(old=>more?[...old,...page.items.filter(item=>!old.some(m=>m.id===item.id))]:page.items);this.nextCursor.set(page.next_cursor);
    }catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
}
