import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthService } from '../../auth.service';
import { InventoryService } from '../../inventory.service';
import { authMock, inventoryMock, spool, deferred } from '../../testing/fixtures';
import { SpoolsComponent } from './spools.component';
import { addLabel } from '../../core/ui/label-selection';

describe('spool cards and ordered label tray',()=>{
  let data:ReturnType<typeof inventoryMock>,component:SpoolsComponent,fixture:ComponentFixture<SpoolsComponent>;
  let params:BehaviorSubject<ReturnType<typeof convertToParamMap>>;
  const first=spool(),second=spool({id:2,uid:'22222222-2222-4222-8222-222222222222'});
  beforeEach(async()=>{
    localStorage.removeItem('filament-manager-spool-view');data=inventoryMock();params=new BehaviorSubject(convertToParamMap({product:'1'}));
    TestBed.configureTestingModule({providers:[provideRouter([]),{provide:ActivatedRoute,useValue:{queryParamMap:params}},
      {provide:AuthService,useValue:authMock('viewer')},{provide:InventoryService,useValue:data}]});
    fixture=TestBed.createComponent(SpoolsComponent);component=fixture.componentInstance;fixture.detectChanges();await fixture.whenStable();
    component.items.set([first,second]);
  });
  afterEach(()=>{localStorage.removeItem('filament-manager-spool-view');});
  it('uses cards by default and carries the exact product filter into requests',()=>{
    expect(component.displayMode()).toBe('cards');expect(data.spoolPage).toHaveBeenCalledWith('active',undefined,'','','',1,false);
  });
  it('clears the exact product filter in the URL and preserves current search and archive mode',()=>{
    const navigate=vi.spyOn(TestBed.inject(Router),'navigate').mockResolvedValue(true);
    component.query.set('Blue');component.archived.set('archived');component.clearProductFilter();
    expect(navigate).toHaveBeenCalledWith([],expect.objectContaining({queryParamsHandling:'merge',
      queryParams:{product:null,q:'Blue',archived:'archived',material:null,status:null,low:null}}));
  });
  it('retains selected identities while filtering, changing views and refreshing',async()=>{
    component.toggleLabel(first.uid);component.toggleLabel(second.uid);component.setDisplay('table');
    data.spoolPage.mockResolvedValue({items:[spool({remaining_g:450})],next_cursor:null});await component.refresh();
    expect(component.selectedLabels()).toEqual([first.uid,second.uid]);expect(component.selectedSpools()[0].remaining_g).toBe(450);
    expect(component.selectedSpools()[1]).toBe(second);expect(component.labelUrl).toContain(first.uid+','+second.uid);
  });
  it('is duplicate-safe, ordered and reversible with keyboard-accessible buttons',()=>{
    component.addToTray(first);component.addToTray(first);component.addToTray(second);
    component.moveSelected(second.uid,-1);expect(component.selectedLabels()).toEqual([second.uid,first.uid]);
    component.moveSelected(second.uid,-1);expect(component.selectedLabels()).toEqual([second.uid,first.uid]);
    component.toggleLabel(second.uid);expect(component.selectedLabels()).toEqual([first.uid]);
  });
  it('updates the rendered print URL when the Move up button is clicked',async()=>{
    component.addToTray(first);component.addToTray(second);fixture.detectChanges();await fixture.whenStable();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('.print-selected')?.getAttribute('href')).toContain(first.uid+','+second.uid);
    const rows=root.querySelectorAll('.label-tray-item');
    (rows[1].querySelector('button[aria-label="Move up"]') as HTMLButtonElement).click();
    await fixture.whenStable();fixture.detectChanges();
    expect(root.querySelector('.print-selected')?.getAttribute('href')).toContain(second.uid+','+first.uid);
    expect(data.spoolPage).toHaveBeenCalled();
  });
  it('does not trust arbitrary external drag payloads',()=>{
    component.dropOnTray({preventDefault:vi.fn(),stopPropagation:vi.fn(),dataTransfer:{getData:()=>first.uid}} as unknown as DragEvent);
    expect(component.selectedLabels()).toEqual([]);
  });
  it('reorders a drop once without bubbling into the outer tray',()=>{
    component.addToTray(first);component.addToTray(second);component.dragged.set(second);
    const event={preventDefault:vi.fn(),stopPropagation:vi.fn()} as unknown as DragEvent;
    component.reorderSelected(event,first.uid);expect(component.selectedLabels()).toEqual([second.uid,first.uid]);expect(event.stopPropagation).toHaveBeenCalled();expect(component.dragged()).toBeNull();
  });
  it('reports active mobile filters and toggles controls without resetting filter values or labels',async()=>{
    component.toggleLabel(first.uid);component.material.set('PETG');component.archived.set('all');
    expect(component.activeFilterCount()).toBe(2);
    fixture.detectChanges();await fixture.whenStable();
    const button=fixture.nativeElement.querySelector('.mobile-filter-toggle') as HTMLButtonElement;
    expect(button.getAttribute('aria-expanded')).toBe('false');button.click();
    await fixture.whenStable();fixture.detectChanges();
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(fixture.nativeElement.querySelector('#inventory-filters').classList.contains('filters-open')).toBe(true);
    button.click();await fixture.whenStable();fixture.detectChanges();
    expect(button.getAttribute('aria-expanded')).toBe('false');expect(component.material()).toBe('PETG');
    expect(component.selectedLabels()).toEqual([first.uid]);expect(component.activeFilterCount()).toBe(2);
  });
  it('enforces the server maximum of one hundred labels',()=>{
    const selected=Array.from({length:100},(_,id)=>spool({id,uid:String(id)}));
    expect(addLabel(selected,second)).toHaveLength(100);
  });
  it('restores all filters from the URL and clears them on history navigation',async()=>{
    params.next(convertToParamMap({q:'Green',material:'PETG',status:'opened',archived:'all',product:'2',low:'1'}));
    await fixture.whenStable();
    expect(data.spoolPage).toHaveBeenLastCalledWith('all',undefined,'Green','PETG','opened',2,true);
    expect(component.activeFilterCount()).toBe(4);
    params.next(convertToParamMap({}));await fixture.whenStable();
    expect(component.query()).toBe('');expect(component.material()).toBe('');expect(component.status()).toBe('');
    expect(component.productId()).toBeUndefined();expect(component.lowOnly()).toBe(false);
    expect(component.activeFilterCount()).toBe(0);
  });
  it('bounds untrusted URL values and rejects invalid states and product identities',async()=>{
    params.next(convertToParamMap({q:'x'.repeat(200),material:'x'.repeat(80),status:'unknown',archived:'bad',product:'1e2',low:'false'}));
    await fixture.whenStable();expect(component.query()).toHaveLength(120);expect(component.material()).toHaveLength(32);
    expect(component.status()).toBe('');expect(component.archived()).toBe('active');expect(component.productId()).toBeUndefined();
  });
  it('uses a global low-stock shortcut without keeping unrelated filters',()=>{
    const navigate=vi.spyOn(TestBed.inject(Router),'navigate').mockResolvedValue(true);
    component.material.set('PETG');component.query.set('Archive');component.quickFilter('low');
    expect(navigate).toHaveBeenCalledWith([],expect.objectContaining({queryParams:{q:null,material:null,status:null,archived:null,product:null,low:'1'}}));
    expect(data.updateSpool).not.toHaveBeenCalled();
  });
  it('keeps existing card DOM and focus while a same-filter refresh is pending',async()=>{
    fixture.detectChanges();await fixture.whenStable();
    const root=fixture.nativeElement as HTMLElement,card=root.querySelector('.spool-card');
    const handle=card?.querySelector('.drag-handle') as HTMLButtonElement;handle.focus();
    const reply=deferred<{items:ReturnType<typeof spool>[];next_cursor:null}>();data.spoolPage.mockReturnValueOnce(reply.promise);
    const refreshing=component.refresh();fixture.detectChanges();
    expect(component.items()).toEqual([first,second]);expect(root.querySelector('.spool-card')).toBe(card);
    expect(document.activeElement).toBe(handle);expect(root.querySelector('.inventory-results')?.getAttribute('aria-busy')).toBe('true');
    reply.resolve({items:[spool({remaining_g:550}),second],next_cursor:null});await refreshing;fixture.detectChanges();
    expect(root.querySelector('.spool-card')).toBe(card);expect(document.activeElement).toBe(handle);
    expect(component.items()[0].remaining_g).toBe(550);
  });
  it('keeps rows and a usable retry when a same-filter refresh fails',async()=>{
    data.spoolPage.mockRejectedValueOnce(new Error('Offline'));await component.refresh();
    expect(component.items()).toEqual([first,second]);expect(component.error()).toBe('Offline');expect(component.loading()).toBe(false);
  });
  it('refreshes the loaded window rather than silently discarding older pages',async()=>{
    const third=spool({id:3,uid:'33333333-3333-4333-8333-333333333333'});
    component.items.set([third,second,first]);
    data.spoolPage.mockResolvedValueOnce({items:[third,second],next_cursor:2}).mockResolvedValueOnce({items:[first],next_cursor:null});
    await component.refresh();expect(component.items()).toEqual([third,second,first]);
    expect(data.spoolPage).toHaveBeenLastCalledWith('active',2,'','','',1,false);
  });
  it('discards a late response belonging to previous filters',async()=>{
    const old=deferred<{items:ReturnType<typeof spool>[];next_cursor:null}>();
    data.spoolPage.mockReturnValueOnce(old.promise);const stale=component.refresh();
    component.material.set('PETG');data.spoolPage.mockResolvedValueOnce({items:[second],next_cursor:null});
    const fresh=component.refresh();expect(component.items()).toEqual([]);await fresh;
    old.resolve({items:[first],next_cursor:null});await stale;expect(component.items()).toEqual([second]);
  });
  it('defers background refresh until a native drag ends',async()=>{
    data.spoolPage.mockClear();component.dragged.set(first);await component.refresh();
    expect(data.spoolPage).not.toHaveBeenCalled();component.dragEnd();await fixture.whenStable();expect(data.spoolPage).toHaveBeenCalledTimes(1);
  });
  it('batch selection is ordered and preserves selection outside the current filter',()=>{
    const hidden=spool({id:3,uid:'33333333-3333-4333-8333-333333333333'});component.addToTray(hidden);
    component.selectLoaded();component.selectLoaded();expect(component.selectedLabels()).toEqual([hidden.uid,first.uid,second.uid]);
    component.deselectLoaded();expect(component.selectedLabels()).toEqual([hidden.uid]);
  });
  it('rejects an over-limit batch atomically rather than partially selecting it',()=>{
    const old=Array.from({length:99},(_,id)=>spool({id:id+10,uid:String(id)}));component.selectedSpools.set(old);
    expect(component.canSelectLoaded()).toBe(false);component.selectLoaded();expect(component.selectedSpools()).toEqual(old);
  });
  it('shows the actual insertion side and announces the resulting position in both languages',()=>{
    component.addToTray(first);component.addToTray(second);component.dragged.set(first);component.dropTarget.set(second.uid);
    expect(component.dropSide(second.uid)).toBe('after');component.moveSelected(first.uid,1);
    expect(component.i18n.t(component.labelFeedback())).toBe('Label for spool #1: position 2 of 2.');
    component.i18n.setLanguage('de');expect(component.i18n.t(component.labelFeedback())).toBe('Etikett für Spule #1: Position 2 von 2.');
    component.i18n.setLanguage('en');
  });

  it('does not install a pending response under an ongoing native drag',async()=>{
    const reply=deferred<{items:ReturnType<typeof spool>[];next_cursor:null}>();data.spoolPage.mockReturnValueOnce(reply.promise);
    const pending=component.refresh();component.dragStart({dataTransfer:{setData:vi.fn()}} as unknown as DragEvent,first);
    reply.resolve({items:[second],next_cursor:null});await pending;expect(component.items()).toEqual([first,second]);
    component.dragEnd();await fixture.whenStable();expect(component.loading()).toBe(false);
  });

  it('bounds refresh pagination when the server repeats a cursor',async()=>{
    component.items.set([first,second,spool({id:3,uid:'3'})]);
    data.spoolPage.mockResolvedValueOnce({items:[second],next_cursor:2}).mockResolvedValueOnce({items:[],next_cursor:2});
    await component.refresh();expect(component.loading()).toBe(false);expect(component.error()).toContain('Refresh and retry');
    expect(component.items()).toHaveLength(3);
  });

});
