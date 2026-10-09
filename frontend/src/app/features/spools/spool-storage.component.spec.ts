import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthService } from '../../auth.service';
import { InventoryService } from '../../inventory.service';
import { authMock, inventoryMock, spool } from '../../testing/fixtures';
import { SpoolsComponent } from './spools.component';

describe('storage board: accessibility, staged moves and concurrent edits',()=>{
  let fixture:ComponentFixture<SpoolsComponent>,component:SpoolsComponent;
  let data:ReturnType<typeof inventoryMock>,auth:ReturnType<typeof authMock>;
  const original=spool();
  beforeEach(async()=>{
    localStorage.removeItem('filament-manager-spool-view');
    localStorage.removeItem('filament-manager-spool-sort');
    data=inventoryMock();auth=authMock('editor');
    TestBed.configureTestingModule({providers:[provideRouter([]),
      {provide:ActivatedRoute,useValue:{queryParamMap:new BehaviorSubject(convertToParamMap({}))}},
      {provide:InventoryService,useValue:data},{provide:AuthService,useValue:auth}]});
    fixture=TestBed.createComponent(SpoolsComponent);component=fixture.componentInstance;
    fixture.detectChanges();await fixture.whenStable();
    component.items.set([original]);
  });
  afterEach(()=>{
    fixture.destroy();
    localStorage.removeItem('filament-manager-spool-view');
    localStorage.removeItem('filament-manager-spool-sort');
  });
  it('presents drop columns and keyboard destination controls to editors',async()=>{
    component.setDisplay('locations');
    fixture.detectChanges();await fixture.whenStable();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('.storage-lane[data-location="Shelf A"]')).not.toBeNull();
    expect(root.querySelector('.storage-spool select')).not.toBeNull();
    expect((root.querySelector('.storage-spool select') as HTMLSelectElement).value).toBe('Shelf A');
    expect(root.querySelector('.storage-spool')?.getAttribute('data-spool-uid')).toBe(original.uid);
    expect(data.updateSpool).not.toHaveBeenCalled();
  });
  it('exposes keyboard scroll controls with correct boundary states and no inventory writes',async()=>{
    component.setDisplay('locations');
    component.locationDraft.set('Shelf C');component.createLocationLane();
    fixture.detectChanges();await fixture.whenStable();
    const root=fixture.nativeElement as HTMLElement;
    const board=root.querySelector<HTMLElement>('#storage-board')!;
    expect(board.getAttribute('role')).toBe('region');
    const previous=root.querySelector<HTMLButtonElement>('button[aria-label="Previous storage locations"]')!;
    const next=root.querySelector<HTMLButtonElement>('button[aria-label="Next storage locations"]')!;
    expect(previous.getAttribute('aria-controls')).toBe('storage-board');
    expect(next.getAttribute('aria-controls')).toBe('storage-board');
    Object.defineProperty(board,'clientWidth',{configurable:true,value:330});
    Object.defineProperty(board,'scrollWidth',{configurable:true,value:920});
    Object.defineProperty(board,'scrollLeft',{configurable:true,writable:true,value:0});
    const scroll=vi.fn();
    Object.defineProperty(board,'scrollBy',{configurable:true,value:scroll});
    component.updateStorageScrollState(board);fixture.detectChanges();
    expect(previous.disabled).toBe(true);expect(next.disabled).toBe(false);
    next.click();
    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({left:expect.any(Number)}));
    expect((scroll.mock.calls[0][0] as ScrollToOptions).left!).toBeGreaterThan(0);
    expect(component.pendingLocation()).toBeNull();
    board.scrollLeft=590;
    component.updateStorageScrollState(board);fixture.detectChanges();
    expect(previous.disabled).toBe(false);expect(next.disabled).toBe(true);
    previous.click();
    expect((scroll.mock.calls[scroll.mock.calls.length-1][0] as ScrollToOptions).left!).toBeLessThan(0);
    expect(data.updateSpool).not.toHaveBeenCalled();
  });
  it('stages browser drops without writing, then requires an explicit check',async()=>{
    component.locationDraft.set('Shelf C');component.createLocationLane();
    expect(component.storageBoard().some(item=>item.location==='Shelf C')).toBe(true);
    component.dragged.set(original);
    const event={preventDefault:vi.fn(),stopPropagation:vi.fn()} as unknown as DragEvent;
    component.dropLocation(event,'Shelf C');
    expect(component.pendingLocation()?.target).toBe('Shelf C');
    expect(component.dragged()).toBeNull();
    await component.saveLocation();
    expect(data.updateSpool).not.toHaveBeenCalled();
    component.locationConfirmed.set(true);
    data.spoolByUid.mockResolvedValue(original);
    await component.saveLocation();
    expect(data.updateSpool).toHaveBeenCalledExactlyOnceWith(original.id,{location:'Shelf C',expected_location:'Shelf A'});
    expect(component.pendingLocation()).toBeNull();
  });
  it('rejects stale changes and archived spools rather than silently overwriting',async()=>{
    component.stageLocation(original,'New A');
    component.locationConfirmed.set(true);
    data.spoolByUid.mockResolvedValue({...original,location:'Moved elsewhere'});
    await component.saveLocation();
    expect(data.updateSpool).not.toHaveBeenCalled();
    expect(component.locationError()).toContain('Spool location changed');
    component.stageLocation({...original,archived_at:'2026-10-01'},'New A');
    expect(component.pendingLocation()).toBeNull();
  });
  it('fails closed on an uncertain API result and never automatically retries',async()=>{
    component.stageLocation(original,'New A');component.locationConfirmed.set(true);
    data.spoolByUid.mockResolvedValue(original);
    data.updateSpool.mockRejectedValueOnce(new Error('Uncertain connection'));
    await component.saveLocation();
    expect(data.updateSpool).toHaveBeenCalledTimes(1);
    expect(component.pendingLocation()).toBeNull();
    expect(component.locationError()).toContain('Uncertain connection');
  });
  it('shows a read-only board to viewers',async()=>{
    auth.user.set({...auth.user()!,role:'viewer'});
    component.setDisplay('locations');fixture.detectChanges();await fixture.whenStable();
    expect(fixture.nativeElement.querySelectorAll('.storage-spool select')).toHaveLength(0);
    component.stageLocation(original,'New A');expect(component.pendingLocation()).toBeNull();
  });
  it('allows sorting without modifying server data, and persists only the display choice',()=>{
    const newer=spool({id:2,uid:'22222222-2222-4222-8222-222222222222',remaining_g:100});
    component.items.set([original,newer]);component.setSpoolOrder('remaining-low');
    expect(component.filtered().map(s=>s.id)).toEqual([2,1]);
    expect(component.items().map(s=>s.id)).toEqual([1,2]);
    expect(localStorage.getItem('filament-manager-spool-sort')).toBe('remaining-low');
    expect(data.updateSpool).not.toHaveBeenCalled();
    component.setDisplay('locations');expect(localStorage.getItem('filament-manager-spool-view')).toBe('locations');
  });
});
