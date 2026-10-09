import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { RestockComponent } from './restock.component';
import { InventoryService } from '../../inventory.service';
import { AuthService } from '../../auth.service';
import { authMock, inventoryMock } from '../../testing/fixtures';
import { ApiRestockItem } from '../../core/api/generated-contracts';

describe('restock planning',()=>{
  it('includes products with no rolls, distinguishes reserved from physical stock and refreshes after edits',async()=>{
    const data=inventoryMock();
    const empty:ApiRestockItem={product_id:1,brand:'Example',name:'Empty product',material:'PLA',color_name:'Green',color_hex:'#227755',target_stock_g:1000,remaining_g:0,reserved_g:0,available_g:0,active_spools:0,sealed_spools:0,suggested_g:1000};
    const reserved:ApiRestockItem={...empty,product_id:2,name:'Reserved product',remaining_g:600,reserved_g:500,available_g:100,active_spools:1,suggested_g:400};
    data.restock.mockResolvedValue({items:[empty,reserved]});
    TestBed.configureTestingModule({providers:[provideRouter([]),{provide:InventoryService,useValue:data},{provide:AuthService,useValue:authMock('viewer')}]});
    const fixture=TestBed.createComponent(RestockComponent);fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
    const text=fixture.nativeElement.textContent as string;expect(text).toContain('Empty product');expect(text).toContain('Reserved product');expect(text).toContain('400 g');expect(text).toContain('500 g');expect(text).toContain('100 g');expect(text).not.toContain('Edit target and product');
    data.restock.mockResolvedValue({items:[{...empty,target_stock_g:0,suggested_g:0}]});data.changed.update(n=>n+1);fixture.detectChanges();await fixture.whenStable();fixture.componentInstance.shortageOnly.set(true);fixture.detectChanges();expect(fixture.componentInstance.filtered()).toEqual([]);
  });
});
