import { orderSpools, spoolSort, storageLanes, type SpoolSort } from './spool-board';
import { SpoolVisualComponent } from '../../core/ui/spool-visual.component';
import { addLabel, reorderLabels, MAX_LABELS } from '../../core/ui/label-selection';
import type { LocalizedMessage } from '../../core/i18n/types';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { Component, OnInit, HostListener, ViewChild, ElementRef, computed, inject, signal, effect, untracked, DestroyRef } from '@angular/core';
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
  templateUrl:'./spools.component.html',
  styleUrl:'./spools.component.css'
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
  readonly displayMode=signal<'cards'|'table'|'locations'>('cards');
  readonly spoolOrder=signal<SpoolSort>('newest');
  readonly filtered=computed(()=>orderSpools(this.items(),this.spoolOrder(),this.i18n.locale()));
  readonly extraLocations=signal<string[]>([]);
  readonly locationDraft=signal('');
  readonly locationError=signal('');
  readonly pendingLocation=signal<{uid:string;id:number;name:string;original:string;target:string}|null>(null);
  readonly locationConfirmed=signal(false);
  readonly locationBusy=signal(false);
  readonly hoverLocation=signal<string|null>(null);
  readonly knownLocations=computed(()=>[...new Set([
    ...this.data.spools().filter(s=>!s.archived_at).map(s=>s.location||''),
    ...this.extraLocations()
  ])]);
  readonly storageBoard=computed(()=>storageLanes(this.filtered(),this.knownLocations(),this.i18n.locale()));
  readonly canScrollStorageBack=signal(false);
  readonly canScrollStorageForward=signal(false);
  private storageElement:HTMLElement|null=null;
  private storageResizeObserver:ResizeObserver|null=null;
  private storageMutationObserver:MutationObserver|null=null;

  // The board is rendered conditionally. Observe both container size and lane
  // changes so scroll controls stay accurate after pagination or resizing.
  @ViewChild('storageBoardEl') set storageBoardRef(ref:ElementRef<HTMLElement>|undefined) {
    this.storageResizeObserver?.disconnect();
    this.storageMutationObserver?.disconnect();
    const board=ref?.nativeElement??null;
    this.storageElement=board;
    if(!board){
      this.canScrollStorageBack.set(false);
      this.canScrollStorageForward.set(false);
      return;
    }
    if(typeof ResizeObserver!=='undefined'){
      this.storageResizeObserver=new ResizeObserver(()=>this.updateStorageScrollState(board));
      this.storageResizeObserver.observe(board);
    }
    if(typeof MutationObserver!=='undefined'){
      this.storageMutationObserver=new MutationObserver(()=>this.updateStorageScrollState(board));
      this.storageMutationObserver.observe(board,{childList:true});
    }
    queueMicrotask(()=>{if(this.storageElement===board&&!this.destroy.destroyed)this.updateStorageScrollState(board);});
  }
  updateStorageScrollState(board:HTMLElement):void {
    if(board!==this.storageElement)return;
    const max=Math.max(0,board.scrollWidth-board.clientWidth);
    this.canScrollStorageBack.set(board.scrollLeft>2);
    this.canScrollStorageForward.set(board.scrollLeft<max-2);
  }
  scrollStorage(direction:-1|1):void {
    const board=this.storageElement;
    // Scrolling never stages a move; keep the native drag source stable.
    if(!board||this.dragged())return;
    const lane=board.querySelector<HTMLElement>('.storage-lane');
    const step=Math.max((lane?.getBoundingClientRect().width??280)+14,Math.floor(board.clientWidth*0.7));
    const reduceMotion=typeof window.matchMedia==='function'&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    board.scrollBy({left:direction*step,behavior:reduceMotion?'instant':'smooth'});
  }
  setSpoolOrder(value:string):void {
    const order=spoolSort(value);this.spoolOrder.set(order);
    try{localStorage.setItem('spoolmera-spool-sort',order);}catch{/* Presentation preference. */}
  }
  createLocationLane():void {
    const name=this.locationDraft().trim();
    if(!name||name.length>120){this.locationError.set('Enter a location name of at most 120 characters.');return;}
    if(!this.knownLocations().includes(name))this.extraLocations.update(items=>[...items,name]);
    this.locationDraft.set('');this.locationError.set('');
  }
  stageLocation(spool:Spool,target:string):void {
    if(!this.auth.canEdit()||this.locationBusy()||spool.archived_at||!this.items().some(item=>item.uid===spool.uid))return;
    const location=target.trim();
    if(location.length>120){this.locationError.set('Enter a location name of at most 120 characters.');return;}
    if(location===(spool.location||''))return;
    this.pendingLocation.set({uid:spool.uid,id:spool.id,name:spool.brand+' · '+spool.product_name,
      original:spool.location||'',target:location});
    this.locationConfirmed.set(false);this.locationError.set('');
  }
  chooseLocation(event:Event,spool:Spool):void {
    const select=event.target as HTMLSelectElement;
    const target=select.value;select.value=spool.location||''; // No unsaved visual mutation.
    this.stageLocation(spool,target);
  }
  overLocation(event:DragEvent,location:string):void {
    if(!this.dragged()||!this.auth.canEdit()||this.dragged()?.archived_at||this.locationBusy())return;
    event.preventDefault();this.hoverLocation.set(location);
    if(event.dataTransfer)event.dataTransfer.dropEffect='move';
  }
  dropLocation(event:DragEvent,location:string):void {
    event.preventDefault();event.stopPropagation();
    const spool=this.dragged();
    if(spool)this.stageLocation(spool,location);
    this.dragEnd();
  }
  cancelLocation():void{if(!this.locationBusy()){this.pendingLocation.set(null);this.locationConfirmed.set(false);this.locationError.set('');}}
  async saveLocation():Promise<void>{
    const pending=this.pendingLocation();
    if(!pending||this.locationBusy()||!this.locationConfirmed()||!this.auth.canEdit())return;
    this.locationBusy.set(true);this.locationError.set('');
    try{
      const fresh=await this.data.spoolByUid(pending.uid);
      if(fresh.id!==pending.id||fresh.archived_at||(fresh.location||'')!==pending.original)
        throw new Error('Spool location changed. Reload the inventory and try again.');
      await this.data.updateSpool(pending.id,{location:pending.target,expected_location:pending.original});
      this.pendingLocation.set(null);this.locationConfirmed.set(false);
      this.notices.show(this.i18n.message('Location saved for {spool}.',{spool:pending.name}));
      await this.refresh();
    }catch(error){
      this.pendingLocation.set(null);this.locationConfirmed.set(false);
      this.locationError.set(apiError(error));
      // A lost response must not automatically retry a potentially successful PATCH.
      await this.refresh();
    }finally{this.locationBusy.set(false);}
  }
  readonly dragged=signal<Spool|null>(null);
  readonly overTray=signal(false);
  readonly dropTarget=signal<string|null>(null);
  readonly labelFeedback=signal<LocalizedMessage|null>(null);
  readonly lowOnly=signal(false);
  readonly loadedSelected=computed(()=>this.items().filter(item=>this.selectedLabels().includes(item.uid)).length);
  readonly canSelectLoaded=computed(()=>this.items().some(item=>!this.selectedLabels().includes(item.uid))
    &&new Set([...this.selectedLabels(),...this.items().map(item=>item.uid)]).size<=MAX_LABELS);
  private routeReady=false;
  private displayedFilters='';
  private refreshAfterDrag=false;
  readonly filtersOpen=signal(false);
  readonly activeFilterCount=computed(()=>Number(this.archived()!=='active')+Number(!!this.material())+Number(!!this.status())+Number(this.lowOnly()));
  setDisplay(value:'cards'|'table'|'locations'):void {
    this.displayMode.set(value);
    try { localStorage.setItem('spoolmera-spool-view',value); } catch { /* Preference only. */ }
  }
  selectLoaded():void {
    this.labelFeedback.set(null);
    if(this.loading())return;
    if(new Set([...this.selectedLabels(),...this.items().map(item=>item.uid)]).size>MAX_LABELS){
      this.notices.show('Select at most 100 labels per sheet.',true);return;
    }
    this.selectedSpools.update(selected=>this.items().reduce((all,item)=>addLabel(all,item),selected));
  }
  deselectLoaded():void {
    this.labelFeedback.set(null);
    const visible=new Set(this.items().map(item=>item.uid));
    this.selectedSpools.update(selected=>selected.filter(item=>!visible.has(item.uid)));
  }
  clearSelection():void {this.selectedSpools.set([]);this.labelFeedback.set(null);}
  markDropTarget(event:DragEvent,uid:string):void {
    this.dragOverTray(event);if(this.dragged())this.dropTarget.set(uid);
  }
  dropSide(uid:string):'before'|'after'|null {
    const dragged=this.dragged();
    if(!dragged||dragged.uid===uid||this.dropTarget()!==uid)return null;
    const from=this.selectedLabels().indexOf(dragged.uid),to=this.selectedLabels().indexOf(uid);
    return from>=0&&from<to?'after':'before';
  }
  private announcePosition(uid:string):void {
    const index=this.selectedSpools().findIndex(item=>item.uid===uid);
    if(index>=0)this.labelFeedback.set(this.i18n.message('Label for spool #{id}: position {position} of {count}.',
      {id:this.selectedSpools()[index].id,position:index+1,count:this.selectedSpools().length}));
  }
  addToTray(spool:Spool):void {
    this.labelFeedback.set(null);
    if(this.selectedSpools().length>=MAX_LABELS && !this.selectedLabels().includes(spool.uid)) {
      this.notices.show('Select at most 100 labels per sheet.',true);return;
    }
    this.selectedSpools.update(items=>addLabel(items,spool));
  }
  dragStart(event:DragEvent,spool:Spool):void {
    // Also suspend responses requested before the pointer started dragging.
    if(this.loading()){this.requests.invalidate();this.refreshAfterDrag=true;this.loading.set(false);}
    this.dragged.set(spool);this.labelFeedback.set(null);
    if(event.dataTransfer) { event.dataTransfer.effectAllowed='copyMove';event.dataTransfer.setData('application/x-spoolmera-spool',spool.uid); }
  }
  dragEnd():void {
    this.dragged.set(null);this.overTray.set(false);this.dropTarget.set(null);this.hoverLocation.set(null);
    if(this.refreshAfterDrag){this.refreshAfterDrag=false;void this.refresh();}
  }
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
      this.announcePosition(spool.uid);
    }
    this.dragEnd();
  }
  moveSelected(uid:string,direction:-1|1):void {
    const items=this.selectedSpools(),index=items.findIndex(item=>item.uid===uid),target=items[index+direction];
    if(index>=0&&target){this.selectedSpools.set(reorderLabels(items,uid,target.uid));this.announcePosition(uid);}
  }

  private searchTimer:ReturnType<typeof setTimeout>|undefined;
  constructor(){
    try{const view=localStorage.getItem('spoolmera-spool-view');if(view==='table'||view==='locations')this.displayMode.set(view);this.spoolOrder.set(spoolSort(localStorage.getItem('spoolmera-spool-sort')));}catch{/* Preference only. */}
    effect(()=>{this.data.changed();untracked(()=>{if(this.routeReady)void this.refresh();});});
  }
  ngOnInit():void {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroy)).subscribe(params=>{
      clearTimeout(this.searchTimer);
      this.query.set((params.get('q')||'').slice(0,120));
      const rawProduct=params.get('product')||'';
      const product=Number(rawProduct);
      this.productId.set(/^\d+$/.test(rawProduct)&&Number.isSafeInteger(product)&&product>0?product:undefined);
      const mode=params.get('archived');this.archived.set(mode==='all'||mode==='archived'?mode:'active');
      this.material.set((params.get('material')||'').slice(0,32));
      const status=params.get('status');this.status.set(status==='sealed'||status==='opened'||status==='empty'?status:'');
      this.lowOnly.set(params.get('low')==='1');
      this.routeReady=true;
      // A filter navigation invalidates any in-flight drag and old response.
      this.refreshAfterDrag=false;this.dragged.set(null);this.overTray.set(false);this.dropTarget.set(null);
      void this.refresh();
    });
  }
  @HostListener('window:focus') onFocus():void{if(this.routeReady)void this.refresh();}
  changeSearch(value:string):void {
    this.query.set(value.slice(0,120));clearTimeout(this.searchTimer);this.requests.invalidate();
    this.searchTimer=setTimeout(()=>this.syncFilters(true),250);
  }
  syncFilters(replaceUrl=false):void {
    clearTimeout(this.searchTimer);this.requests.invalidate();
    void this.router.navigate([], {relativeTo:this.route,queryParamsHandling:'merge',replaceUrl,
      queryParams:{q:this.query().trim()||null,material:this.material()||null,status:this.status()||null,
        archived:this.archived()==='active'?null:this.archived(),product:this.productId()??null,low:this.lowOnly()?'1':null}})
      .then(navigated=>{if(!navigated&&!this.destroy.destroyed)void this.refresh();})
      .catch(error=>{if(!this.destroy.destroyed){this.loading.set(false);this.error.set(apiError(error));}});
  }
  clearFilters():void {
    this.query.set('');this.material.set('');this.status.set('');this.archived.set('active');this.lowOnly.set(false);
    this.productId.set(undefined);this.syncFilters();
  }
  quickFilter(kind:'all'|'opened'|'low'):void {
    this.query.set('');this.material.set('');this.archived.set('active');this.productId.set(undefined);
    this.status.set(kind==='opened'?'opened':'');this.lowOnly.set(kind==='low');this.syncFilters();
  }
  private filters(){return {archived:this.archived(),query:this.query().trim(),material:this.material(),
    status:this.status(),product:this.productId(),low:this.lowOnly()};}
  async refresh(more=false):Promise<void> {
    if(this.destroy.destroyed)return;
    if(this.dragged()){this.refreshAfterDrag=true;return;}
    if(more&&(this.loading()||!this.nextCursor()))return;
    const filters=this.filters(),key=JSON.stringify(filters),same=key===this.displayedFilters;
    const target=more?1:(same?Math.max(1,this.items().length):1);
    const owner=this.requests.begin();this.loading.set(true);this.error.set('');
    // Keep cards and focus mounted on ordinary refreshes. A new filter must not
    // display rows from the previous filter while its response is outstanding.
    if(!same){this.items.set([]);this.nextCursor.set(null);this.displayedFilters=key;}
    let cursor=more?this.nextCursor():null;
    const fresh:Spool[]=[];
    try{
      do {
        const result=await this.data.spoolPage(filters.archived,cursor??undefined,filters.query,
          filters.material,filters.status,filters.product,filters.low);
        if(!this.requests.owns(owner))return;
        fresh.push(...result.items.filter(item=>!fresh.some(old=>old.id===item.id)));
        const previous=cursor;cursor=result.next_cursor;
        // Enforce progress even if an unexpected backend response repeats its cursor.
        if(cursor!==null&&previous!==null&&cursor>=previous)throw new Error('Unable to load more spools. Refresh and retry.');
      }while(!more&&fresh.length<target&&cursor!==null);
      this.items.update(old=>more?[...old,...fresh.filter(item=>!old.some(s=>s.id===item.id))]:fresh);
      this.nextCursor.set(cursor);
      this.selectedSpools.update(selected=>selected.map(item=>fresh.find(row=>row.uid===item.uid)??item));
    }catch(error){if(this.requests.owns(owner))this.error.set(apiError(error));}
    finally{if(this.requests.owns(owner))this.loading.set(false);}
  }
  toggleLabel(uid:string):void{
    this.labelFeedback.set(null);
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
  clearProductFilter():void {this.productId.set(undefined);this.syncFilters();}
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
  ngOnDestroy():void{this.storageResizeObserver?.disconnect();this.storageMutationObserver?.disconnect();this.storageElement=null;this.stopNfc();this.requests.invalidate();clearTimeout(this.searchTimer);}

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
}
