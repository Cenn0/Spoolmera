import { Component, OnInit, OnDestroy, HostListener, computed, inject, signal } from '@angular/core';
import { RequestOwner } from '../../core/request-owner';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService, AutomationToken, ScaleMeasurement } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities } from '../../models';

@Component({
  standalone: true,
  imports:[FormsModule,RouterLink,TranslatePipe],
  templateUrl:'./integrations.component.html',
  styleUrl:'./integrations.component.css'
})
export class IntegrationsComponent implements OnInit, OnDestroy {
  readonly i18n=inject(I18nService);
  private readonly data = inject(InventoryService);
  private readonly notices = inject(NoticeService);
  private readonly workspace = inject(WorkspaceService);
  readonly printers = signal<Printer[]>([]);
  readonly auth = inject(AuthService);
  readonly cloudEvents = signal<CloudReceipt[]>([]);
  readonly scales=signal<ScaleMeasurement[]>([]);
  scaleNote='';
  readonly dateText=(value:string|null|undefined)=>this.i18n.dateText(value);readonly loading=signal(false);readonly error=signal('');
  private readonly requests=new RequestOwner();
  ngOnDestroy():void{this.requests.invalidate();this.issuedSecret.set('');}
  @HostListener('window:focus') onFocus():void{if(!this.scaleBusy()&&!this.tokenBusy())void this.refresh();}
  readonly scaleBusy=signal(false);
  async reviewScale(item:ScaleMeasurement,action:'approve'|'discard'):Promise<void>{
    if(this.scaleBusy()||!this.auth.canEdit()||this.scaleNote.trim().length<10)return;
    if(action==='approve'&&(item.stale||item.blocking_job_ids.length)){this.notices.show('This reading is outdated or belongs to a job needing reconciliation. Refresh and review the job first.',true);return;}
    if(action==='approve' && !window.confirm(this.i18n.t(
      'Apply scale measurement for {spool}? This may change physical stock.',{spool:item.brand+' '+item.product_name})))return;
    this.scaleBusy.set(true);
    try{
      await this.workspace.reviewScale(item.id,action,this.scaleNote.trim());
      this.scales.set(await this.workspace.scaleMeasurements());this.scaleNote='';
      await this.data.load();
      this.notices.show(action==='approve'?'Measured stock adjustment recorded.':'Scale report discarded.');
    }catch(e){this.notices.show(apiError(e),true);await this.refresh();}
    finally{this.scaleBusy.set(false);}
  }
  readonly tokens=signal<AutomationToken[]>([]);
  readonly issuedSecret=signal('');
  readonly tokenBusy=signal(false);
  readonly tokenError=signal('');
  tokenLabel='';tokenScope:'inventory_read'|'events_read'='inventory_read';
  async createToken():Promise<void>{
    if(!this.auth.isAdmin()||this.tokenBusy())return;
    this.tokenBusy.set(true);this.tokenError.set('');this.issuedSecret.set('');
    try {
      const response=await this.workspace.createAutomationToken(this.tokenLabel,this.tokenScope);
      this.issuedSecret.set(response.token);this.tokenLabel='';
      this.tokens.set(await this.workspace.automationTokens());
      this.notices.show('Automation token created. Copy its secret now; it is only shown once.');
    }catch(err){this.tokenError.set(apiError(err));}
    finally{this.tokenBusy.set(false);}
  }
  async revokeToken(id:number):Promise<void>{
    if(this.tokenBusy()||!window.confirm(this.i18n.t('Revoke this machine token immediately?')))return;
    this.tokenBusy.set(true);this.tokenError.set('');
    try{
      await this.workspace.revokeAutomationToken(id);
      this.tokens.set(await this.workspace.automationTokens());
      this.notices.show('Machine token revoked.');
    }catch(err){this.tokenError.set(apiError(err));}
    finally{this.tokenBusy.set(false);}
  }
  readonly enabledPrinters = computed(() => this.printers().filter(printer => printer.enabled).length);
  readonly capabilities = signal<Capabilities | null>(null);
  ngOnInit():void{void this.refresh();}
  async refresh():Promise<void>{
    const owner=this.requests.begin();this.loading.set(true);this.error.set('');
    try {
      const [capabilities,printers,scales,events,tokens]=await Promise.all([
        this.data.capabilities(),this.workspace.printers(),
        this.auth.canEdit()?this.workspace.scaleMeasurements():Promise.resolve([]),
        this.auth.isAdmin()?this.workspace.cloudEvents():Promise.resolve([]),
        this.auth.isAdmin()?this.workspace.automationTokens():Promise.resolve([]),
      ]);
      if(!this.requests.owns(owner))return;
      this.capabilities.set(capabilities);this.printers.set(printers);this.scales.set(scales);this.cloudEvents.set(events);this.tokens.set(tokens);
    }catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
}
