import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { beforeEach, describe, expect, it } from 'vitest';
import { ConsumptionComponent } from './consumption.component';
import { InventoryService } from '../../inventory.service';
import { AuthService } from '../../auth.service';
import { LANGUAGE_STORAGE_KEY } from '../../core/i18n/types';
import { WorkspaceService } from '../../workspace.service';
import { authMock, consumption, inventoryMock, job, workspaceMock } from '../../testing/fixtures';

describe('explicit actual consumption and revisions',()=>{
  let component:ConsumptionComponent,fixture:ComponentFixture<ConsumptionComponent>,api:ReturnType<typeof workspaceMock>;
  beforeEach(async()=>{api=workspaceMock();TestBed.configureTestingModule({providers:[provideRouter([]),{provide:InventoryService,useValue:inventoryMock()},{provide:AuthService,useValue:authMock('editor')},{provide:WorkspaceService,useValue:api}]});
    fixture=TestBed.createComponent(ConsumptionComponent);fixture.componentRef.setInput('job',job({status:'needs_review'}));component=fixture.componentInstance;await component.reload();component.reason='Failed print after the first layer';component.confirmed=true;});
  it('requires each physical roll to have an explicit actual amount, including zero',async()=>{
    await component.submit();expect(api.reconcileConsumption).not.toHaveBeenCalled();expect(component.error()).toContain('including zero');
    component.rows[0].actual_g=0;await component.submit();expect(api.reconcileConsumption.mock.calls[0][1].materials).toEqual([{spool_id:1,actual_g:0}]);
  });
  it('submits the corrected total without overwriting the original estimate or submitting a second full debit',async()=>{
    const state=consumption();state.materials[0].remaining_g=500;state.materials[0].accounted_g=100;state.accounting_revision=1;
    api.consumption.mockResolvedValue(state);await component.reload();component.rows[0].actual_g=37;component.confirmed=true;
    expect(component.expectedBalance(0)).toBe(563);await component.submit();
    expect(api.reconcileConsumption).toHaveBeenCalledWith(1,expect.objectContaining({mode:'actual',materials:[{spool_id:1,actual_g:37}],expected_accounting_revision:1,expected_updated_at:state.updated_at}));
    expect(component.snapshot()?.materials[0].estimated_g).toBe(100);
  });
  it('submits scale weights atomically with matching confirmed consumption',async()=>{
    component.rows[0]={spool_id:1,actual_g:37,measured:true,gross_g:763,tare_g:200};await component.submit();
    expect(api.reconcileConsumption.mock.calls[0][1].measurements).toEqual([{spool_id:1,gross_g:763,tare_g:200,expected_stock_revision:3}]);
  });
  it('refuses a scale reading that disagrees with the resulting stock',async()=>{
    component.rows[0]={spool_id:1,actual_g:37,measured:true,gross_g:700,tare_g:200};await component.submit();
    expect(api.reconcileConsumption).not.toHaveBeenCalled();expect(component.error()).toContain('must match');
  });
  it('reuses the same idempotency key after a lost response for unchanged confirmation',async()=>{
    api.reconcileConsumption.mockRejectedValueOnce(new HttpErrorResponse({status:0}));component.rows[0].actual_g=37;
    await component.submit();await component.submit();expect(api.reconcileConsumption.mock.calls[0][1].request_id).toBe(api.reconcileConsumption.mock.calls[1][1].request_id);
  });
  it('requires refreshed balances and a new explicit confirmation after a conflict',async()=>{
    api.reconcileConsumption.mockRejectedValueOnce(new HttpErrorResponse({status:409,error:{detail:'Stock changed'}}));component.rows[0].actual_g=37;
    await component.submit();expect(component.conflict()).toBe(true);await component.submit();expect(api.reconcileConsumption).toHaveBeenCalledTimes(1);
    await component.reload();expect(component.rows[0].actual_g).toBeNull();expect(component.confirmed).toBe(false);expect(component.conflict()).toBe(false);
  });
  it('does not send explicit actual fields with an estimated decision',async()=>{
    component.mode='estimated';await component.submit();expect(api.reconcileConsumption.mock.calls[0][1]).toEqual(expect.objectContaining({mode:'estimated',materials:[],measurements:[]}));
  });
  it('requires a fresh measurement to correct a booking after a later weighing',async()=>{
    const state=consumption();state.materials[0]={...state.materials[0],accounted_g:100,remaining_g:600,measurement_reconciliation_required:true,last_measured_g:600,last_measured_at:'2026-10-02T12:00:00Z'};
    api.consumption.mockResolvedValue(state);await component.reload();component.rows[0].actual_g=37;component.confirmed=true;
    await component.submit();expect(api.reconcileConsumption).not.toHaveBeenCalled();expect(component.error()).toContain('weighed after');
    component.rows[0].measured=true;component.rows[0].gross_g=800;
    expect(component.expectedBalance(0)).toBe(600);await component.submit();
    expect(api.reconcileConsumption.mock.calls[0][1]).toEqual(expect.objectContaining({materials:[{spool_id:1,actual_g:37}],measurements:[{spool_id:1,gross_g:800,tare_g:200,expected_stock_revision:3}]}));
  });
  it('supports a required current measurement when discarding a previously weighed booking',async()=>{
    const state=consumption();state.materials[0]={...state.materials[0],accounted_g:100,measurement_reconciliation_required:true};
    api.consumption.mockResolvedValue(state);await component.reload();component.mode='discard';component.confirmed=true;
    component.rows[0].measured=true;component.rows[0].gross_g=800;await component.submit();
    expect(api.reconcileConsumption.mock.calls[0][1]).toEqual(expect.objectContaining({mode:'discard',materials:[],measurements:[{spool_id:1,gross_g:800,tare_g:200,expected_stock_revision:3}]}));
  });
  it('does not permit an unrelated measurement change when the previously weighed job total is unchanged',async()=>{
    const state=consumption();state.materials[0]={...state.materials[0],accounted_g:100,measurement_reconciliation_required:true};
    api.consumption.mockResolvedValue(state);await component.reload();component.rows[0]={spool_id:1,actual_g:100,measured:true,gross_g:700,tare_g:200};component.confirmed=true;
    await component.submit();expect(api.reconcileConsumption).not.toHaveBeenCalled();expect(component.error()).toContain('must match');
  });

  it('switches an open consumption form between German and English without losing the confirmed measurement',async()=>{
    fixture.detectChanges();await fixture.whenStable();
    component.rows[0]={spool_id:1,actual_g:37,measured:true,gross_g:763,tare_g:200};
    component.reason='Failed print after the first layer';component.confirmed=true;
    fixture.detectChanges();await fixture.whenStable();
    const snapshot=component.snapshot(),row=component.rows[0],requests=api.consumption.mock.calls.length;
    try{
      component.i18n.setLanguage('de');fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Verbrauch prüfen');
      expect(fixture.nativeElement.textContent).toContain('Tatsächlicher Gesamtverbrauch (g)');
      expect(fixture.nativeElement.querySelector('.reconciliation-material input[type="number"]').value).toBe('37');
      expect(fixture.nativeElement.querySelector('textarea[name="reason"]').value).toBe('Failed print after the first layer');
      expect(component.rows[0]).toBe(row);expect(component.snapshot()).toBe(snapshot);expect(component.confirmed).toBe(true);
      component.i18n.setLanguage('en');fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Review consumption');
      expect(component.rows[0]).toBe(row);expect(component.confirmed).toBe(true);
      expect(api.consumption).toHaveBeenCalledTimes(requests);expect(api.reconcileConsumption).not.toHaveBeenCalled();
    }finally{component.i18n.setLanguage('en');localStorage.removeItem(LANGUAGE_STORAGE_KEY);document.cookie='fm_language=; Path=/; Max-Age=0';}
  });

  it('retranslates an existing conflict instruction while retaining its retry block and entered values',async()=>{
    api.reconcileConsumption.mockRejectedValueOnce(new HttpErrorResponse({status:409,error:{detail:'Stock changed'}}));
    component.rows[0].actual_g=37;await component.submit();
    expect(component.error()).toContain('Reload the latest balances');
    try{
      component.i18n.setLanguage('de');
      expect(component.error()).toContain('Lade die aktuellen Bestände neu');
      expect(component.conflict()).toBe(true);expect(component.rows[0].actual_g).toBe(37);
      await component.submit();expect(api.reconcileConsumption).toHaveBeenCalledTimes(1);
      component.i18n.setLanguage('en');expect(component.error()).toContain('Reload the latest balances');
    }finally{component.i18n.setLanguage('en');localStorage.removeItem(LANGUAGE_STORAGE_KEY);document.cookie='fm_language=; Path=/; Max-Age=0';}
  });

});
