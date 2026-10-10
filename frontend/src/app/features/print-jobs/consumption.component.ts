import { Component, computed, ElementRef, OnDestroy, OnInit, effect, inject, input, output, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { PrintJob, WorkspaceService } from '../../workspace.service';
import { ConsumptionInput, ConsumptionSnapshot } from './consumption-contracts';
import { RequestOwner } from '../../core/request-owner';
import { I18nService, LocalizedMessage, TranslatePipe } from '../../core/i18n';

interface ActualRow {spool_id:number;actual_g:number|null;measured:boolean;gross_g:number|null;tare_g:number;}

@Component({selector:'sm-consumption',standalone:true,imports:[FormsModule,RouterLink,TranslatePipe],templateUrl:'./consumption.component.html'})
export class ConsumptionComponent implements OnInit, OnDestroy {
  readonly i18n=inject(I18nService);
  readonly job=input.required<PrintJob>();
  readonly closed=output<void>();readonly saved=output<void>();
  readonly api=inject(WorkspaceService);readonly auth=inject(AuthService);
  readonly data=inject(InventoryService);readonly notice=inject(NoticeService);
  readonly modal=viewChild<ElementRef<HTMLDialogElement>>('dialog');
  readonly snapshot=signal<ConsumptionSnapshot|null>(null);
  readonly loading=signal(false);readonly busy=signal(false);private readonly errorValue=signal<string|LocalizedMessage>('');readonly error=computed(()=>this.i18n.t(this.errorValue()));
  readonly conflict=signal(false);readonly grams=(value:number)=>this.i18n.grams(value);readonly dateText=(value:string|null|undefined)=>this.i18n.dateText(value);
  private readonly requests=new RequestOwner();
  private submitted:{fingerprint:string;requestId:string}|null=null;
  rows:ActualRow[]=[];mode:'actual'|'estimated'|'discard'='actual';reason='';confirmed=false;
  constructor(){effect(()=>{const element=this.modal()?.nativeElement;if(element&&!element.open)element.showModal();});}
  ngOnInit():void{void this.reload();}
  ngOnDestroy():void{this.requests.invalidate();}
  close(event?:Event):void{if(this.busy()){event?.preventDefault();return;}this.closed.emit();}
  changed():void{this.confirmed=false;}
  async reload():Promise<void>{
    if(this.busy())return;
    const owner=this.requests.begin();this.loading.set(true);this.errorValue.set('');
    try{
      const state=await this.api.consumption(this.job().id);
      if(!this.requests.owns(owner))return;
      this.snapshot.set(state);this.rows=state.materials.map(m=>({spool_id:m.spool_id,
        actual_g:null,measured:false,gross_g:null,tare_g:m.tare_g}));
      this.confirmed=false;this.conflict.set(false);this.submitted=null;
    }catch(error){if(this.requests.owns(owner))this.errorValue.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
  canSuggestPartial():boolean{
    const job=this.job();
    return job.status==='needs_review' && job.last_layer_num!==null && job.total_layer_num!==null
      && job.total_layer_num>0 && job.last_layer_num>0 && job.last_layer_num<job.total_layer_num;
  }
  suggestPartial():void{
    if(!this.canSuggestPartial()||!this.snapshot())return;
    const job=this.job(),fraction=job.last_layer_num!/job.total_layer_num!;
    this.mode='actual';
    this.rows=this.rows.map((row,index)=>({...row,
      actual_g:Math.round(this.snapshot()!.materials[index].estimated_g*fraction)}));
    this.reason=this.i18n.t('Proportional layer estimate (not weighed); verify against physical spools.');
    this.changed();
  }
  newTotal(index:number):number|null{
    const material=this.snapshot()?.materials[index];if(!material)return null;
    return this.mode==='actual'?this.rows[index]?.actual_g??null:this.mode==='estimated'?material.estimated_g:0;
  }
  measurementRequired(index:number):boolean{
    const material=this.snapshot()?.materials[index],total=this.newTotal(index);
    return !!material?.measurement_reconciliation_required&&total!==null&&total!==material.accounted_g;
  }
  expectedBalance(index:number):number|null{
    const row=this.rows[index],material=this.snapshot()?.materials[index],total=this.newTotal(index);
    if(!row||!material||total===null)return null;
    if(this.measurementRequired(index))return row.measured&&row.gross_g!==null?row.gross_g-row.tare_g:null;
    return material.remaining_g+material.accounted_g-total;
  }
  validation():string{
    const state=this.snapshot();if(!state)return 'Load the current job balances first.';
    if(!this.auth.canEdit())return 'Editing permission is required.';
    if(this.reason.trim().length<3)return 'Describe why you are recording or correcting consumption.';
    for(const [index,row] of this.rows.entries()){
      if(this.mode==='actual'&&(row.actual_g===null||!Number.isInteger(row.actual_g)||row.actual_g<0||row.actual_g>100000))
        return 'Enter actual grams for every physical spool, including zero when none was used.';
      const required=this.measurementRequired(index),material=state.materials[index];
      if(this.mode==='actual'&&row.actual_g!>material.initial_g)return 'Actual use cannot exceed the original filament weight of this physical spool.';
      if(required&&!row.measured)return 'This spool was weighed after its previous job booking. Include a current measurement to correct the job without counting that balance change twice.';
      if(row.measured){
        if(row.gross_g===null||!Number.isInteger(row.gross_g)||!Number.isInteger(row.tare_g)||row.tare_g<0||row.tare_g>100000||row.gross_g<row.tare_g||row.gross_g>200000)
          return 'Enter whole-number gross and tare weights for each measured spool.';
        const net=row.gross_g-row.tare_g;
        if(net<0||net>material.initial_g)return 'Measured net weight must be between zero and the original filament weight.';
        if(!required&&net!==material.remaining_g+material.accounted_g-this.newTotal(index)!)
          return 'The measured net weight must match the balance after the confirmed consumption.';
      }
      const balance=this.expectedBalance(index);
      if(balance===null||balance<0||balance>material.initial_g)return 'The resulting stock must be between zero and the original filament weight.';
    }
    return '';
  }
  async submit():Promise<void>{
    if(this.busy()||this.loading()||this.conflict())return;
    const state=this.snapshot(),invalid=this.validation();
    if(invalid||!state){this.errorValue.set(invalid);return;}
    if(!this.confirmed){this.errorValue.set('Confirm the displayed consumption and balance changes first.');return;}
    const body:ConsumptionInput={mode:this.mode,reason:this.reason.trim(),
      materials:this.mode==='actual'?this.rows.map(({spool_id,actual_g})=>({spool_id,actual_g:actual_g!})):[],
      expected_accounting_revision:state.accounting_revision,expected_updated_at:state.updated_at,
      measurements:this.rows.flatMap((row,index)=>row.measured?[{
        spool_id:row.spool_id,gross_g:row.gross_g!,tare_g:row.tare_g,
        expected_stock_revision:state.materials[index].stock_revision}]:[])};
    const fingerprint=JSON.stringify(body);
    if(this.submitted?.fingerprint!==fingerprint)this.submitted={fingerprint,requestId:crypto.randomUUID()};
    body.request_id=this.submitted!.requestId;
    this.busy.set(true);this.errorValue.set('');
    try{
      await this.api.reconcileConsumption(this.job().id,body);
      await this.data.load();this.notice.show('Consumption reconciliation saved. The estimate and previous entries remain in history.');
      this.saved.emit();
    }catch(error){
      const status=(error as {status?:number}).status;
      this.conflict.set(status===409);
      this.errorValue.set(status===409
        ? this.i18n.message('{error} Reload the latest balances and review your values before confirming again.', {error:this.i18n.message(apiError(error))})
        : apiError(error));
    }finally{this.busy.set(false);}
  }
}
