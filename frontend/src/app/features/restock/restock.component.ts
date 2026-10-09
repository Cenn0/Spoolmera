import { Component, HostListener, OnDestroy, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../auth.service';
import { DialogService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { ApiRestockItem } from '../../core/api/generated-contracts';
import { RequestOwner } from '../../core/request-owner';
import { grams } from '../../models';
@Component({standalone:true,imports:[FormsModule,RouterLink],templateUrl:'./restock.component.html'})
export class RestockComponent implements OnDestroy {
  readonly data=inject(InventoryService);readonly dialogs=inject(DialogService);readonly auth=inject(AuthService);
  readonly items=signal<ApiRestockItem[]>([]);readonly loading=signal(false);readonly error=signal('');
  readonly shortageOnly=signal(false);readonly grams=grams;private readonly requests=new RequestOwner();
  readonly filtered=computed(()=>this.items().filter(item=>!this.shortageOnly()||item.suggested_g>0));
  constructor(){effect(()=>{this.data.changed();untracked(()=>void this.refresh());});}
  ngOnDestroy():void{this.requests.invalidate();}
  @HostListener('window:focus') onFocus():void{void this.refresh();}
  async editTarget(item:ApiRestockItem):Promise<void>{
    if(!this.auth.canEdit())return;
    if(!this.data.products().some(product=>product.id===item.product_id))await this.data.load(['products']);
    if(this.data.products().some(product=>product.id===item.product_id))this.dialogs.open({kind:'product',id:item.product_id});
    else this.error.set('Unable to load this product for editing. Refresh the inventory and try again.');
  }
  async refresh():Promise<void>{
    const owner=this.requests.begin();this.loading.set(true);this.error.set('');
    try{const result=await this.data.restock();if(this.requests.owns(owner))this.items.set(result.items);}
    catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
}
