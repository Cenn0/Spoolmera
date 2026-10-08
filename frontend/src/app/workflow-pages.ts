import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, ManagedUser } from './auth.service';
import { InventoryService, apiError } from './inventory.service';
import { NoticeService } from './dialog.service';
import { PrintJob, Printer, PrinterInput, PrinterCapabilities, SliceProfiles, WorkspaceService } from './workspace.service';
import { grams } from './models';

@Component({standalone:true,imports:[FormsModule],templateUrl:'./jobs.html'})
export class JobsComponent implements OnInit {
  readonly api=inject(WorkspaceService); readonly data=inject(InventoryService);
  readonly auth=inject(AuthService); readonly notice=inject(NoticeService);
  readonly printers=signal<Printer[]>([]);readonly jobs=signal<PrintJob[]>([]);
  readonly busy=signal(false);readonly error=signal('');readonly grams=grams;
  printerId=0;spoolId=0;fileName='';estimatedG:number|null=null;upload:File|null=null;note='';
  readonly slicer=signal<SliceProfiles>({enabled:false,profiles:[]});
  readonly capabilities=signal<PrinterCapabilities>({write_enabled:false,max_upload_bytes:0});
  readonly extraMaterials=signal<{tool:number;spool_id:number;estimated_g:number|null}[]>([]);
  stlFile:File|null=null; sliceProfile='';
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
  }
  addMaterial():void {
    const materials=this.extraMaterials();
    const tool=materials.length+1;
    if(tool<=15 && materials.length<7){
      this.extraMaterials.set([...materials, {tool,
        spool_id:this.data.spools().find(s=>s.remaining_g>0)?.id || 0,
        estimated_g:null}]);
    }
  }
  removeMaterial(index:number):void {
    this.extraMaterials.update(items=>items.filter((_,i)=>i!==index));
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
  async start(job:PrintJob):Promise<void>{
    if(!window.confirm('Start '+job.file_name+' on '+job.printer_name+'? The printer will physically begin printing.'))return;
    this.busy.set(true);this.error.set('');
    try{await this.api.startJob(job.id);this.notice.show('Print start requested. Controller tracking will verify progress.');}
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
          materials:[{tool:0,spool_id:this.spoolId,estimated_g:this.estimatedG},
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
      this.fileName='';this.upload=null;this.estimatedG=null;this.note='';this.extraMaterials.set([]);
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

@Component({standalone:true,imports:[FormsModule],templateUrl:'./printers.html'})
export class PrintersComponent implements OnInit {
  readonly api=inject(WorkspaceService);readonly auth=inject(AuthService);readonly notice=inject(NoticeService);
  readonly printers=signal<Printer[]>([]);readonly error=signal('');readonly busy=signal(false);
  model:PrinterInput={name:'',kind:'moonraker',base_url:'',token_env:'',enabled:true};
  readonly capabilities=signal<PrinterCapabilities>({write_enabled:false,max_upload_bytes:0});
  async ngOnInit(){await this.refresh();}
  async refresh(){try{
    const [printers,caps]=await Promise.all([this.api.printers(),this.api.printerCapabilities()]);
    this.printers.set(printers);this.capabilities.set(caps);
  }catch(e){this.error.set(apiError(e));}}
  async create(){
    if(this.busy())return;this.busy.set(true);this.error.set('');
    try {
      await this.api.addPrinter({...this.model});
      this.model={name:'',kind:'moonraker',base_url:'',token_env:'',enabled:true};
      await this.refresh();this.notice.show('Printer registered. Use Test connection to verify access.');
    }catch(e){this.error.set(apiError(e));}finally{this.busy.set(false);}
  }
  async probe(p:Printer){
    this.busy.set(true);this.error.set('');
    try{
      const r=await this.api.probe(p.id);
      this.notice.show(p.name+' reports '+r.state+(r.filename?' · '+r.filename:''));
    }catch(e){this.error.set(apiError(e));}finally{this.busy.set(false);}
  }
  async control(p:Printer,action:'pause'|'resume'|'cancel'):Promise<void>{
    if(!window.confirm(action+' the physical print on '+p.name+'?'))return;
    this.busy.set(true);this.error.set('');
    try{
      await this.api.controlPrinter(p.id,action);
      this.notice.show('Controller accepted '+action+'. Verify the physical printer.');
    }catch(e){this.error.set(apiError(e));}finally{this.busy.set(false);}
  }
  async toggle(p:Printer){
    this.busy.set(true);this.error.set('');
    try{
      await this.api.updatePrinter(p.id,{name:p.name,kind:p.kind,base_url:p.base_url,
        token_env:p.token_env,enabled:!p.enabled});
      await this.refresh();
      this.notice.show('Printer configuration updated.');
    }catch(e){this.error.set(apiError(e));}finally{this.busy.set(false);}
  }
}
@Component({standalone:true,imports:[FormsModule],templateUrl:'./users.html'})
export class UsersComponent implements OnInit {
  readonly api=inject(WorkspaceService);readonly auth=inject(AuthService);readonly notice=inject(NoticeService);
  readonly users=signal<ManagedUser[]>([]);readonly error=signal('');readonly busy=signal(false);
  username='';password='';role:'viewer'|'editor'|'admin'='viewer';
  readonly resetFor=signal<number|null>(null);
  resetSecret='';
  async ngOnInit(){await this.refresh();}
  async refresh(){try{this.users.set(await this.api.users());}catch(e){this.error.set(apiError(e));}}
  async create(){
    this.busy.set(true);this.error.set('');
    try{
      await this.api.createUser({username:this.username,password:this.password,role:this.role});
      this.username='';this.password='';this.role='viewer';await this.refresh();
      this.notice.show('User account created.');
    }catch(e){this.error.set(apiError(e));}finally{this.busy.set(false);}
  }
  async update(user:ManagedUser,changes:{role?:string;enabled?:boolean;password?:string}){
    this.busy.set(true);this.error.set('');
    try{await this.api.updateUser(user.id,changes);await this.refresh();this.notice.show('User updated. Existing sessions have been revoked.');}
    catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  openReset(user:ManagedUser):void {
    this.error.set('');
    this.resetSecret='';
    this.resetFor.set(this.resetFor()===user.id?null:user.id);
  }
  async reset(user:ManagedUser){
    if(this.resetFor()!==user.id || this.resetSecret.length<14) {
      this.error.set('Provide a password of at least 14 characters.');
      return;
    }
    await this.update(user,{password:this.resetSecret});
    if(!this.error()) {this.resetSecret='';this.resetFor.set(null);}
  }
}


@Component({standalone:true,imports:[FormsModule],template: `
<section class="page-head"><div><span class="eyebrow">PERSONAL SECURITY</span><h1>My <em>account.</em></h1>
  <p>Review your access role and change your password.</p></div></section>
@if(error()){<p class="form-error" role="alert">{{error()}}</p>}
<section class="panel workflow-panel">
  <div class="panel-heading"><div><span class="eyebrow">CURRENT ACCOUNT</span><h2>{{auth.user()?.username}} · {{auth.user()?.role}}</h2></div></div>
  <form class="workflow-form" #passwordForm="ngForm" (ngSubmit)="submit()">
    <div class="form-grid">
      <label>Current password<input name="old" type="password" [(ngModel)]="oldPassword" required autocomplete="current-password"></label>
      <label>New password (minimum 14 characters)<input name="new" type="password" [(ngModel)]="newPassword" required minlength="14" maxlength="128" autocomplete="new-password"></label>
      <label>Confirm new password<input name="confirm" type="password" [(ngModel)]="confirmPassword" required minlength="14" autocomplete="new-password"></label>
    </div>
    <p class="helper">Changing your password invalidates other active sessions.</p>
    <button class="btn primary" type="submit" [disabled]="busy()||passwordForm.invalid">Update password</button>
  </form>
</section>
`})
export class AccountComponent {
  readonly auth=inject(AuthService);readonly notice=inject(NoticeService);
  readonly busy=signal(false);readonly error=signal('');
  oldPassword='';newPassword='';confirmPassword='';
  async submit():Promise<void>{
    if(this.newPassword!==this.confirmPassword){this.error.set('New passwords must match.');return;}
    this.busy.set(true);this.error.set('');
    try{
      await this.auth.password(this.oldPassword,this.newPassword);
      this.oldPassword='';this.newPassword='';this.confirmPassword='';
      this.notice.show('Password changed. Other sessions have been revoked.');
    }catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
}
