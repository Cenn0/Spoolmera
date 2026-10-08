import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, dateText, grams, stockPercent } from '../../models';

@Component({
  standalone: true,
  templateUrl:'../../integrations.html'
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
