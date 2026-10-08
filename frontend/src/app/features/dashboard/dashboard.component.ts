import { Component, OnInit, computed, inject, signal } from '@angular/core';
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
export class DashboardComponent {
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
