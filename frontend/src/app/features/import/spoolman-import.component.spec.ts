import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SpoolmanImportComponent } from './spoolman-import.component';
import { InventoryService } from '../../inventory.service';
import { AuthService } from '../../auth.service';
import { authMock, inventoryMock } from '../../testing/fixtures';

const preview={dry_run:true,source:'spoolman',spools_created:1,spools_skipped:0,products_created:1,products_skipped:0,archived_skipped:0};
function file(name:string,bytes:string){const selected=new File([bytes],name);Object.defineProperty(selected,'text',{value:vi.fn().mockResolvedValue(bytes)});return selected;}
function choose(component:SpoolmanImportComponent,selected:File){component.onFile({target:{files:[selected],value:'selected'}} as unknown as Event);}
describe('Spoolman preview ownership',()=>{
  let component:SpoolmanImportComponent,http:HttpTestingController;
  beforeEach(()=>{TestBed.configureTestingModule({providers:[provideHttpClient(),provideHttpClientTesting(),{provide:InventoryService,useValue:inventoryMock()},{provide:AuthService,useValue:authMock('editor')}]});
    http=TestBed.inject(HttpTestingController);component=TestBed.createComponent(SpoolmanImportComponent).componentInstance;});
  afterEach(()=>http.verify());
  it('never commits file B using a delayed preview of file A',async()=>{
    choose(component,file('a.json','{"spools":[1]}'));const reading=component.previewImport();await Promise.resolve();
    const response=http.expectOne('/api/import/spoolman?source=spoolman&dry_run=true');
    choose(component,file('b.json','{"spools":[1,2,3,4,5,6,7,8,9]}'));
    response.flush(preview);await reading;expect(component.preview()).toBeNull();
    component.confirmed=true;await component.commit();http.expectNone(request=>request.method==='POST');
  });
  it('requires a new preview when the source changes while a request is outstanding',async()=>{
    choose(component,file('a.json','{"spools":[1]}'));const reading=component.previewImport();await Promise.resolve();
    const response=http.expectOne('/api/import/spoolman?source=spoolman&dry_run=true');
    component.source='second-server';component.invalidate();response.flush(preview);await reading;
    expect(component.preview()).toBeNull();expect(component.confirmed).toBe(false);
  });
  it('commits the exact reviewed bytes instead of reading a mutable file again',async()=>{
    const selected=file('a.json','{"spools":[1]}');choose(component,selected);const reading=component.previewImport();await Promise.resolve();
    http.expectOne('/api/import/spoolman?source=spoolman&dry_run=true').flush(preview);await reading;
    vi.mocked(selected.text).mockResolvedValue('DIFFERENT CONTENT');component.confirmed=true;const commit=component.commit();
    const request=http.expectOne('/api/import/spoolman?source=spoolman&dry_run=false');expect(request.request.body).toBe('{"spools":[1]}');
    request.flush({...preview,dry_run:false});await commit;expect(selected.text).toHaveBeenCalledTimes(1);
  });
  it('drops both preview and prior confirmation on reselection of the same file',async()=>{
    const selected=file('a.json','{}');choose(component,selected);const reading=component.previewImport();await Promise.resolve();
    http.expectOne('/api/import/spoolman?source=spoolman&dry_run=true').flush(preview);await reading;component.confirmed=true;
    choose(component,selected);expect(component.confirmed).toBe(false);expect(component.preview()).toBeNull();
  });
});
