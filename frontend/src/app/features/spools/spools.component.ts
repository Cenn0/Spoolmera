import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService } from '../../workspace.service';
import { RouterLink } from '@angular/router';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, dateText, grams, stockPercent } from '../../models';

@Component({
  standalone: true,
  imports: [FormsModule],
  templateUrl:'../../spools.html'
})
export class SpoolsComponent {
  readonly data = inject(InventoryService);
  readonly dialogs = inject(DialogService);
  readonly auth = inject(AuthService);
  readonly grams = grams;
  readonly percent = stockPercent;
  readonly query = signal('');
  readonly material = signal('');
  readonly status = signal('');
  readonly notices=inject(NoticeService);
  tagNamespace='nfc';tagSearch='';
  readonly scanning=signal(false);
  readonly nfcActive=signal(false);
  private nfcController:AbortController|null=null;
  supportsWebNfc():boolean {
    return typeof (window as unknown as {NDEFReader?:unknown}).NDEFReader==='function';
  }
  async scanNfc():Promise<void> {
    const ctor=(window as unknown as {NDEFReader?:new()=> {
      scan(options?:{signal?:AbortSignal}):Promise<void>;
      onreading:((event:{serialNumber:string})=>void)|null;
    }}).NDEFReader;
    if(!ctor){
      this.notices.show('Web NFC is unsupported in this browser. Use a tag reader or QR instead.',true);
      return;
    }
    if(this.nfcController)this.nfcController.abort();
    this.nfcController=new AbortController();
    const reader=new ctor();
    reader.onreading=event=>{
      if(!event.serialNumber || !/^[A-Za-z0-9:_-]{8,128}$/.test(event.serialNumber)){
        this.notices.show('Tag has no supported public serial number. Use a QR label or reader.',true);
        return;
      }
      this.tagNamespace='nfc';this.tagSearch=event.serialNumber;
      this.stopNfc();void this.findTag();
    };
    this.nfcActive.set(true);
    try{await reader.scan({signal:this.nfcController.signal});}
    catch(err){
      this.stopNfc();
      this.notices.show('NFC reader unavailable or permission refused: '+apiError(err),true);
    }
  }
  stopNfc():void{
    this.nfcController?.abort();this.nfcController=null;this.nfcActive.set(false);
  }
  ngOnDestroy():void{this.stopNfc();}

  async findTag():Promise<void>{
    if(this.scanning()||!this.tagSearch.trim())return;
    this.scanning.set(true);
    try{
      const found=await this.data.resolveIdentifier(this.tagNamespace,this.tagSearch.trim());
      window.location.assign('/?spool='+encodeURIComponent(found.uid));
    }catch(err){this.notices.show(apiError(err),true);}
    finally{this.scanning.set(false);}
  }
  readonly materials = computed(() => Array.from(new Set(this.data.spools().map(item=>item.material))).sort());
  readonly filtered = computed(() => {
    const query=this.query().trim().toLocaleLowerCase('en-US'), material=this.material(), status=this.status();
    return this.data.spools().filter(s =>
      (!material || s.material===material) && (!status || s.status===status) &&
      (!query || [s.brand,s.product_name,s.material,s.color_name,s.location,s.notes].join(' ').toLocaleLowerCase('en-US').includes(query)));
  });
}
