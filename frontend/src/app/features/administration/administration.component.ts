import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, ManagedUser } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { PrintJob, Printer, PrinterInput, PrinterCapabilities, SliceProfiles, WorkspaceService } from '../../workspace.service';
import { grams } from '../../models';

@Component({standalone:true,imports:[FormsModule],templateUrl:'../../users.html'})
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


