import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { PrintersComponent } from './printers.component';
import { AuthService } from '../../auth.service';
import { InventoryService } from '../../inventory.service';
import { WorkspaceService } from '../../workspace.service';
import { authMock, inventoryMock, spool, workspaceMock } from '../../testing/fixtures';

async function setup(role:'admin'|'editor'|'viewer'){
  const api=workspaceMock();TestBed.configureTestingModule({providers:[provideRouter([]),{provide:AuthService,useValue:authMock(role)},{provide:InventoryService,useValue:inventoryMock()},{provide:WorkspaceService,useValue:api}]});
  const fixture=TestBed.createComponent(PrintersComponent);await fixture.componentInstance.refresh();fixture.detectChanges();await fixture.whenStable();return {fixture,api,component:fixture.componentInstance};
}
describe('usable physical spool slots',()=>{
  it('renders editor assignment controls and persists a nonzero tool assignment',async()=>{
    const {fixture,component,api}=await setup('editor');expect(fixture.nativeElement.querySelector('select[name="slotSpool"]')).toBeTruthy();
    component.printerSelection=1;component.slotTool=3;component.slotSpool=1;
    api.printerSlots.mockResolvedValue([{tool:3,spool_id:1,spool_uid:spool().uid,brand:'Example',product_name:'Basic'}]);
    await component.assignSlot();fixture.detectChanges();expect(api.assignSlot).toHaveBeenCalledWith(1,3,1);expect(fixture.nativeElement.textContent).toContain('Tool 3');
    await component.unloadSlot(3,1);expect(api.unloadSlot).toHaveBeenCalledWith(1,3);
  });
  it('shows viewer slot information without exposing mutation controls',async()=>{
    const {fixture,component,api}=await setup('viewer');component.slots.set({1:[{tool:3,spool_id:1,spool_uid:spool().uid,brand:'Example',product_name:'Basic'}]});fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Tool 3');expect(fixture.nativeElement.querySelector('select[name="slotSpool"]')).toBeNull();
    await component.unloadSlot(3,1);expect(api.unloadSlot).not.toHaveBeenCalled();expect(api.printerOperations).not.toHaveBeenCalled();
  });
});

describe('dragged spool assignments require an explicit save',()=>{
  it('prepares the same editor form without sending any write request',async()=>{
    const {component,api}=await setup('editor');
    const event={preventDefault(){},stopPropagation(){}} as DragEvent;
    component.slotTool=3;component.draggedSpool.set(spool());component.dropSpool(event,1);
    expect(component.printerSelection).toBe(1);expect(component.slotSpool).toBe(1);expect(component.slotTool).toBe(3);
    expect(api.assignSlot).not.toHaveBeenCalled();await component.assignSlot();expect(api.assignSlot).toHaveBeenCalledWith(1,3,1);
  });
  it('rejects drops in a viewer session even if a drag state was injected',async()=>{
    const {component,api}=await setup('viewer');
    component.draggedSpool.set(spool());component.dropSpool({preventDefault(){},stopPropagation(){}} as DragEvent,1);
    expect(component.slotSpool).toBe(0);expect(api.assignSlot).not.toHaveBeenCalled();
  });
});
