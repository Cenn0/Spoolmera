import { Component, OnInit, HostListener, computed, inject, signal, effect, untracked, DestroyRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../auth.service';
import { CloudReceipt, Printer, WorkspaceService } from '../../workspace.service';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RequestOwner } from '../../core/request-owner';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Capabilities, Spool, dateText, grams, stockPercent, isLowStock } from '../../models';

@Component({
  standalone: true,
  imports: [FormsModule,RouterLink],
  templateUrl:'./spools.component.html'
})
export class SpoolsComponent implements OnInit {
  readonly route=inject(ActivatedRoute);private readonly destroy=inject(DestroyRef);
  private readonly requests=new RequestOwner();
  readonly items=signal<Spool[]>([]);readonly loading=signal(false);readonly error=signal('');
  readonly nextCursor=signal<number|null>(null);readonly archived=signal<'active'|'archived'|'all'>('active');
  readonly selectedLabels=signal<string[]>([]);readonly low=isLowStock;
  labelSize='60x40';
  private searchTimer:ReturnType<typeof setTimeout>|undefined;
  constructor(){effect(()=>{this.data.changed();untracked(()=>void this.refresh());});}
  ngOnInit():void{this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroy)).subscribe(params=>{
    this.query.set(params.get('q')||'');
    const mode=params.get('archived');this.archived.set(mode==='all'||mode==='archived'?mode:'active');
    void this.refresh();
  });}
  @HostListener('window:focus') onFocus():void{void this.refresh();}
  changeSearch(value:string):void{this.query.set(value);clearTimeout(this.searchTimer);this.requests.invalidate();this.loading.set(false);
    this.searchTimer=setTimeout(()=>void this.refresh(),250);}
  async refresh(more=false):Promise<void>{
    if(more&&(this.loading()||!this.nextCursor()))return;
    const owner=this.requests.begin();this.loading.set(true);this.error.set('');
    if(!more){this.items.set([]);this.nextCursor.set(null);this.selectedLabels.set([]);}
    try{const result=await this.data.spoolPage(this.archived(),more?this.nextCursor()!:undefined,this.query(),this.material(),this.status());
      if(!this.requests.owns(owner))return;
      this.items.update(old=>more?[...old,...result.items.filter(item=>!old.some(s=>s.id===item.id))]:result.items);this.nextCursor.set(result.next_cursor);
    }catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
  toggleLabel(uid:string):void{this.selectedLabels.update(old=>old.includes(uid)?old.filter(id=>id!==uid):[...old,uid]);}
  get labelUrl():string{return '/labels?uids='+this.selectedLabels().join(',')+'&size='+this.labelSize;}
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
  ngOnDestroy():void{this.stopNfc();this.requests.invalidate();clearTimeout(this.searchTimer);}

  async findTag():Promise<void>{
    if(this.scanning()||!this.tagSearch.trim())return;
    this.scanning.set(true);
    try{
      const found=await this.data.resolveIdentifier(this.tagNamespace,this.tagSearch.trim());
      window.location.assign('/?spool='+encodeURIComponent(found.uid));
    }catch(err){this.notices.show(apiError(err),true);}
    finally{this.scanning.set(false);}
  }
  readonly materials = computed(() => Array.from(new Set(this.data.products().map(item=>item.material))).sort());
  readonly filtered = this.items;
}
