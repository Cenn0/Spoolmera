import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, ManagedUser } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { PrintJob, Printer, PrinterInput, PrinterCapabilities, SliceProfiles, WorkspaceService, PrinterSlot } from '../../workspace.service';
import { grams } from '../../models';

@Component({standalone:true,imports:[FormsModule],templateUrl:'../../printers.html'})
export class PrintersComponent implements OnInit {
  readonly api=inject(WorkspaceService);readonly auth=inject(AuthService);readonly notice=inject(NoticeService);
  readonly printers=signal<Printer[]>([]);readonly error=signal('');readonly busy=signal(false);
  readonly data=inject(InventoryService);
  readonly slots=signal<Record<number,PrinterSlot[]>>({});
  printerSelection=0;slotTool=0;slotSpool=0;
  model:PrinterInput={name:'',kind:'moonraker',base_url:'',token_env:'',enabled:true};
  readonly capabilities=signal<PrinterCapabilities>({write_enabled:false,max_upload_bytes:0});
  async ngOnInit(){await this.refresh();}
  async refresh(){try{
    const printers=await this.api.printers();
    const caps=this.auth.isAdmin()?await this.api.printerCapabilities():{write_enabled:false,max_upload_bytes:0};
    this.printers.set(printers);this.capabilities.set(caps);
    if(!printers.some(p=>p.id===this.printerSelection))this.printerSelection=printers[0]?.id || 0;
    const results=await Promise.all(printers.map(async p=>[p.id,await this.api.printerSlots(p.id)] as const));
    this.slots.set(Object.fromEntries(results));
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
  async assignSlot():Promise<void>{
    if(!this.auth.canEdit()||!this.printerSelection||!this.slotSpool)return;
    this.busy.set(true);this.error.set('');
    try{await this.api.assignSlot(this.printerSelection,this.slotTool,this.slotSpool);
      await this.refresh();this.notice.show('Advisory spool slot recorded. Verify physical loading.');}
    catch(e){this.error.set(apiError(e));}finally{this.busy.set(false);}
  }
  async unloadSlot(tool:number):Promise<void>{
    this.busy.set(true);this.error.set('');
    try{await this.api.unloadSlot(this.printerSelection,tool);
      await this.refresh();this.notice.show('Slot mapping removed. No physical unload command was sent.');}
    catch(e){this.error.set(apiError(e));}finally{this.busy.set(false);}
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
