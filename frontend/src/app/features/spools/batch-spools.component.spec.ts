import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { beforeEach, describe, expect, it } from 'vitest';
import { BatchSpoolsComponent } from './batch-spools.component';
import { InventoryService } from '../../inventory.service';
import { AuthService } from '../../auth.service';
import { authMock, inventoryMock, spool } from '../../testing/fixtures';

describe('batch confirmation and labels',()=>{
  let component:BatchSpoolsComponent,data:ReturnType<typeof inventoryMock>;
  beforeEach(()=>{data=inventoryMock();TestBed.configureTestingModule({providers:[provideRouter([]),{provide:InventoryService,useValue:data},{provide:AuthService,useValue:authMock('editor')}]});
    component=TestBed.createComponent(BatchSpoolsComponent).componentInstance;component.spool.product_id=1;});
  it('rejects changed quantity until the new batch is previewed',async()=>{
    component.prepare();component.confirmed=true;component.count=9;await component.create();expect(data.createBatch).not.toHaveBeenCalled();expect(component.preview()).toBeNull();
  });
  it('reuses the preview request key after a lost response and labels every returned UUID',async()=>{
    const rolls=[spool(),spool({id:2,uid:'33333333-3333-4333-8333-333333333333'})];
    data.createBatch.mockRejectedValueOnce(new HttpErrorResponse({status:0})).mockResolvedValueOnce({items:rolls,label_url:'/labels?uids='+rolls.map(s=>s.uid).join(',')});
    component.prepare();component.confirmed=true;await component.create();expect(component.uncertain()).toBe(true);await component.create();
    expect(data.createBatch).toHaveBeenCalledTimes(2);expect(data.createBatch.mock.calls[0][2]).toBe(data.createBatch.mock.calls[1][2]);
    expect(component.labelUrl).toContain(rolls[0].uid+','+rolls[1].uid);component.labelSize='50x30';expect(component.labelUrl).toContain('size=50x30');
  });
  it('clears old confirmation when an input is edited',()=>{
    component.prepare();const first=component.preview()?.requestId;component.confirmed=true;component.spool.location='Shelf B';component.changed();expect(component.confirmed).toBe(false);
    component.prepare();expect(component.preview()?.requestId).not.toBe(first);expect(component.preview()?.spool.location).toBe('Shelf B');
  });
});
