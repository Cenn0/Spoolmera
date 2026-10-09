import { SpoolVisualComponent } from '../../core/ui/spool-visual.component';
import { addLabel, reorderLabels, MAX_LABELS } from '../../core/ui/label-selection';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { Component, OnInit, HostListener, computed, inject, signal, effect, untracked, DestroyRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../auth.service';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RequestOwner } from '../../core/request-owner';
import { DialogService, NoticeService } from '../../dialog.service';
import { InventoryService, apiError } from '../../inventory.service';
import { Spool, stockPercent, isLowStock } from '../../models';

@Component({
  standalone: true,
  imports:[TranslatePipe,FormsModule,RouterLink,SpoolVisualComponent],
  templateUrl:'./spools.component.html'
})
export class SpoolsComponent implements OnInit {
  readonly i18n=inject(I18nService);
  readonly route=inject(ActivatedRoute);private readonly router=inject(Router);private readonly destroy=inject(DestroyRef);
  private readonly requests=new RequestOwner();
  readonly items=signal<Spool[]>([]);readonly loading=signal(false);readonly error=signal('');
  readonly nextCursor=signal<number|null>(null);readonly archived=signal<'active'|'archived'|'all'>('active');
  readonly selectedSpools=signal<Spool[]>([]);
  readonly selectedLabels=computed(()=>this.selectedSpools().map(item=>item.uid));readonly low=isLowStock;
  labelSize='60x40';
  readonly displayMode=signal<'cards'|'table'>('cards');
  readonly dragged=signal<Spool|null>(null);
  readonly overTray=signal(false);
  setDisplay(value:'cards'|'table'):void {
    this.displayMode.set(value);
    try { localStorage.setItem('filament-manager-spool-view',value); } catch { /* Preference only. */ }
  }
  addToTray(spool:Spool):void {
    if(this.selectedSpools().length>=MAX_LABELS && !this.selectedLabels().includes(spool.uid)) {
      this.notices.show('Select at most 100 labels per sheet.',true);return;
    }
    this.selectedSpools.update(items=>addLabel(items,spool));
  }
  dragStart(event:DragEvent,spool:Spool):void {
    this.dragged.set(spool);
    if(event.dataTransfer) { event.dataTransfer.effectAllowed='copyMove';event.dataTransfer.setData('application/x-filament-spool',spool.uid); }
  }
  dragEnd():void { this.dragged.set(null);this.overTray.set(false); }
  dragOverTray(event:DragEvent):void {
    if(!this.dragged())return;
    event.preventDefault();this.overTray.set(true);
    if(event.dataTransfer)event.dataTransfer.dropEffect='copy';
  }
  dropOnTray(event:DragEvent):void {
    event.preventDefault();event.stopPropagation();
    const spool=this.dragged();if(spool)this.addToTray(spool);this.dragEnd();
  }
  reorderSelected(event:DragEvent,targetUid:string):void {
    event.preventDefault();event.stopPropagation();
    const spool=this.dragged();
    if(spool){
      this.addToTray(spool);
      this.selectedSpools.update(items=>reorderLabels(items,spool.uid,targetUid));
    }
    this.dragEnd();
  }
  moveSelected(uid:string,direction:-1|1):void {
    const items=this.selectedSpools(),index=items.findIndex(item=>item.uid===uid),target=items[index+direction];
    if(index>=0&&target)this.selectedSpools.set(reorderLabels(items,uid,target.uid));
  }

  private searchTimer:ReturnType<typeof setTimeout>|undefined;
  constructor(){try{if(localStorage.getItem('filament-manager-spool-view')==='table')this.displayMode.set('table');}catch{/* Preference only. */}effect(()=>{this.data.changed();untracked(()=>void this.refresh());});}
  ngOnInit():void{this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroy)).subscribe(params=>{
    this.query.set(params.get('q')||'');
    const product=Number(params.get('product'));this.productId.set(Number.isSafeInteger(product)&&product>0?product:undefined);
    const mode=params.get('archived');this.archived.set(mode==='all'||mode==='archived'?mode:'active');
    void this.refresh();
  });}
  @HostListener('window:focus') onFocus():void{void this.refresh();}
  changeSearch(value:string):void{this.query.set(value);clearTimeout(this.searchTimer);this.requests.invalidate();this.loading.set(false);
    this.searchTimer=setTimeout(()=>void this.refresh(),250);}
  async refresh(more=false):Promise<void>{
    if(more&&(this.loading()||!this.nextCursor()))return;
    const owner=this.requests.begin();this.loading.set(true);this.error.set('');
    if(!more){this.items.set([]);this.nextCursor.set(null);}
    try{const result=await this.data.spoolPage(this.archived(),more?this.nextCursor()!:undefined,this.query(),this.material(),this.status(),this.productId());
      if(!this.requests.owns(owner))return;
      this.items.update(old=>more?[...old,...result.items.filter(item=>!old.some(s=>s.id===item.id))]:result.items);this.nextCursor.set(result.next_cursor);
      this.selectedSpools.update(selected=>selected.map(item=>result.items.find(fresh=>fresh.uid===item.uid)??item));
    }catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
  toggleLabel(uid:string):void{
    if(this.selectedLabels().includes(uid))this.selectedSpools.update(items=>items.filter(item=>item.uid!==uid));
    else{const spool=this.items().find(item=>item.uid===uid);if(spool)this.addToTray(spool);}
  }
  get labelUrl():string{return '/labels?uids='+this.selectedLabels().join(',')+'&size='+this.labelSize+'&lang='+this.i18n.language();}
  readonly data = inject(InventoryService);
  readonly dialogs = inject(DialogService);
  readonly auth = inject(AuthService);
  readonly grams=(value:number)=>this.i18n.grams(value);
  readonly percent = stockPercent;
  readonly query = signal('');
  readonly material = signal('');
  readonly status = signal('');
  readonly productId=signal<number|undefined>(undefined);
  clearProductFilter():void {
    // Keep the URL and the visible filter aligned so reload/back does not restore a cleared product.
    void this.router.navigate([], {relativeTo:this.route, queryParamsHandling:'merge',
      queryParams:{product:null,q:this.query()||null,archived:this.archived()}});
  }
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
      this.notices.show(this.i18n.message('NFC reader unavailable or permission refused: {error}',{error:this.i18n.message(apiError(err))}),true);
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
