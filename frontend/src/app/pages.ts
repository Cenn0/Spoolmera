import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { AuthService } from './auth.service';
import { CloudReceipt, Printer, WorkspaceService } from './workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from './dialog.service';
import { InventoryService, apiError } from './inventory.service';
import { Capabilities, dateText, grams, stockPercent } from './models';

@Component({
  standalone: true,
  imports: [RouterLink],
  templateUrl: './dashboard.html'
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
@Component({
  standalone: true,
  templateUrl: './spools.html'
})
export class SpoolsComponent {
  readonly data = inject(InventoryService);
  readonly dialogs = inject(DialogService);
  readonly auth = inject(AuthService);
  readonly grams = grams;
  readonly percent = stockPercent;
  readonly query = signal('');
  readonly material = signal('');
  readonly status = signal('');
  readonly materials = computed(() => Array.from(new Set(this.data.spools().map(item=>item.material))).sort());
  readonly filtered = computed(() => {
    const query=this.query().trim().toLocaleLowerCase('en-US'), material=this.material(), status=this.status();
    return this.data.spools().filter(s =>
      (!material || s.material===material) && (!status || s.status===status) &&
      (!query || [s.brand,s.product_name,s.material,s.color_name,s.location,s.notes].join(' ').toLocaleLowerCase('en-US').includes(query)));
  });
}
@Component({
  standalone: true,
  templateUrl: './products.html'
})
export class ProductsComponent {
  readonly data = inject(InventoryService);
  readonly dialogs = inject(DialogService);
  readonly auth = inject(AuthService);
  readonly grams = grams;
  readonly query = signal('');
  readonly filtered = computed(() => {
    const query=this.query().trim().toLocaleLowerCase('en-US');
    return this.data.products().filter(p=>[p.brand,p.name,p.material,p.color_name]
      .join(' ').toLocaleLowerCase('en-US').includes(query));
  });
}
@Component({
  standalone: true,
  templateUrl: './history.html'
})
export class HistoryComponent {
  readonly data = inject(InventoryService);
  readonly dateText = dateText;
  readonly grams = grams;
  readonly kind = signal('');
  readonly filtered = computed(() => this.data.movements().filter(m => !this.kind() || m.kind === this.kind()));
}
@Component({
  standalone: true,
  templateUrl: './integrations.html'
})
export class IntegrationsComponent implements OnInit {
  private readonly data = inject(InventoryService);
  private readonly notices = inject(NoticeService);
  private readonly workspace = inject(WorkspaceService);
  readonly printers = signal<Printer[]>([]);
  readonly auth = inject(AuthService);
  readonly cloudEvents = signal<CloudReceipt[]>([]);
  readonly enabledPrinters = computed(() => this.printers().filter(printer => printer.enabled).length);
  readonly capabilities = signal<Capabilities | null>(null);
  async ngOnInit(): Promise<void> {
    try {
      const [capabilities, printers] = await Promise.all([
        this.data.capabilities(), this.workspace.printers(),
      ]);
      this.capabilities.set(capabilities);
      this.printers.set(printers);
      if(this.auth.isAdmin())this.cloudEvents.set(await this.workspace.cloudEvents());
    }
    catch (error) { this.notices.show('Unable to load integration capabilities: ' + apiError(error),true); }
  }
}
