import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, ManagedUser } from './auth.service';
import { InventoryService, apiError } from './inventory.service';
import { NoticeService } from './dialog.service';
import { PrintJob, Printer, PrinterInput, WorkspaceService } from './workspace.service';
import { grams } from './models';

@Component({standalone:true,imports:[FormsModule],templateUrl:'./jobs.html'})
export class JobsComponent implements OnInit {
  readonly api=inject(WorkspaceService); readonly data=inject(InventoryService);
  readonly auth=inject(AuthService); readonly notice=inject(NoticeService);
  readonly printers=signal<Printer[]>([]);readonly jobs=signal<PrintJob[]>([]);
  readonly busy=signal(false);readonly error=signal('');readonly grams=grams;
  printerId=0;spoolId=0;fileName='';estimatedG:number|null=null;upload:File|null=null;note='';
  async ngOnInit(){await this.refresh();}
  async refresh(){
    try{const [printers,jobs]=await Promise.all([this.api.printers(),this.api.jobs()]);
      this.printers.set(printers);this.jobs.set(jobs);
      if(!this.printerId)this.printerId=printers.find(p=>p.enabled)?.id || 0;
      if(!this.spoolId)this.spoolId=this.data.spools().find(s=>s.remaining_g>0)?.id || 0;
    }catch(error){this.error.set(apiError(error));}
  }
  choose(event:Event){
    const f=(event.target as HTMLInputElement).files?.[0] || null;
    this.upload=f;if(f)this.fileName=f.name;
  }
  async submit(){
    if(this.busy()||!this.auth.canEdit())return;
    this.busy.set(true);this.error.set('');
    try {
      if(this.upload)await this.api.importJob(this.upload,this.printerId,this.spoolId,this.estimatedG);
      else {
        if(!this.estimatedG)throw new Error('Enter a positive estimated weight in grams.');
        await this.api.createJob({printer_id:this.printerId,spool_id:this.spoolId,file_name:this.fileName,
          estimated_g:this.estimatedG,note:this.note});
      }
      this.notice.show('Print-job mapping registered. The file must already be present on the printer.');
      this.fileName='';this.upload=null;this.estimatedG=null;this.note='';
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
  async ngOnInit(){await this.refresh();}
  async refresh(){try{this.printers.set(await this.api.printers());}catch(e){this.error.set(apiError(e));}}
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
  async reset(user:ManagedUser){
    const password=window.prompt('New password (at least 14 characters) for '+user.username+':');
    if(password===null)return;
    if(password.length<14){this.error.set('Password must be at least 14 characters.');return;}
    await this.update(user,{password});
  }
}
