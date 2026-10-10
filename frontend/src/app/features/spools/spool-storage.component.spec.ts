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
    localStorage.removeItem('spoolmera-spool-view');
    localStorage.removeItem('spoolmera-spool-sort');
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
    localStorage.removeItem('spoolmera-spool-view');
    localStorage.removeItem('spoolmera-spool-sort');
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
  it('focuses the staged confirmation before the board without saving a location',async()=>{
    component.setDisplay('locations');component.stageLocation(original,'Shelf C');
    fixture.detectChanges();await fixture.whenStable();
    const root=fixture.nativeElement as HTMLElement;
    const confirmation=root.querySelector<HTMLElement>('.storage-confirm')!;
    const board=root.querySelector<HTMLElement>('.storage-board')!;
    expect(document.activeElement).toBe(confirmation);
    expect(confirmation.compareDocumentPosition(board)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(component.locationConfirmed()).toBe(false);expect(data.updateSpool).not.toHaveBeenCalled();
  });
  it('refocuses and reveals the existing confirmation when another destination is selected',async()=>{
    component.extraLocations.set(['Shelf C','Shelf D']);
    component.setDisplay('locations');component.stageLocation(original,'Shelf C');
    fixture.detectChanges();await fixture.whenStable();
    const root=fixture.nativeElement as HTMLElement;
    const confirmation=root.querySelector<HTMLElement>('.storage-confirm')!;
    const select=root.querySelector<HTMLSelectElement>('.storage-spool select')!;
    const scroll=vi.fn();confirmation.scrollIntoView=scroll;
    component.locationConfirmed.set(true);select.focus();
    select.value='Shelf D';select.dispatchEvent(new Event('change'));
    fixture.detectChanges();await fixture.whenStable();
    expect(root.querySelector('.storage-confirm')).toBe(confirmation);
    expect(component.pendingLocation()?.target).toBe('Shelf D');
    expect(confirmation.textContent).toContain('Shelf D');
    expect(document.activeElement).toBe(confirmation);
    expect(scroll).toHaveBeenCalledExactlyOnceWith({block:'nearest',behavior:'instant'});
    expect(component.locationConfirmed()).toBe(false);expect(data.updateSpool).not.toHaveBeenCalled();
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
  it('keeps label selection reachable directly from location cards without changing inventory',async()=>{
    auth.user.set({...auth.user()!,role:'viewer'});
    component.setDisplay('locations');fixture.detectChanges();await fixture.whenStable();
    const root=fixture.nativeElement as HTMLElement;
    const label=root.querySelector<HTMLButtonElement>('.storage-label-selector')!;
    expect(label.getAttribute('aria-pressed')).toBe('false');
    label.click();fixture.detectChanges();await fixture.whenStable();
    expect(label.getAttribute('aria-pressed')).toBe('true');
    expect(root.querySelector('.storage-spool')?.classList.contains('selected')).toBe(true);
    expect(root.querySelector('.print-selected')?.getAttribute('href')).toContain(original.uid);
    expect(component.pendingLocation()).toBeNull();expect(data.updateSpool).not.toHaveBeenCalled();
    label.click();fixture.detectChanges();
    expect(component.selectedLabels()).toEqual([]);
  });
  it('allows sorting without modifying server data, and persists only the display choice',()=>{
    const newer=spool({id:2,uid:'22222222-2222-4222-8222-222222222222',remaining_g:100});
    component.items.set([original,newer]);component.setSpoolOrder('remaining-low');
    expect(component.filtered().map(s=>s.id)).toEqual([2,1]);
    expect(component.items().map(s=>s.id)).toEqual([1,2]);
    expect(localStorage.getItem('spoolmera-spool-sort')).toBe('remaining-low');
    expect(data.updateSpool).not.toHaveBeenCalled();
    component.setDisplay('locations');expect(localStorage.getItem('spoolmera-spool-view')).toBe('locations');
  });
});
