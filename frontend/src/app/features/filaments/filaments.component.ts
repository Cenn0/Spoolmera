import { I18nService, TranslatePipe } from '../../core/i18n';
import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../auth.service';
import { DialogService } from '../../dialog.service';
import { InventoryService } from '../../inventory.service';
import { SpoolVisualComponent } from '../../core/ui/spool-visual.component';
import { ProductOrder, productOrder, selectProducts, summarizeProducts, targetStockPercent, belowWarning } from './product-view';

const SORT_PREFERENCE = 'filament-manager-product-sort';

@Component({
  standalone: true,
  imports: [TranslatePipe, RouterLink, SpoolVisualComponent],
  templateUrl: '../../products.html',
  styleUrl: './filaments.component.css',
})
export class ProductsComponent {
  readonly i18n = inject(I18nService);
  readonly data = inject(InventoryService);
  readonly dialogs = inject(DialogService);
  readonly auth = inject(AuthService);
  readonly grams = (value: number): string => this.i18n.grams(value);
  readonly targetPercent = targetStockPercent;
  readonly belowWarning = belowWarning;
  readonly query = signal('');
  readonly material = signal('');
  readonly stockOnly = signal(false);
  readonly order = signal<ProductOrder>('name');
  readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('productSearch');
  readonly materials = computed(() => {
    const collator = new Intl.Collator(this.i18n.locale(), {numeric: true, sensitivity: 'base'});
    return Array.from(new Set(this.data.products().map(product => product.material))).sort(collator.compare);
  });
  readonly hasFilters = computed(() => !!this.query().trim() || !!this.material() || this.stockOnly());
  readonly filtered = computed(() => selectProducts(this.data.products(), {
    query: this.query(), material: this.material(), stockOnly: this.stockOnly(), order: this.order(),
  }, this.i18n.locale()));
  readonly summary = computed(() => summarizeProducts(this.filtered()));

  constructor() {
    try { this.order.set(productOrder(localStorage.getItem(SORT_PREFERENCE))); }
    catch { /* A restricted browser still has a fully usable, in-memory view. */ }
  }

  setOrder(value: string): void {
    const order = productOrder(value);
    this.order.set(order);
    try { localStorage.setItem(SORT_PREFERENCE, order); }
    catch { /* Sorting is a presentation preference, not a server write. */ }
  }

  resetFilters(): void {
    this.query.set(''); this.material.set(''); this.stockOnly.set(false);
    // The reset button disappears. Keep keyboard users at the search, not the document body.
    this.searchInput()?.nativeElement.focus({preventScroll: true});
  }
}
