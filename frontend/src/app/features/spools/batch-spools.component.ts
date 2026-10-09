import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { ApiSpoolBatch } from '../../core/api/generated-contracts';
import { SpoolInput, grams, money } from '../../models';

@Component({standalone:true,imports:[FormsModule,RouterLink],templateUrl:'./batch-spools.component.html'})
export class BatchSpoolsComponent {
  readonly data=inject(InventoryService);readonly auth=inject(AuthService);readonly notice=inject(NoticeService);
  readonly busy=signal(false);readonly error=signal('');readonly result=signal<ApiSpoolBatch|null>(null);
  readonly preview=signal<{count:number;spool:SpoolInput;product:string;requestId:string}|null>(null);readonly uncertain=signal(false);
  readonly grams=grams;readonly money=money;
  count=2;confirmed=false;labelSize='60x40';
  spool:SpoolInput={product_id:0,initial_g:1000,remaining_g:null,opened:false,location:'',notes:'',tare_g:0,
    purchase_price_cents:null,purchase_currency:'EUR',purchased_on:null,batch:''};
  changed():void{this.preview.set(null);this.confirmed=false;this.error.set('');}
  prepare():void{
    if(this.busy()||this.uncertain())return;
    const product=this.data.products().find(p=>p.id===this.spool.product_id);
    if(!product||!Number.isInteger(this.count)||this.count<1||this.count>100){this.error.set('Choose a product and a batch size from 1 to 100.');return;}
    if(!Number.isInteger(this.spool.initial_g)||this.spool.initial_g<1||this.spool.initial_g>100000||
      (this.spool.remaining_g!==null&&(!Number.isInteger(this.spool.remaining_g)||this.spool.remaining_g<0||this.spool.remaining_g>this.spool.initial_g))){
      this.error.set('Check the original and remaining weight for each spool.');return;
    }
    this.preview.set({requestId:crypto.randomUUID(),count:this.count,spool:{...this.spool,purchased_on:this.spool.purchased_on||null},
      product:product.brand+' · '+product.name+' · '+product.color_name});this.confirmed=false;this.error.set('');
  }
  get labelUrl():string{
    const result=this.result();if(!result)return '';
    return '/labels?uids='+result.items.map(spool=>spool.uid).join(',')+'&size='+this.labelSize;
  }
  acknowledgeCheck():void{
    if(window.confirm('Have you checked the inventory and verified whether the previous batch was created?')){
      this.uncertain.set(false);this.changed();
    }
  }
  async create():Promise<void>{
    const preview=this.preview();
    if(!this.auth.canEdit()||!preview||!this.confirmed||this.busy())return;
    const current=JSON.stringify({count:this.count,spool:{...this.spool,purchased_on:this.spool.purchased_on||null}});
    if(current!==JSON.stringify({count:preview.count,spool:preview.spool})){
      this.changed();this.error.set('Batch details changed. Preview them again.');return;
    }
    this.busy.set(true);this.error.set('');
    try{
      this.result.set(await this.data.createBatch(preview.count,preview.spool,preview.requestId));this.uncertain.set(false);this.preview.set(null);this.confirmed=false;
      this.notice.show('Registered '+preview.count+' physical spools with individual labels.');
    }catch(error){
      const status=(error as {status?:number}).status;
      if(!status||status>=500)this.uncertain.set(true);
      this.error.set(apiError(error)+(this.uncertain()?' The response is uncertain. Retry this confirmed batch to retrieve the same result, or check the inventory before preparing another batch.':''));
    }finally{this.busy.set(false);}
  }
}
