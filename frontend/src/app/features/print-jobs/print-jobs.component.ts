import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, ManagedUser } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { PrintJob, Printer, PrinterInput, PrinterCapabilities, SliceProfiles, WorkspaceService, JobReadiness, FileInspection } from '../../workspace.service';
import { grams } from '../../models';

@Component({standalone:true,imports:[FormsModule],templateUrl:'../../jobs.html'})
export class JobsComponent implements OnInit {
  readonly api=inject(WorkspaceService); readonly data=inject(InventoryService);
  readonly auth=inject(AuthService); readonly notice=inject(NoticeService);
  readonly printers=signal<Printer[]>([]);readonly jobs=signal<PrintJob[]>([]);
  readonly busy=signal(false);
  readonly readiness=signal<Record<number,JobReadiness>>({});
  readonly inspection=signal<FileInspection|null>(null);
  plateIndex=0; firstTool=0;readonly error=signal('');readonly grams=grams;
  printerId=0;spoolId=0;fileName='';estimatedG:number|null=null;upload:File|null=null;note='';
  readonly slicer=signal<SliceProfiles>({enabled:false,profiles:[]});
  readonly capabilities=signal<PrinterCapabilities>({write_enabled:false,max_upload_bytes:0});
  readonly extraMaterials=signal<{tool:number;spool_id:number;estimated_g:number|null}[]>([]);
  stlFile:File|null=null; sliceProfile='';
  readonly clearFor=signal<number|null>(null);clearReason='';
  async ngOnInit(){await this.refresh();}
  async refresh(){
    try{const [printers,jobs]=await Promise.all([this.api.printers(),this.api.jobs()]);
      this.printers.set(printers);this.jobs.set(jobs);
      if(this.auth.isAdmin()){
        const [caps,profiles]=await Promise.all([this.api.printerCapabilities(),this.api.slicerProfiles()]);
        this.capabilities.set(caps);this.slicer.set(profiles);
        if(!this.sliceProfile || !profiles.profiles.includes(this.sliceProfile)){
          this.sliceProfile=profiles.profiles[0] || '';
        }
      }
      if(!this.printerId)this.printerId=printers.find(p=>p.enabled)?.id || 0;
      if(!this.spoolId)this.spoolId=this.data.spools().find(s=>s.remaining_g>0)?.id || 0;
    }catch(error){this.error.set(apiError(error));}
  }
  choose(event:Event){
    const f=(event.target as HTMLInputElement).files?.[0] || null;
    this.upload=f;if(f)this.fileName=f.name;
    this.inspection.set(null);this.firstTool=0;
  }
  addMaterial():void {
    const materials=this.extraMaterials();
    const used=new Set([this.firstTool,...materials.map(item=>item.tool)]);
    const tool=Array.from({length:16},(_,i)=>i).find(i=>!used.has(i)) ?? 16;
    if(tool<=15 && materials.length<7){
      this.extraMaterials.set([...materials, {tool,
        spool_id:0,
        estimated_g:null}]);
    }
  }
  removeMaterial(index:number):void {
    this.extraMaterials.update(items=>items.filter((_,i)=>i!==index));
  }
  async inspect():Promise<void> {
    if(!this.upload||this.busy())return;
    this.busy.set(true);this.error.set('');this.inspection.set(null);
    try{
      const result=await this.api.inspectFile(this.upload);
      this.inspection.set(result);this.plateIndex=0;
      if(result.needs_manual_estimate){
        this.notice.show('No reliable slicer material weights found. Enter an estimate manually.');
      }
    }catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  applyInspection():void {
    const preview=this.inspection();
    const plate=preview?.plates[this.plateIndex];
    if(!plate?.materials.length)return;
    const items=[...plate.materials].sort((a,b)=>a.tool-b.tool);
    this.firstTool=items[0].tool;this.estimatedG=items[0].estimated_g;
    this.spoolId=0;  // operator must select the actual physical roll
    this.extraMaterials.set(items.slice(1).map(m=>({...m,spool_id:0})));
    // 3MF and multi-tool files are inspection-only; no implicit printer upload.
    if(items.length>1 || this.upload?.name.toLowerCase().endsWith('.3mf'))this.upload=null;
    this.notice.show('Weights loaded. Explicitly select each physical spool and confirm before saving.');
  }
  async checkReadiness(job:PrintJob):Promise<void>{
    this.busy.set(true);this.error.set('');
    try{const r=await this.api.readiness(job.id);
      this.readiness.update(old=>({...old,[job.id]:r}));}
    catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  async setReservation(job:PrintJob,enabled:boolean):Promise<void>{
    this.busy.set(true);this.error.set('');
    try{
      const r=enabled?await this.api.reserve(job.id):await this.api.release(job.id);
      this.readiness.update(old=>({...old,[job.id]:r}));
      this.notice.show(enabled?'Material reserved (advisory; not consumed).':'Reservation released.');
    }catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  chooseStl(event:Event):void {
    this.stlFile=(event.target as HTMLInputElement).files?.[0] || null;
  }
  async sliceModel():Promise<void>{
    if(!this.stlFile || !this.sliceProfile || this.busy())return;
    if(!this.stlFile.name.toLowerCase().endsWith('.stl')){
      this.error.set('Only STL models can be sliced.');return;
    }
    this.busy.set(true);this.error.set('');
    try{
      const result=await this.api.sliceStl(this.stlFile,this.sliceProfile);
      const url=URL.createObjectURL(result.content);
      const anchor=document.createElement('a');
      anchor.href=url;
      anchor.download=this.stlFile.name.replace(/\.stl$/i,'.gcode');
      document.body.appendChild(anchor);anchor.click();anchor.remove();
      window.setTimeout(()=>URL.revokeObjectURL(url),30000);
      this.notice.show('G-code generated'+(result.estimated?' · estimated '+result.estimated+' g':'')+
                       '. Inspect the G-code before printing.');
    }catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  async uploadPending(job:PrintJob,event:Event):Promise<void>{
    const input=event.target as HTMLInputElement;
    const file=input.files?.[0] || null;
    input.value='';
    if(!file)return;
    if(file.name!==job.file_name){
      this.error.set('The selected file name must exactly match the registered job filename.');
      return;
    }
    if(!window.confirm('Upload '+file.name+' to '+job.printer_name+'? This transfers executable printer instructions.'))return;
    this.busy.set(true);this.error.set('');
    try{await this.api.uploadJob(job.id,file);this.notice.show('File transferred. Print not started.');}
    catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  async clearStart(job:PrintJob):Promise<void>{
    if(!this.auth.isAdmin()||this.clearFor()!==job.id||this.clearReason.trim().length<10){
      this.error.set('Record how you physically verified that the printer did not start.');return;
    }
    if(!window.confirm('Confirm the printer did NOT start this job? Clearing allows another start request.'))return;
    this.busy.set(true);this.error.set('');
    try{
      const commands=await this.api.jobCommands(job.id);
      const last=commands.find(item=>item.action==='start');
      if(!last||!['unknown','acknowledged'].includes(last.state))
        throw new Error('There is no unconfirmed start command to clear.');
      await this.api.clearPrinterCommand(last.id,this.clearReason.trim());
      this.clearReason='';this.clearFor.set(null);await this.refresh();
      this.notice.show('Command cleared after physical verification.');
    }catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
  async start(job:PrintJob):Promise<void>{
    if(!window.confirm('Start '+job.file_name+' on '+job.printer_name+'? The printer will physically begin printing.'))return;
    this.busy.set(true);this.error.set('');
    try{await this.api.startJob(job.id);await this.refresh();this.notice.show('Print start acknowledged. Controller tracking will verify progress.');}
    catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  async submit(){
    if(this.busy()||!this.auth.canEdit())return;
    this.busy.set(true);this.error.set('');
    try {
      if(this.extraMaterials().length){
        if(this.upload)throw new Error('For multi-material jobs, enter the filename and explicit weights without importing G-code metadata.');
        if(!this.estimatedG || this.estimatedG<=0 || this.extraMaterials().some(m=>!m.estimated_g || m.estimated_g<=0))
          throw new Error('Every mapped tool requires a positive estimated weight.');
        await this.api.createMultiJob({printer_id:this.printerId,file_name:this.fileName,note:this.note,
          materials:[{tool:this.firstTool,spool_id:this.spoolId,estimated_g:this.estimatedG},
            ...this.extraMaterials().map(m=>({tool:Number(m.tool),spool_id:m.spool_id,
                                            estimated_g:Number(m.estimated_g)}))]});
      }else if(this.upload){
        await this.api.importJob(this.upload,this.printerId,this.spoolId,this.estimatedG);
      }else{
        if(!this.estimatedG)throw new Error('Enter a positive estimated weight in grams.');
        await this.api.createJob({printer_id:this.printerId,spool_id:this.spoolId,file_name:this.fileName,
          estimated_g:this.estimatedG,note:this.note});
      }
      this.notice.show('Print-job mapping registered. Transfer a file separately if needed.');
      this.fileName='';this.upload=null;this.estimatedG=null;this.note='';this.firstTool=0;
      this.extraMaterials.set([]);this.inspection.set(null);
      await this.refresh();
    }catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
  async poll(printerId:number){
    this.busy.set(true);this.error.set('');
    try {
      const state=await this.api.poll(printerId);
      this.notice.show('Printer: '+state.state+' · '+state.updated_jobs+' job(s) updated.');
      await this.refresh();await this.data.load();
    }catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
  async resolve(job:PrintJob,action:'debit'|'discard'){
    if(!window.confirm(action==='debit'
      ?'Confirm this print finished successfully and deduct '+this.grams(job.estimated_g)+' from the selected spool?'
      :'Discard tracking for this print job without deducting material?'))return;
    this.busy.set(true);this.error.set('');
    try{
      await this.api.resolveJob(job.id,action);await this.refresh();await this.data.load();
      this.notice.show(action==='debit'?'Confirmed consumption recorded.':'Job tracking discarded.');
    }catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
  async cancel(job:PrintJob){
    if(!window.confirm('Cancel tracking this job? The printer itself will not be stopped.'))return;
    this.busy.set(true);
    try{await this.api.cancelJob(job.id);await this.refresh();this.notice.show('Tracking cancelled; printer was not changed.');}
    catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
}

