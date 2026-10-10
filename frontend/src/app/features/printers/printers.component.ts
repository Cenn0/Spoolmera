import { Component, computed, HostListener, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { Printer, PrinterInput, PrinterCapabilities, WorkspaceService, PrinterSlot, PrinterOperation, PrinterProbe } from '../../workspace.service';
import { RequestOwner } from '../../core/request-owner';
import { I18nService, LocalizedMessage, TranslatePipe } from '../../core/i18n';

import { Spool } from '../../models';
import { SpoolVisualComponent } from '../../core/ui/spool-visual.component';

const blankPrinter=():PrinterInput=>({name:'',kind:'moonraker',base_url:'',token_env:'',serial:'',enabled:true});
@Component({standalone:true,imports:[FormsModule,RouterLink,TranslatePipe,SpoolVisualComponent],templateUrl:'./printers.component.html'})
export class PrintersComponent implements OnInit, OnDestroy {
  readonly i18n=inject(I18nService);
  readonly api=inject(WorkspaceService);readonly auth=inject(AuthService);readonly notice=inject(NoticeService);readonly data=inject(InventoryService);
  readonly printers=signal<Printer[]>([]);private readonly errorValue=signal<string|LocalizedMessage>('');readonly error=computed(()=>this.i18n.t(this.errorValue()));readonly busy=signal(false);readonly loading=signal(false);
  readonly observations=signal<Record<number,PrinterProbe>>({});
  readonly slots=signal<Record<number,PrinterSlot[]>>({});readonly operations=signal<Record<number,PrinterOperation[]>>({});
  readonly capabilities=signal<PrinterCapabilities>({write_enabled:false,max_upload_bytes:0});
  readonly grams=(value:number)=>this.i18n.grams(value);readonly dateText=(value:string|null|undefined)=>this.i18n.dateText(value);private readonly requests=new RequestOwner();
  readonly draggedSpool=signal<Spool|null>(null);readonly dropPrinter=signal<number|null>(null);
  readonly paletteQuery=signal('');
  readonly palette=computed(()=>{
    const query=this.paletteQuery().trim().toLocaleLowerCase(this.i18n.locale());
    return this.data.available().filter(s=>[s.brand,s.product_name,s.color_name,s.material,s.location,''+s.id].join(' ').toLocaleLowerCase(this.i18n.locale()).includes(query));
  });
  startSpoolDrag(event:DragEvent,spool:Spool):void {
    if(!this.auth.canEdit()||this.busy()){event.preventDefault();return;}
    this.draggedSpool.set(spool);
    if(event.dataTransfer){event.dataTransfer.effectAllowed='copy';event.dataTransfer.setData('application/x-spoolmera-spool',spool.uid);}
  }
  finishSpoolDrag():void {this.draggedSpool.set(null);this.dropPrinter.set(null);}
  overPrinter(event:DragEvent,printerId:number):void {
    if(!this.draggedSpool()||!this.auth.canEdit()||this.busy())return;
    event.preventDefault();this.dropPrinter.set(printerId);if(event.dataTransfer)event.dataTransfer.dropEffect='copy';
  }
  dropSpool(event:DragEvent,printerId:number):void {
    event.preventDefault();event.stopPropagation();
    const spool=this.draggedSpool();
    if(spool&&this.auth.canEdit()&&!this.busy()&&this.data.available().some(s=>s.uid===spool.uid)&&this.printers().some(p=>p.id===printerId)){
      this.printerSelection=printerId;this.slotSpool=spool.id;
      this.notice.show('Assignment prepared. Check the tool number and physical printer, then save.');
    }
    this.finishSpoolDrag();
  }
  printerSelection=0;slotTool=0;slotSpool=0;editingId:number|null=null;
  clearOperation:PrinterOperation|null=null;clearReason='';clearChecked=false;
  model:PrinterInput=blankPrinter();
  async ngOnInit():Promise<void>{await this.refresh();}
  ngOnDestroy():void{this.requests.invalidate();}
  @HostListener('window:focus') onFocus():void{if(!this.busy())void this.refresh();}
  async refresh():Promise<void>{
    const owner=this.requests.begin();this.loading.set(true);this.errorValue.set('');
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
    }catch(error){if(this.requests.owns(owner))this.errorValue.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
  edit(printer:Printer):void{
    this.editingId=printer.id;this.model={name:printer.name,kind:printer.kind,base_url:printer.base_url,token_env:printer.token_env,serial:printer.serial,enabled:!!printer.enabled};
  }
  cancelEdit():void{this.editingId=null;this.model=blankPrinter();}
  async create():Promise<void>{
    if(this.busy()||!this.auth.isAdmin())return;
    this.busy.set(true);this.errorValue.set('');
    try{
      if(this.editingId)await this.api.updatePrinter(this.editingId,{...this.model});else await this.api.addPrinter({...this.model});
      this.cancelEdit();await this.refresh();this.notice.show('Printer configuration saved. Test the connection to verify access.');
    }catch(error){this.errorValue.set(apiError(error));}finally{this.busy.set(false);}
  }
  async probe(printer:Printer):Promise<void>{
    if(this.busy()||!this.auth.isAdmin())return;
    this.busy.set(true);this.errorValue.set('');
    try{const result=await this.api.probe(printer.id);this.observations.update(old=>({...old,[printer.id]:result}));this.notice.show(this.i18n.message('{printer} reports {state}{file}',{printer:printer.name,state:this.i18n.message(result.state),file:result.filename?' · '+result.filename:''}));}
    catch(error){this.errorValue.set(apiError(error));}finally{this.busy.set(false);}
  }
  async control(printer:Printer,action:'pause'|'resume'|'cancel'):Promise<void>{
    const questions={pause:'pause the physical print on {printer}?',resume:'resume the physical print on {printer}?',cancel:'cancel the physical print on {printer}?'};
    if(this.busy()||!this.auth.isAdmin()||!window.confirm(this.i18n.t(questions[action],{printer:printer.name})))return;
    this.busy.set(true);this.errorValue.set('');let failure='';
    try{await this.api.controlPrinter(printer.id,action);this.notice.show('Command accepted. Verify the printer before issuing another command.');}
    catch(error){failure=apiError(error);}
    finally{await this.refresh();await this.data.load();if(failure)this.errorValue.set(this.i18n.message('{error} Check the printer and the operation state before continuing.',{error:this.i18n.message(failure)}));this.busy.set(false);}
  }
  async assignSlot():Promise<void>{
    if(this.busy()||!this.auth.canEdit()||!this.printerSelection||!this.slotSpool)return;
    if(!Number.isInteger(this.slotTool)||this.slotTool<0||this.slotTool>15){this.errorValue.set('Choose a tool number from 0 to 15.');return;}
    this.busy.set(true);this.errorValue.set('');
    try{await this.api.assignSlot(this.printerSelection,this.slotTool,this.slotSpool);await this.refresh();this.notice.show(this.i18n.message('Loaded roll recorded for tool {tool}.',{tool:String(this.slotTool)}));}
    catch(error){this.errorValue.set(apiError(error));}finally{this.busy.set(false);}
  }
  async unloadSlot(tool:number,printerId=this.printerSelection):Promise<void>{
    if(this.busy()||!this.auth.canEdit())return;
    this.busy.set(true);this.errorValue.set('');
    try{await this.api.unloadSlot(printerId,tool);await this.refresh();this.notice.show('Recorded slot assignment removed.');}
    catch(error){this.errorValue.set(apiError(error));}finally{this.busy.set(false);}
  }
  async clearUpload():Promise<void>{
    const operation=this.clearOperation;
    if(!operation||operation.kind!=='upload'||operation.state!=='unknown'||!this.auth.isAdmin()||this.busy()||!this.clearChecked||this.clearReason.trim().length<10)return;
    this.busy.set(true);this.errorValue.set('');
    try{await this.api.clearUploadOperation(operation.printer_id,operation.operation_id,this.clearReason.trim());this.clearOperation=null;this.clearReason='';this.clearChecked=false;await this.refresh();this.notice.show('Uncertain upload released after your check.');}
    catch(error){this.errorValue.set(apiError(error));}finally{this.busy.set(false);}
  }
  async toggle(printer:Printer):Promise<void>{
    if(this.busy()||!this.auth.isAdmin())return;
    this.busy.set(true);this.errorValue.set('');
    try{await this.api.updatePrinter(printer.id,{name:printer.name,kind:printer.kind,base_url:printer.base_url,token_env:printer.token_env,serial:printer.serial,enabled:!printer.enabled});await this.refresh();this.notice.show('Printer configuration updated.');}
    catch(error){this.errorValue.set(apiError(error));}finally{this.busy.set(false);}
  }
}
