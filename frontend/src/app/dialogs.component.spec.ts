import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { DialogsComponent } from './dialogs.component';
import { DialogService } from './dialog.service';
import { InventoryService } from './inventory.service';
import { AuthService } from './auth.service';
import { authMock, deferred, inventoryMock, movement, spool } from './testing/fixtures';
import { Movement } from './models';
import { I18nService } from './core/i18n';

describe('spool dialog ownership and nullable details',()=>{
  let data:ReturnType<typeof inventoryMock>,dialogs:DialogService;
  beforeEach(()=>{data=inventoryMock();data.spools.set([spool(),spool({id:2,uid:'33333333-3333-4333-8333-333333333333'})]);
    TestBed.configureTestingModule({providers:[provideRouter([]),{provide:InventoryService,useValue:data},{provide:AuthService,useValue:authMock('editor')}]});dialogs=TestBed.inject(DialogService);});
  it('does not attach delayed history from spool A to spool B',async()=>{
    const a=deferred<Movement[]>(),b=deferred<Movement[]>();data.movementsFor.mockImplementation((id:number)=>id===1?a.promise:b.promise);
    const fixture=TestBed.createComponent(DialogsComponent);dialogs.open({kind:'details',id:1});fixture.detectChanges();
    dialogs.open({kind:'details',id:2});fixture.detectChanges();
    b.resolve([movement({id:22,spool_id:2,note:'B record'})]);await b.promise;fixture.detectChanges();
    a.resolve([movement({id:11,note:'A record'})]);await a.promise;fixture.detectChanges();
    expect(fixture.componentInstance.history()[0].id).toBe(22);expect(fixture.nativeElement.textContent).toContain('B record');expect(fixture.nativeElement.textContent).not.toContain('A record');
  });
  it('preserves edited form input while inventory refreshes in the background',()=>{
    const fixture=TestBed.createComponent(DialogsComponent);dialogs.open({kind:'details',id:1});fixture.detectChanges();
    fixture.componentInstance.detail.location='Unsubmitted location';data.spools.set([spool({location:'Refreshed location'})]);fixture.detectChanges();
    expect(fixture.componentInstance.detail.location).toBe('Unsubmitted location');
  });
  it('shows purchase metadata and explicitly clears nullable purchase fields',async()=>{
    const fixture=TestBed.createComponent(DialogsComponent);dialogs.open({kind:'details',id:1});fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('2026-10-01');expect(fixture.nativeElement.textContent).toContain('€20.00');
    fixture.componentInstance.detail.purchase_price_cents=null;fixture.componentInstance.detail.purchased_on='';await fixture.componentInstance.saveDetails();
    expect(data.updateSpool).toHaveBeenCalledWith(1,expect.objectContaining({purchase_price_cents:null,purchased_on:null}));
  });
  it('opens an archived QR-linked spool even though active inventory omits it',()=>{
    const fixture=TestBed.createComponent(DialogsComponent);data.spools.set([]);
    dialogs.open({kind:'details',id:7,spool:spool({id:7,archived_at:'2026-10-07T12:00:00Z'})});fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Archived on');expect(fixture.nativeElement.textContent).toContain('Restore to active inventory');
    expect(fixture.nativeElement.textContent).not.toContain('Record use');
  });
  it('sends the stock revision displayed when weighing starts',async()=>{
    const fixture=TestBed.createComponent(DialogsComponent);dialogs.open({kind:'weigh',id:1});fixture.detectChanges();
    fixture.componentInstance.weighing.gross_g=750;data.spools.set([spool({remaining_g:550,stock_revision:4})]);fixture.detectChanges();await fixture.componentInstance.saveWeighing();
    expect(data.weigh).toHaveBeenCalledWith(1,750,200,'Physical scale measurement',3);
  });
  it('changes an open dialog language without resetting its draft or reloading spool data',async()=>{
    const fixture=TestBed.createComponent(DialogsComponent),i18n=TestBed.inject(I18nService);
    const previousLanguage=i18n.language();
    try{
      i18n.setLanguage('en');dialogs.open({kind:'details',id:1});fixture.detectChanges();await fixture.whenStable();
      const component=fixture.componentInstance,draft=component.detail;
      const location=fixture.nativeElement.querySelector('input[name="location"]') as HTMLInputElement;
      location.value='Opened';location.dispatchEvent(new Event('input'));fixture.detectChanges();
      draft.notes='Do not translate this note';draft.purchase_price_cents=1234;fixture.detectChanges();
      i18n.setLanguage('de');fixture.detectChanges();await fixture.whenStable();
      const rendered=fixture.nativeElement.textContent.replaceAll('\u00a0',' ');
      expect(rendered).toContain('Spulendetails');expect(rendered).toContain('01.10.2026');
      expect(rendered).toContain('1,75 mm');expect(rendered).toContain('20,00 €');
      expect(component.detail).toBe(draft);
      expect(component.detail).toMatchObject({location:'Opened',notes:'Do not translate this note',purchase_price_cents:1234});
      expect(fixture.nativeElement.querySelector('input[name="location"]')).toBe(location);
      expect(location.value).toBe('Opened');expect(data.movementsFor).toHaveBeenCalledTimes(1);
      expect(data.dryingRecords).toHaveBeenCalledTimes(1);expect(data.identifiers).toHaveBeenCalledTimes(1);
      i18n.setLanguage('en');fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Spool details');expect(component.detail).toBe(draft);
    }finally{i18n.setLanguage(previousLanguage);}
  });
});
