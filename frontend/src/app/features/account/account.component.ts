import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, ManagedUser } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { PrintJob, Printer, PrinterInput, PrinterCapabilities, SliceProfiles, WorkspaceService } from '../../workspace.service';
import { grams } from '../../models';

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
