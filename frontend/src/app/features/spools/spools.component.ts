import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, dateText, grams, stockPercent } from '../../models';

@Component({
  standalone: true,
  templateUrl:'../../spools.html'
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
