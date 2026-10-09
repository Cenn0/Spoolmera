import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService, AutomationToken, ScaleMeasurement } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, dateText, grams, stockPercent } from '../../models';

@Component({
  standalone: true,
  imports:[FormsModule],
  templateUrl:'../../integrations.html'
})
export class IntegrationsComponent implements OnInit {
  private readonly data = inject(InventoryService);
  private readonly notices = inject(NoticeService);
  private readonly workspace = inject(WorkspaceService);
  readonly printers = signal<Printer[]>([]);
  readonly auth = inject(AuthService);
  readonly cloudEvents = signal<CloudReceipt[]>([]);
  readonly scales=signal<ScaleMeasurement[]>([]);
  scaleNote='Verified physical scale measurement and correct spool identification.';
  readonly scaleBusy=signal(false);
  async reviewScale(item:ScaleMeasurement,action:'approve'|'discard'):Promise<void>{
    if(this.scaleBusy()||!this.auth.canEdit()||this.scaleNote.trim().length<10)return;
    if(action==='approve' && !window.confirm(
      'Apply scale measurement for '+item.brand+' '+item.product_name+'? This may change physical stock.'))return;
    this.scaleBusy.set(true);
    try{
      await this.workspace.reviewScale(item.id,action,this.scaleNote.trim());
      this.scales.set(await this.workspace.scaleMeasurements());
      await this.data.load();
      this.notices.show(action==='approve'?'Measured stock adjustment recorded.':'Scale report discarded.');
    }catch(e){this.notices.show(apiError(e),true);}
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
    if(this.tokenBusy()||!window.confirm('Revoke this machine token immediately?'))return;
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
  async ngOnInit(): Promise<void> {
    try {
      const [capabilities, printers] = await Promise.all([
        this.data.capabilities(), this.workspace.printers(),
      ]);
      this.capabilities.set(capabilities);
      this.printers.set(printers);
      if(this.auth.canEdit())this.scales.set(await this.workspace.scaleMeasurements());
      if(this.auth.isAdmin()){
        this.cloudEvents.set(await this.workspace.cloudEvents());
        this.tokens.set(await this.workspace.automationTokens());
      }
    }
    catch (error) { this.notices.show('Unable to load integration capabilities: ' + apiError(error),true); }
  }
}
