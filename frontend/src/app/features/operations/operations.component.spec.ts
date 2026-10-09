import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';
import { OperationsComponent } from './operations.component';
import { WorkspaceService } from '../../workspace.service';
import { ApiDiagnostics } from '../../core/api/generated-contracts';

describe('operational diagnostics',()=>{
  it('distinguishes a running observation service from an offline printer and exposes uncertain uploads',async()=>{
    const state:ApiDiagnostics={version:'0.10.0',schema_version:10,status:'ok',jobs:[],uncertain_commands:0,commands:[],
      poller:{status:'running',interval_seconds:15,started_at:null,last_cycle_at:'2026-10-01T12:00:00Z',last_success_at:null,last_heartbeat_at:null,last_error:null,lease_held:true,lease_expires_at:null},
      printers:[{id:1,name:'Workshop',enabled:true,active_jobs:1,last_attempt_at:null,last_success_at:null,consecutive_failures:2,last_error:'Connection timed out',observation_age_seconds:90,freshness:'stale'}],
      backup:{status:'never',last_success_at:null,last_size_bytes:null,last_error:null},storage:{database_bytes:1000,wal_bytes:0,free_bytes:1000000000,reserve_bytes:1000000,low_space:false},
      restore:{last_restored_at:null,requires_token_reissue:false},slicer:{enabled:false,configured:false},material_mapping_warnings:[],
      printer_operations:[{printer_id:1,printer_name:'Workshop',operation_id:'op-1',job_id:1,kind:'upload',state:'unknown',created_at:'2026-10-01T12:00:00Z',updated_at:'2026-10-01T12:00:00Z'}]};
    TestBed.configureTestingModule({providers:[provideRouter([]),{provide:WorkspaceService,useValue:{diagnostics:vi.fn().mockResolvedValue(state),alerts:vi.fn().mockResolvedValue({schema_version:'1',instance_epoch:'test',generated_at:'2026-10-01T12:00:00Z',truncated:false,alerts:[]})}}]});
    const fixture=TestBed.createComponent(OperationsComponent);fixture.detectChanges();await fixture.componentInstance.refresh();fixture.detectChanges();const text=fixture.nativeElement.textContent as string;
    expect(text).toContain('Operating');expect(text).toContain('Running');expect(text).toContain('Out of date');expect(text).toContain('File upload');expect(text).toContain('Outcome uncertain');
    const link=[...fixture.nativeElement.querySelectorAll('a')].find((anchor)=>anchor.textContent.includes('Review operation'));
    expect(link?.getAttribute('href')).toContain('/printers');
  });
});
