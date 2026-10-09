import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { describe, expect, it } from 'vitest';
import { CatalogComponent } from './catalog.component';
import { AuthService } from '../../auth.service';
import { authMock } from '../../testing/fixtures';

describe('catalog cascading request ownership',()=>{
  it('discards a late variant from the previous brand when a new brand is selected',async()=>{
    TestBed.configureTestingModule({providers:[provideHttpClient(),provideHttpClientTesting(),{provide:AuthService,useValue:authMock('editor')}]});
    const component=TestBed.createComponent(CatalogComponent).componentInstance,http=TestBed.inject(HttpTestingController);
    component.brandSlug='a';component.materialSlug='pla';component.filamentSlug='basic';component.variantSlug='green';const old=component.selectVariant();
    const variant=http.expectOne('/api/catalog/brands/a/materials/pla/filaments/basic/variants/green');
    component.brandSlug='b';const current=component.selectBrand();http.expectOne('/api/catalog/brands/b').flush({name:'B',materials:[]});await current;
    variant.flush({name:'Old green',color_hex:'#227755',sizes:[]});await old;expect(component.brand()?.name).toBe('B');expect(component.variant()).toBeNull();expect(component.loading()).toBe(false);http.verify();
  });
});
