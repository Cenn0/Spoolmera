import { I18nService, TranslatePipe } from '../../core/i18n';
import { Component, OnDestroy, computed, inject, signal, effect, untracked } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { RequestOwner } from '../../core/request-owner';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, stockPercent } from '../../models';

@Component({
  standalone: true,
  imports:[TranslatePipe,RouterLink],
  templateUrl:'./dashboard.component.html',
  styleUrl:'./dashboard.component.css'
})
export class DashboardComponent implements OnDestroy {
  readonly i18n=inject(I18nService);
  private readonly http=inject(HttpClient);
  readonly costs=signal<{consumed_g:number;currency_groups:{currency:string;consumed_g:number;known_cost_cents:number;unpriced_g:number}[];estimated:boolean}|null>(null);
  readonly costError=signal('');readonly costsLoading=signal(false);private readonly requests=new RequestOwner();
  constructor(){effect(()=>{this.data.lastUpdated();untracked(()=>void this.refreshCosts());});}
  ngOnDestroy():void{this.requests.invalidate();}
  async refreshCosts():Promise<void>{
    const owner=this.requests.begin();this.costsLoading.set(true);this.costError.set('');
    try{const result=await firstValueFrom(this.http.get<NonNullable<ReturnType<typeof this.costs>>>('/api/analytics/material-usage'));
      if(this.requests.owns(owner))this.costs.set(result);
    }catch(error){if(this.requests.owns(owner))this.costError.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.costsLoading.set(false);}
  }
  readonly data = inject(InventoryService);
  readonly dialogs = inject(DialogService);
  readonly auth = inject(AuthService);
  readonly grams=(value:number)=>this.i18n.grams(value);
  readonly dateText=(value:string|null|undefined)=>this.i18n.dateText(value);
  readonly percent = stockPercent;
  readonly low = this.data.lowStock;
  readonly materialStock = computed(() => {
    const weights = new Map<string, number>();
    for (const spool of this.data.available()) {
      weights.set(spool.material, (weights.get(spool.material) || 0) + spool.remaining_g);
    }
    const total = Array.from(weights.values()).reduce((a,b)=>a+b,0);
    return Array.from(weights.entries()).sort((a,b)=>b[1]-a[1]).slice(0,5)
      .map(([name,weight])=>({name,weight,percentage:total ? Math.round(100*weight/total) : 0}));
  });
  readonly recent = computed(() => this.data.movements().slice(0,5));
}
