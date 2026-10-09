import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';
import { OperationsComponent } from './operations.component';
import { WorkspaceService } from '../../workspace.service';
import { ApiAlerts, ApiDiagnostics } from '../../core/api/generated-contracts';
import { I18nService } from '../../core/i18n/i18n.service';


function diagnosticsState():ApiDiagnostics {
  return {version:'0.10.0',schema_version:10,status:'ok',jobs:[],uncertain_commands:0,commands:[],
      poller:{status:'running',interval_seconds:15,started_at:null,last_cycle_at:'2026-10-01T12:00:00Z',last_success_at:null,last_heartbeat_at:null,last_error:null,lease_held:true,lease_expires_at:null},
      printers:[{id:1,name:'Workshop',enabled:true,active_jobs:1,last_attempt_at:null,last_success_at:null,consecutive_failures:2,last_error:'Connection timed out',observation_age_seconds:90,freshness:'stale'}],
      backup:{status:'never',last_success_at:null,last_size_bytes:null,last_error:null},storage:{database_bytes:1000,wal_bytes:0,free_bytes:1000000000,reserve_bytes:1000000,low_space:false},
      restore:{last_restored_at:null,requires_token_reissue:false},slicer:{enabled:false,configured:false},material_mapping_warnings:[],
      printer_operations:[{printer_id:1,printer_name:'Workshop',operation_id:'op-1',job_id:1,kind:'upload',state:'unknown',created_at:'2026-10-01T12:00:00Z',updated_at:'2026-10-01T12:00:00Z'}]};
}

describe('operational diagnostics',()=>{
  it('distinguishes a running observation service from an offline printer and exposes uncertain uploads',async()=>{
    const state=diagnosticsState();
    TestBed.configureTestingModule({providers:[provideRouter([]),{provide:WorkspaceService,useValue:{diagnostics:vi.fn().mockResolvedValue(state),alerts:vi.fn().mockResolvedValue({schema_version:'1',instance_epoch:'test',generated_at:'2026-10-01T12:00:00Z',truncated:false,alerts:[]})}}]});
    const fixture=TestBed.createComponent(OperationsComponent);fixture.detectChanges();await fixture.componentInstance.refresh();fixture.detectChanges();const text=fixture.nativeElement.textContent as string;
    expect(text).toContain('Operating');expect(text).toContain('Running');expect(text).toContain('Out of date');expect(text).toContain('File upload');expect(text).toContain('Outcome uncertain');
    const link=[...fixture.nativeElement.querySelectorAll('a')].find((anchor)=>anchor.textContent.includes('Review operation'));
    expect(link?.getAttribute('href')).toContain('/printers');
  });

  it('translates live operational decisions and alerts without changing identities or reloading data',async()=>{
    const state=diagnosticsState();
    state.printer_operations[0].job_id=1234;
    state.backup.last_size_bytes=1572864;
    state.commands=[{id:'command-1',printer_id:1,printer_name:'Workshop',job_id:1234,action:'pause',state:'unknown',created_at:'2026-10-01T12:00:00Z',updated_at:'2026-10-01T12:00:00Z'}];
    const alerts:ApiAlerts={schema_version:'1',instance_epoch:'test',generated_at:'2026-10-01T12:00:00Z',truncated:false,alerts:[
      {id:'low_stock:test',category:'low_stock',severity:'warning',title:'Low filament stock',message:'Spool #1234 has 1250 g remaining (threshold 2000 g).',entity_type:'spool',entity_id:'1234'},
      {id:'job_review:1234',category:'job_review',severity:'warning',title:'Print material needs review',message:'Review actual material usage for print job #1234.',entity_type:'print_job',entity_id:'1234'},
      {id:'printer_offline:1',category:'printer_offline',severity:'error',title:'Printer connection needs attention',message:'Printer #1 could not be observed in at least three consecutive polling attempts.',entity_type:'printer',entity_id:'1'}
    ]};
    const api={diagnostics:vi.fn().mockResolvedValue(state),alerts:vi.fn().mockResolvedValue(alerts)};
    TestBed.configureTestingModule({providers:[provideRouter([]),{provide:WorkspaceService,useValue:api}]});
    const i18n=TestBed.inject(I18nService);const original=i18n.language();
    try{
      i18n.setLanguage('en');
      const fixture=TestBed.createComponent(OperationsComponent);fixture.detectChanges();await fixture.componentInstance.refresh();fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Low filament stock');
      const requests=api.diagnostics.mock.calls.length;
      i18n.setLanguage('de');fixture.detectChanges();
      const text=fixture.nativeElement.textContent as string;
      expect(text).toContain('Betriebsbereit');expect(text).toContain('Datei-Upload');expect(text).toContain('Druck pausieren');
      expect(text).toContain('Ergebnis unklar');expect(text).toContain('Niedriger Filamentbestand');
      expect(text).toContain('Spule #1234 hat noch 1,25 kg (Schwellwert 2 kg).');
      expect(text).toContain('Prüfe den tatsächlichen Materialverbrauch für Druckauftrag #1234.');
      expect(text).toContain('Drucker #1 konnte bei mindestens drei aufeinanderfolgenden Abfragen nicht erreicht werden.');
      expect(text).toContain('1,5 MiB');expect(text).toContain('Auftrag #1234');
      expect(text).toContain('Workshop');expect(text).toContain('Connection timed out');
      expect(text).not.toContain('Low filament stock');expect(text).not.toContain('Job #');
      expect(api.diagnostics).toHaveBeenCalledTimes(requests);
      const link=[...fixture.nativeElement.querySelectorAll('a')].find((anchor)=>anchor.textContent.includes('Vorgang prüfen'));
      expect(link?.getAttribute('href')).toContain('/printers?job=1234');
      i18n.setLanguage('en');fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Review actual material usage for print job #1234.');
      expect(fixture.nativeElement.textContent).toContain('1.5 MiB');
    }finally{i18n.setLanguage(original);}
  });
});
