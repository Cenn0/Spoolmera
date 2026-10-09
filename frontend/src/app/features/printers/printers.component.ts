import { Component, HostListener, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { Printer, PrinterInput, PrinterCapabilities, WorkspaceService, PrinterSlot, PrinterOperation } from '../../workspace.service';
import { RequestOwner } from '../../core/request-owner';
import { grams, dateText } from '../../models';

const blankPrinter=():PrinterInput=>({name:'',kind:'moonraker',base_url:'',token_env:'',enabled:true});
@Component({standalone:true,imports:[FormsModule,RouterLink],templateUrl:'./printers.component.html'})
export class PrintersComponent implements OnInit, OnDestroy {
  readonly api=inject(WorkspaceService);readonly auth=inject(AuthService);readonly notice=inject(NoticeService);readonly data=inject(InventoryService);
  readonly printers=signal<Printer[]>([]);readonly error=signal('');readonly busy=signal(false);readonly loading=signal(false);
  readonly slots=signal<Record<number,PrinterSlot[]>>({});readonly operations=signal<Record<number,PrinterOperation[]>>({});
  readonly capabilities=signal<PrinterCapabilities>({write_enabled:false,max_upload_bytes:0});
  readonly grams=grams;readonly dateText=dateText;private readonly requests=new RequestOwner();
  printerSelection=0;slotTool=0;slotSpool=0;editingId:number|null=null;
  clearOperation:PrinterOperation|null=null;clearReason='';clearChecked=false;
  model:PrinterInput=blankPrinter();
  async ngOnInit():Promise<void>{await this.refresh();}
  ngOnDestroy():void{this.requests.invalidate();}
  @HostListener('window:focus') onFocus():void{if(!this.busy())void this.refresh();}
  async refresh():Promise<void>{
    const owner=this.requests.begin();this.loading.set(true);this.error.set('');
    try{
      const printers=await this.api.printers();
      const [caps,slots,operations]=await Promise.all([
        this.auth.isAdmin()?this.api.printerCapabilities():Promise.resolve({write_enabled:false,max_upload_bytes:0}),
        Promise.all(printers.map(async p=>[p.id,await this.api.printerSlots(p.id)] as const)),
        this.auth.canEdit()?Promise.all(printers.map(async p=>[p.id,await this.api.printerOperations(p.id)] as const)):Promise.resolve([]),
      ]);
      if(!this.requests.owns(owner))return;
      this.printers.set(printers);this.capabilities.set(caps);this.slots.set(Object.fromEntries(slots));this.operations.set(Object.fromEntries(operations));
      if(!printers.some(p=>p.id===this.printerSelection))this.printerSelection=printers[0]?.id||0;
    }catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
  edit(printer:Printer):void{
    this.editingId=printer.id;this.model={name:printer.name,kind:printer.kind,base_url:printer.base_url,token_env:printer.token_env,enabled:!!printer.enabled};
  }
  cancelEdit():void{this.editingId=null;this.model=blankPrinter();}
  async create():Promise<void>{
    if(this.busy()||!this.auth.isAdmin())return;
    this.busy.set(true);this.error.set('');
    try{
      if(this.editingId)await this.api.updatePrinter(this.editingId,{...this.model});else await this.api.addPrinter({...this.model});
      this.cancelEdit();await this.refresh();this.notice.show('Printer configuration saved. Test the connection to verify access.');
    }catch(error){this.error.set(apiError(error));}finally{this.busy.set(false);}
  }
  async probe(printer:Printer):Promise<void>{
    if(this.busy()||!this.auth.isAdmin())return;
    this.busy.set(true);this.error.set('');
    try{const result=await this.api.probe(printer.id);this.notice.show(printer.name+' reports '+result.state+(result.filename?' · '+result.filename:''));}
    catch(error){this.error.set(apiError(error));}finally{this.busy.set(false);}
  }
  async control(printer:Printer,action:'pause'|'resume'|'cancel'):Promise<void>{
    if(this.busy()||!this.auth.isAdmin()||!window.confirm(action+' the physical print on '+printer.name+'?'))return;
    this.busy.set(true);this.error.set('');let failure='';
    try{await this.api.controlPrinter(printer.id,action);this.notice.show('Command accepted. Verify the printer before issuing another command.');}
    catch(error){failure=apiError(error);}
    finally{await this.refresh();await this.data.load();if(failure)this.error.set(failure+' Check the printer and the operation state before continuing.');this.busy.set(false);}
  }
  async assignSlot():Promise<void>{
    if(this.busy()||!this.auth.canEdit()||!this.printerSelection||!this.slotSpool)return;
    if(!Number.isInteger(this.slotTool)||this.slotTool<0||this.slotTool>15){this.error.set('Choose a tool number from 0 to 15.');return;}
    this.busy.set(true);this.error.set('');
    try{await this.api.assignSlot(this.printerSelection,this.slotTool,this.slotSpool);await this.refresh();this.notice.show('Loaded roll recorded for tool '+this.slotTool+'.');}
    catch(error){this.error.set(apiError(error));}finally{this.busy.set(false);}
  }
  async unloadSlot(tool:number,printerId=this.printerSelection):Promise<void>{
    if(this.busy()||!this.auth.canEdit())return;
    this.busy.set(true);this.error.set('');
    try{await this.api.unloadSlot(printerId,tool);await this.refresh();this.notice.show('Recorded slot assignment removed.');}
    catch(error){this.error.set(apiError(error));}finally{this.busy.set(false);}
  }
  async clearUpload():Promise<void>{
    const operation=this.clearOperation;
    if(!operation||operation.kind!=='upload'||operation.state!=='unknown'||!this.auth.isAdmin()||this.busy()||!this.clearChecked||this.clearReason.trim().length<10)return;
    this.busy.set(true);this.error.set('');
    try{await this.api.clearUploadOperation(operation.printer_id,operation.operation_id,this.clearReason.trim());this.clearOperation=null;this.clearReason='';this.clearChecked=false;await this.refresh();this.notice.show('Uncertain upload released after your check.');}
    catch(error){this.error.set(apiError(error));}finally{this.busy.set(false);}
  }
  async toggle(printer:Printer):Promise<void>{
    if(this.busy()||!this.auth.isAdmin())return;
    this.busy.set(true);this.error.set('');
    try{await this.api.updatePrinter(printer.id,{name:printer.name,kind:printer.kind,base_url:printer.base_url,token_env:printer.token_env,enabled:!printer.enabled});await this.refresh();this.notice.show('Printer configuration updated.');}
    catch(error){this.error.set(apiError(error));}finally{this.busy.set(false);}
  }
}
