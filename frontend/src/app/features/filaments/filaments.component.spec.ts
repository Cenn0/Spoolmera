import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthService } from '../../auth.service';
import { DialogService } from '../../dialog.service';
import { InventoryService } from '../../inventory.service';
import { I18nService } from '../../core/i18n';
import { authMock, inventoryMock, product } from '../../testing/fixtures';
import { ProductsComponent } from './filaments.component';

const SORT_KEY = 'spoolmera-product-sort';

describe('filament gallery controls and state', () => {
  let fixture: ComponentFixture<ProductsComponent>;
  let component: ProductsComponent;
  let data: ReturnType<typeof inventoryMock>;
  let auth: ReturnType<typeof authMock>;
  let dialogs: {open: ReturnType<typeof vi.fn>};
  beforeEach(() => {
    TestBed.resetTestingModule();
    localStorage.removeItem(SORT_KEY);
    data = inventoryMock(); auth = authMock(); dialogs = {open: vi.fn()};
    data.products.set([
      product({id: 1, name: 'Matte', material: 'PLA', total_remaining_g: 2500, spool_count: 3}),
      product({id: 2, name: 'Basic', material: 'PLA', total_remaining_g: 0, spool_count: 2}),
      product({id: 3, name: 'Clear', material: 'PETG', color_name: 'Ocean', total_remaining_g: 310, spool_count: 1}),
    ]);
    data.overview.update(value => ({...value, total_spools: 999}));
    TestBed.configureTestingModule({imports: [ProductsComponent], providers: [provideRouter([]),
      {provide: InventoryService, useValue: data}, {provide: AuthService, useValue: auth}, {provide: DialogService, useValue: dialogs},
    ]});
    TestBed.inject(I18nService).setLanguage('en');
    fixture = TestBed.createComponent(ProductsComponent); component = fixture.componentInstance;
  });
  afterEach(() => {
    vi.restoreAllMocks(); TestBed.resetTestingModule(); localStorage.removeItem(SORT_KEY);
  });
  const text = () => fixture.nativeElement.textContent as string;
  const ids = () => Array.from(fixture.nativeElement.querySelectorAll('.filament-card') as NodeListOf<HTMLElement>).map(item => Number(item.dataset['productId']));

  it('does not mix filtered totals with the global inventory', () => {
    component.query.set('Ocean'); fixture.detectChanges();
    const summary = fixture.nativeElement.querySelector('#product-results').textContent;
    expect(summary).toContain('1 filament product'); expect(summary).toContain('1 active roll');
    expect(summary).toContain('310 g'); expect(summary).not.toContain('999');
    expect(ids()).toEqual([3]);
  });
  it('sorts through the actual select control and saves only the preference', () => {
    fixture.detectChanges();
    const select = fixture.nativeElement.querySelector('.product-order select') as HTMLSelectElement;
    select.value = 'stock-high'; select.dispatchEvent(new Event('change')); fixture.detectChanges();
    expect(ids()).toEqual([1, 3, 2]); expect(localStorage.getItem(SORT_KEY)).toBe('stock-high');
    expect(data.updateSpool).not.toHaveBeenCalled(); expect(dialogs.open).not.toHaveBeenCalled();
  });
  it('loads a saved sort preference on a new instance', () => {
    fixture.destroy(); localStorage.setItem(SORT_KEY, 'stock-low');
    fixture = TestBed.createComponent(ProductsComponent); fixture.detectChanges();
    expect(fixture.componentInstance.order()).toBe('stock-low'); expect(ids()).toEqual([2, 3, 1]);
  });
  it('keeps sorting usable when browser storage throws', () => {
    fixture.destroy();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {throw new DOMException('Blocked', 'SecurityError');});
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {throw new DOMException('Blocked', 'SecurityError');});
    fixture = TestBed.createComponent(ProductsComponent); component = fixture.componentInstance;
    expect(component.order()).toBe('name'); expect(() => component.setOrder('stock-high')).not.toThrow();
    fixture.detectChanges(); expect(ids()).toEqual([1, 3, 2]);
  });
  it('resets all filters, preserves sort and restores keyboard focus to search', () => {
    component.query.set('missing'); component.material.set('PLA'); component.stockOnly.set(true); component.setOrder('stock-high');
    fixture.detectChanges();
    const focus = vi.spyOn(fixture.nativeElement.querySelector('#product-search') as HTMLInputElement, 'focus');
    fixture.nativeElement.querySelector('.product-empty button').click(); fixture.detectChanges();
    expect(component.hasFilters()).toBe(false); expect(component.order()).toBe('stock-high'); expect(ids()).toEqual([1, 3, 2]);
    expect(focus).toHaveBeenCalledWith({preventScroll: true});
  });
  it('changes language without resetting query, material, stock filter or order', () => {
    component.query.set('Ocean'); component.material.set('PETG'); component.stockOnly.set(true); component.setOrder('stock-low');
    TestBed.inject(I18nService).setLanguage('de'); fixture.detectChanges();
    expect(text()).toContain('1 Filamentprodukt'); expect(text()).toContain('1 aktive Spule'); expect(text()).toContain('Filamente sortieren');
    expect(component.query()).toBe('Ocean'); expect(component.material()).toBe('PETG'); expect(component.stockOnly()).toBe(true); expect(component.order()).toBe('stock-low');
  });
  it('retains exact product navigation and contextual edit labels', () => {
    component.query.set('Ocean'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.spool-card-actions a').getAttribute('href')).toBe('/spools?product=3');
    expect(fixture.nativeElement.querySelector('.icon-btn').getAttribute('aria-label')).toBe('Edit filament: Example · Clear · Ocean');
  });
  it('distinguishes first load, load failure and a genuinely empty catalogue', () => {
    data.products.set([]); data.ready.set(false); data.loading.set(true); fixture.detectChanges();
    expect(text()).toContain('Loading filament products…'); expect(text()).not.toContain('No filament products yet.');
    data.loading.set(false); data.error.set('offline'); fixture.detectChanges();
    expect(text()).toContain('Filament products could not be loaded.');
    fixture.nativeElement.querySelector('.product-empty button').click(); expect(data.load).toHaveBeenCalledOnce();
    data.ready.set(true); data.error.set(''); fixture.detectChanges(); expect(text()).toContain('No filament products yet.');
  });
  it('offers the first-product action to editors but not viewers', () => {
    data.products.set([]); fixture.detectChanges();
    fixture.nativeElement.querySelector('.product-empty button').click(); expect(dialogs.open).toHaveBeenCalledWith({kind: 'product'});
    auth.user.set({...auth.user()!, role: 'viewer'}); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.product-empty button')).toBeNull();
  });
  it('shows target progress and warning indicators without modifying stock', () => {
    fixture.detectChanges();
    const first = fixture.nativeElement.querySelector('.filament-card[data-product-id="1"]') as HTMLElement;
    const gauge = first.querySelector('[role="progressbar"]') as HTMLElement;
    expect(gauge.getAttribute('aria-valuenow')).toBe('100');
    expect(first.textContent).toContain('Target stock');
    const low = fixture.nativeElement.querySelector('.filament-card[data-product-id="2"]') as HTMLElement;
    expect(low.textContent).toContain('Below warning level');
    expect(data.updateSpool).not.toHaveBeenCalled();
  });
  it('recomputes the filtered stock when inventory data refreshes', () => {
    component.material.set('PETG'); fixture.detectChanges(); expect(component.summary().remaining_g).toBe(310);
    data.products.update(items => items.map(item => item.id === 3 ? {...item, total_remaining_g: 275} : item)); fixture.detectChanges();
    expect(component.summary()).toEqual({products: 1, spools: 1, remaining_g: 275}); expect(text()).toContain('275 g');
  });
});
