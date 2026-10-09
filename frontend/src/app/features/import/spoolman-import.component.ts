import { Component, OnDestroy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../auth.service';
import { NoticeService } from '../../dialog.service';
import { apiError, InventoryService } from '../../inventory.service';
import { ApiSpoolmanPreview } from '../../core/api/generated-contracts';
import { RequestOwner } from '../../core/request-owner';

type Preview=ApiSpoolmanPreview;
@Component({standalone:true,imports:[FormsModule],templateUrl:'./spoolman-import.component.html'})
export class SpoolmanImportComponent implements OnDestroy {
  readonly auth=inject(AuthService);readonly http=inject(HttpClient);
  readonly notice=inject(NoticeService);readonly data=inject(InventoryService);
  readonly busy=signal(false);readonly error=signal('');
  readonly preview=signal<Preview|null>(null);
  source='spoolman';selected:File|null=null;confirmed=false;
  private readonly requests=new RequestOwner();
  private validated:{file:File;source:string;bytes:string}|null=null;
  ngOnDestroy():void{this.requests.invalidate();}
  invalidate():void{this.requests.invalidate();this.preview.set(null);this.validated=null;this.confirmed=false;}
  onFile(event:Event):void{
    const input=event.target as HTMLInputElement;
    this.selected=input.files?.[0]||null;input.value='';this.invalidate();this.error.set('');
  }
  private perform(source:string,bytes:string,dryRun:boolean):Promise<Preview>{
    const route='/api/import/spoolman?source='+encodeURIComponent(source)+'&dry_run='+(dryRun?'true':'false');
    return firstValueFrom(this.http.post<Preview>(route,bytes,{headers:new HttpHeaders({'Content-Type':'application/json'})}));
  }
  async previewImport():Promise<void>{
    if(!this.auth.canEdit()||this.busy())return;
    const file=this.selected,source=this.source.trim();
    if(!file){this.error.set('Choose a Spoolman JSON file.');return;}
    if(!source){this.error.set('Enter a source identifier.');return;}
    const owner=this.requests.begin();this.busy.set(true);this.error.set('');this.preview.set(null);this.validated=null;this.confirmed=false;
    try{
      const bytes=await file.text();
      if(!this.requests.owns(owner)||this.selected!==file||this.source.trim()!==source)return;
      const result=await this.perform(source,bytes,true);
      if(!this.requests.owns(owner)||this.selected!==file||this.source.trim()!==source)return;
      this.validated={file,source,bytes};this.preview.set(result);
    }catch(e){if(this.requests.owns(owner))this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  async commit():Promise<void>{
    if(!this.auth.canEdit()||!this.confirmed||!this.preview()||this.busy())return;
    const validated=this.validated;
    if(!validated||validated.file!==this.selected||validated.source!==this.source.trim()){
      this.invalidate();this.error.set('The file or source changed. Preview the current snapshot again.');return;
    }
    this.busy.set(true);this.error.set('');
    try{
      const result=await this.perform(validated.source,validated.bytes,false);
      this.invalidate();await this.data.load();
      this.notice.show('Imported '+result.products_created+' products and '+result.spools_created+' spools. Skipped '+result.products_skipped+' existing products, '+result.spools_skipped+' existing spools and '+result.archived_skipped+' archived spools.');
    }catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
}
