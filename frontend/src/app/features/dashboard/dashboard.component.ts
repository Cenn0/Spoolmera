import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, dateText, grams, stockPercent } from '../../models';

@Component({
  standalone: true,
  imports: [RouterLink],
  templateUrl:'../../dashboard.html'
})
export class DashboardComponent implements OnInit {
  private readonly http=inject(HttpClient);
  readonly costs=signal<{consumed_g:number;currency_groups:{currency:string;consumed_g:number;known_cost_cents:number;unpriced_g:number}[];estimated:boolean}|null>(null);
  async ngOnInit():Promise<void>{
    try{this.costs.set(await firstValueFrom(this.http.get<{consumed_g:number;currency_groups:{currency:string;consumed_g:number;known_cost_cents:number;unpriced_g:number}[];estimated:boolean}>("/api/analytics/material-usage")));}
    catch{this.costs.set(null);}
  }
  readonly data = inject(InventoryService);
  readonly dialogs = inject(DialogService);
  readonly auth = inject(AuthService);
  readonly grams = grams;
  readonly dateText = dateText;
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
