import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, dateText, grams, stockPercent } from '../../models';

@Component({
  standalone: true,
  templateUrl:'../../products.html'
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
