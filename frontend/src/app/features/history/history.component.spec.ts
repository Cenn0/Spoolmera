import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { beforeEach, describe, expect, it } from 'vitest';
import { HistoryComponent } from './history.component';
import { InventoryService } from '../../inventory.service';
import { deferred, inventoryMock, movement } from '../../testing/fixtures';
import { ApiMovementPage } from '../../core/api/generated-contracts';

describe('full movement history',()=>{
  let component:HistoryComponent,data:ReturnType<typeof inventoryMock>;
  beforeEach(()=>{data=inventoryMock();TestBed.configureTestingModule({providers:[provideRouter([]),{provide:ActivatedRoute,useValue:{queryParamMap:of(convertToParamMap({job:'42'}))}},{provide:InventoryService,useValue:data}]});component=TestBed.createComponent(HistoryComponent).componentInstance;});
  it('applies job deep links and server filters to every cursor page',async()=>{
    component.ngOnInit();await Promise.resolve();expect(data.movementPage).toHaveBeenCalledWith(expect.objectContaining({job_id:42}),undefined);
    data.movementPage.mockResolvedValueOnce({items:[movement({id:200})],next_cursor:200});component.source='print_job';component.actorId=3;await component.apply();
    data.movementPage.mockResolvedValueOnce({items:[movement({id:199})],next_cursor:null});await component.load(true);
    expect(data.movementPage).toHaveBeenLastCalledWith(expect.objectContaining({job_id:42,actor_id:3,source:'print_job'}),200);expect(component.items().map(row=>row.id)).toEqual([200,199]);
  });
  it('never appends an old next page after filters change',async()=>{
    data.movementPage.mockResolvedValueOnce({items:[movement({id:200})],next_cursor:200});await component.apply();
    const old=deferred<ApiMovementPage>();data.movementPage.mockReturnValueOnce(old.promise);const next=component.load(true);
    data.movementPage.mockResolvedValueOnce({items:[movement({id:7,spool_id:2})],next_cursor:null});component.spoolId=2;await component.apply();
    old.resolve({items:[movement({id:199})],next_cursor:null});await next;expect(component.items().map(row=>row.id)).toEqual([7]);
  });
});
