import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { AuthService } from '../../auth.service';
import { InventoryService } from '../../inventory.service';
import { authMock, inventoryMock, product } from '../../testing/fixtures';
import { SpoolsComponent } from './spools.component';

describe('asynchronous spool filter options',()=>{
  it('renders the URL material after options arrive and resets on history navigation',async()=>{
    const data=inventoryMock();data.products.set([]);
    const params=new BehaviorSubject(convertToParamMap({material:'PETG',status:'opened'}));
    TestBed.configureTestingModule({providers:[provideRouter([]),
      {provide:ActivatedRoute,useValue:{queryParamMap:params}},
      {provide:AuthService,useValue:authMock('viewer')},{provide:InventoryService,useValue:data}]});
    const fixture=TestBed.createComponent(SpoolsComponent),component=fixture.componentInstance;
    fixture.detectChanges();await fixture.whenStable();
    expect(component.material()).toBe('PETG');
    const select=fixture.nativeElement.querySelector('#spool-material-filter') as HTMLSelectElement;
    data.products.set([product(),product({id:2,material:'PETG'})]);
    fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
    expect(select.value).toBe('PETG');
    expect(component.status()).toBe('opened');
    expect(data.updateSpool).not.toHaveBeenCalled();
    params.next(convertToParamMap({}));
    fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();
    expect(select.value).toBe('');
  });
});
