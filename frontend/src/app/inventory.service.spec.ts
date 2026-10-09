import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { InventoryService } from './inventory.service';
import { product, spool } from './testing/fixtures';
import { EMPTY_OVERVIEW, isLowStock } from './models';

describe('inventory freshness and authoritative filters',()=>{
  let service:InventoryService,http:HttpTestingController;
  beforeEach(()=>{TestBed.configureTestingModule({providers:[provideHttpClient(),provideHttpClientTesting()]});service=TestBed.inject(InventoryService);http=TestBed.inject(HttpTestingController);});
  afterEach(()=>http.verify());
  it('keeps newer inventory when overlapping reads complete in reverse order',async()=>{
    const old=service.load(['spools']);const first=http.expectOne('/api/spools');
    const fresh=service.load(['spools']);http.expectOne('/api/spools').flush([spool({remaining_g:400})]);await fresh;
    first.flush([spool({remaining_g:600})]);await old;
    expect(service.spools()[0].remaining_g).toBe(400);expect(service.loading()).toBe(false);
  });
  it('never repopulates a signed-out workspace from a pending response',async()=>{
    const pending=service.load(['spools']);const response=http.expectOne('/api/spools');service.reset();
    response.flush([spool()]);await pending;
    expect(service.spools()).toEqual([]);expect(service.ready()).toBe(false);expect(service.lastUpdated()).toBeNull();
  });
  it('refreshes overview and per-spool warnings after changing a product threshold',async()=>{
    const {id,uid,created_at,updated_at,spool_count,total_remaining_g,...payload}=product({low_stock_threshold_g:700});
    const done=service.updateProduct(id,payload);http.expectOne('/api/products/1').flush({id});await Promise.resolve();
    http.expectOne('/api/overview').flush({...EMPTY_OVERVIEW,total_spools:1,low_spools:1});
    http.expectOne('/api/products').flush([product({low_stock_threshold_g:700})]);
    http.expectOne('/api/spools').flush([spool({low_stock_threshold_g:700})]);http.expectOne('/api/movements?limit=200').flush([]);
    await done;expect(service.overview().low_spools).toBe(1);expect(service.lowStock()).toHaveLength(1);
  });
  it('uses product-specific inclusive warning levels, with zero disabled',()=>{
    for(const threshold of [0,1,20,200,500,1000])for(const remaining of [0,1,19,20,200,500,1000]){
      expect(isLowStock({remaining_g:remaining,low_stock_threshold_g:threshold})).toBe(remaining>0&&remaining<=threshold);
    }
  });
  it('passes archive, cursor and all filters to the server',async()=>{
    const done=service.spoolPage('archived',40,'Green','PLA','opened');
    const request=http.expectOne(req=>req.url==='/api/spools/page');
    expect(Object.fromEntries(request.request.params.keys().map(key=>[key,request.request.params.get(key)]))).toEqual({archived:'archived',limit:'100',before_id:'40',q:'Green',material:'PLA',status:'opened'});
    request.flush({items:[],next_cursor:null});await done;
  });
});
