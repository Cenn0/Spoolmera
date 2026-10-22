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
  it('searches all history pages on the server and clears the query on reset',async()=>{
    component.ngOnInit();await Promise.resolve();
    component.query='Müller Café_100%';component.source='manual';
    data.movementPage.mockResolvedValueOnce({items:[movement({id:12})],next_cursor:12});
    await component.apply();
    expect(data.movementPage).toHaveBeenLastCalledWith(expect.objectContaining({
      q:'Müller Café_100%',job_id:42,source:'manual',
    }),undefined);
    data.movementPage.mockResolvedValueOnce({items:[movement({id:9})],next_cursor:null});
    await component.load(true);
    expect(data.movementPage).toHaveBeenLastCalledWith(expect.objectContaining({q:'Müller Café_100%'}),12);
    component.reset();await Promise.resolve();
    expect(data.movementPage).toHaveBeenLastCalledWith(expect.objectContaining({q:'',source:'',job_id:undefined}),undefined);
  });

  it('exports every matching ledger entry using only the applied filters',async()=>{
    component.ngOnInit();await Promise.resolve();
    component.query='Müller Café_100%';component.kind.set('consume');
    component.actorId=3;component.source='manual';
    component.fromDate='2026-01-01';component.toDate='2026-01-31';
    await component.apply();
    const url=new URL(component.exportUrl(),'https://spoolmera.test');
    expect(url.pathname).toBe('/api/movements/export.csv');
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      job_id:'42',actor_id:'3',kind:'consume',source:'manual',
      q:'Müller Café_100%',from_date:'2026-01-01',to_date:'2026-01-31',
    });
    expect(url.searchParams.has('before_id')).toBe(false);
    expect(url.searchParams.has('limit')).toBe(false);
    // Editing the form must not export un-applied filters.
    component.query='unsaved change';component.fromDate='2026-02-01';
    expect(component.exportUrl()).toBe(url.pathname+url.search);
    component.toDate='2026-01-01';
    await component.apply();
    expect(component.error()).toContain('start date');
    expect(component.exportUrl()).toBe(url.pathname+url.search);
  });

  it('shows a directly downloadable CSV action alongside the history results',()=>{
    const fixture=TestBed.createComponent(HistoryComponent);
    fixture.detectChanges();
    const anchor=fixture.nativeElement.querySelector('a[download="spoolmera-movements-v1.csv"]');
    expect(anchor).not.toBeNull();
    expect(anchor.getAttribute('href')).toContain('/api/movements/export.csv');
  });

});
