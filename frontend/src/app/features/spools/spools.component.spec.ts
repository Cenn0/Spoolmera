import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthService } from '../../auth.service';
import { InventoryService } from '../../inventory.service';
import { authMock, inventoryMock, spool } from '../../testing/fixtures';
import { SpoolsComponent } from './spools.component';
import { addLabel } from '../../core/ui/label-selection';

describe('spool cards and ordered label tray',()=>{
  let data:ReturnType<typeof inventoryMock>,component:SpoolsComponent,fixture:ComponentFixture<SpoolsComponent>;
  const first=spool(),second=spool({id:2,uid:'22222222-2222-4222-8222-222222222222'});
  beforeEach(async()=>{
    localStorage.removeItem('filament-manager-spool-view');data=inventoryMock();
    TestBed.configureTestingModule({providers:[provideRouter([]),{provide:ActivatedRoute,useValue:{queryParamMap:of(convertToParamMap({product:'1'}))}},
      {provide:AuthService,useValue:authMock('viewer')},{provide:InventoryService,useValue:data}]});
    fixture=TestBed.createComponent(SpoolsComponent);component=fixture.componentInstance;fixture.detectChanges();await fixture.whenStable();
    component.items.set([first,second]);
  });
  afterEach(()=>{localStorage.removeItem('filament-manager-spool-view');});
  it('uses cards by default and carries the exact product filter into requests',()=>{
    expect(component.displayMode()).toBe('cards');expect(data.spoolPage).toHaveBeenCalledWith('active',undefined,'','','',1);
  });
  it('clears the exact product filter in the URL and preserves current search and archive mode',()=>{
    const navigate=vi.spyOn(TestBed.inject(Router),'navigate').mockResolvedValue(true);
    component.query.set('Blue');component.archived.set('archived');component.clearProductFilter();
    expect(navigate).toHaveBeenCalledWith([],expect.objectContaining({queryParamsHandling:'merge',
      queryParams:{product:null,q:'Blue',archived:'archived'}}));
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
  it('enforces the server maximum of one hundred labels',()=>{
    const selected=Array.from({length:100},(_,id)=>spool({id,uid:String(id)}));
    expect(addLabel(selected,second)).toHaveLength(100);
  });
});
