import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, dateText, grams, stockPercent } from '../../models';

@Component({
  standalone: true,
  templateUrl:'../../history.html'
})
export class HistoryComponent {
  readonly data = inject(InventoryService);
  readonly dateText = dateText;
  readonly grams = grams;
  readonly kind = signal('');
  readonly filtered = computed(() => this.data.movements().filter(m => !this.kind() || m.kind === this.kind()));
}
