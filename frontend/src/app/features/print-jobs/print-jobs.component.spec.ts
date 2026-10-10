import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { JobsComponent } from './print-jobs.component';
import { AuthService } from '../../auth.service';
import { InventoryService } from '../../inventory.service';
import { WorkspaceService, FileInspection } from '../../workspace.service';
import { authMock, deferred, inventoryMock, job, workspaceMock } from '../../testing/fixtures';

function choose(component:JobsComponent,file:File){const input={files:[file],value:'selected'};component.choose({target:input} as unknown as Event);return input;}
describe('print-job intent and uncertain operations',()=>{
  let component:JobsComponent,api:ReturnType<typeof workspaceMock>,inventory:ReturnType<typeof inventoryMock>;
  beforeEach(()=>{
    api=workspaceMock();inventory=inventoryMock();
    TestBed.configureTestingModule({providers:[provideRouter([]),{provide:ActivatedRoute,useValue:{queryParamMap:of(convertToParamMap({}))}},
      {provide:WorkspaceService,useValue:api},{provide:InventoryService,useValue:inventory},{provide:AuthService,useValue:authMock()}]});
    component=TestBed.createComponent(JobsComponent).componentInstance;
  });
  it('preserves a sole T3 from inspection through the canonical material-list API',async()=>{
    const file=new File([';filament'],'part.gcode');choose(component,file);
    api.inspectFile.mockResolvedValue({source:'prusaslicer',file_stored:false,verified:false,needs_manual_estimate:false,plates:[{plate:1,materials:[{tool:3,estimated_g:37}]}]});
    await component.inspect();component.applyInspection();
    expect(component.firstTool).toBe(3);expect(component.spoolId).toBe(0);
    component.spoolId=1;component.printerId=1;await component.submit();
    expect(api.createMultiJob).toHaveBeenCalledWith({printer_id:1,file_name:'part.gcode',note:'',auto_account_bambu:false,materials:[{tool:3,spool_id:1,estimated_g:37}]});
  });
  it('persists Bambu automatic estimated usage only when explicitly enabled',async()=>{
    component.printers.set([{id:7,name:'Bambu',kind:'bambu',base_url:'',token_env:'',serial:'',enabled:1,created_at:''}]);
    component.printerId=7;component.fileName='part.3mf';component.spoolId=1;component.estimatedG=45;
    component.autoAccountBambu=true;await component.submit();
    expect(api.createMultiJob).toHaveBeenCalledWith(expect.objectContaining({
      printer_id:7,auto_account_bambu:true,materials:[{tool:0,spool_id:1,estimated_g:45}]
    }));
    component.printerId=1;component.fileName='part.gcode';component.estimatedG=55;
    await component.submit();
    expect(api.createMultiJob.mock.calls[1][0].auto_account_bambu).toBe(false);
  });
  it('allows explicit T0 after a nonzero primary tool without renumbering either tool',async()=>{
    component.firstTool=3;component.estimatedG=37;component.spoolId=1;component.printerId=1;component.fileName='two.gcode';
    component.extraMaterials.set([{tool:0,spool_id:2,estimated_g:8}]);await component.submit();
    expect(api.createMultiJob.mock.calls[0][0].materials).toEqual([{tool:3,spool_id:1,estimated_g:37},{tool:0,spool_id:2,estimated_g:8}]);
  });
  it('rejects duplicate tools before contacting the server',async()=>{
    component.firstTool=3;component.estimatedG=37;component.spoolId=1;component.printerId=1;component.fileName='two.gcode';
    component.extraMaterials.set([{tool:3,spool_id:2,estimated_g:8}]);await component.submit();expect(api.createMultiJob).not.toHaveBeenCalled();
    expect(component.error()).toContain('unique');
  });
  it('ignores late metadata for file A after selecting file B and clears the native file input',async()=>{
    const late=deferred<FileInspection>();api.inspectFile.mockReturnValue(late.promise);
    const input=choose(component,new File(['A'],'a.gcode'));expect(input.value).toBe('');
    const reading=component.inspect();choose(component,new File(['B'],'b.gcode'));
    late.resolve({source:'test',file_stored:false,verified:false,needs_manual_estimate:false,plates:[{plate:1,materials:[{tool:3,estimated_g:37}]}]});await reading;
    expect(component.inspection()).toBeNull();expect(component.estimatedG).toBeNull();expect(component.fileName).toBe('b.gcode');
  });
  it('refreshes after a failed start and blocks retry from the new unknown command state',async()=>{
    vi.spyOn(window,'confirm').mockReturnValue(true);api.startJob.mockRejectedValue(new Error('Connection lost'));
    api.jobs.mockResolvedValue([job({start_command_state:'unknown'})]);await component.start(job());
    expect(api.jobs).toHaveBeenCalled();expect(inventory.load).toHaveBeenCalled();expect(component.error()).toContain('Connection lost');
    await component.start(component.jobs()[0]);expect(api.startJob).toHaveBeenCalledTimes(1);
  });
  it('keeps a local unknown-start block when reloading the server also fails',async()=>{
    vi.spyOn(window,'confirm').mockReturnValue(true);api.startJob.mockRejectedValue(new Error('Timeout'));api.jobs.mockRejectedValue(new Error('Offline'));
    await component.start(job());expect(component.uncertainStarts()).toContain(1);await component.start(job());expect(api.startJob).toHaveBeenCalledTimes(1);
  });
  it('releases a confirmed start for a stopped job only after a physical-idle check',async()=>{
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    const clear=vi.fn().mockResolvedValue(undefined);
    Object.assign(api,{jobCommands:vi.fn().mockResolvedValue([{id:'command-1',action:'start',state:'confirmed'}]),clearPrinterCommand:clear});
    component.clearFor.set(1);component.clearReason='Printer checked idle after a partial print';
    await component.clearStart(job({status:'cancelled',start_command_state:'confirmed'}));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('printer is idle'));
    expect(clear).toHaveBeenCalledWith('command-1','Printer checked idle after a partial print');
    expect(component.clearFor()).toBeNull();
  });
  it('invalidates loaded-slot suggestions when the selected printer changes',async()=>{
    const late=deferred<[]>();api.printerSlots.mockReturnValue(late.promise);component.printerId=1;component.estimatedG=37;
    const reading=component.suggestLoadedSpools();component.printerId=2;late.resolve([]);await reading;expect(component.slotSuggestions()).toEqual([]);
  });
});
