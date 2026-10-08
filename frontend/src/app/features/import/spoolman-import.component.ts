import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../auth.service';
import { NoticeService } from '../../dialog.service';
import { apiError, InventoryService } from '../../inventory.service';

interface Preview {
  dry_run:boolean;source:string;spools_created:number;spools_skipped:number;
  products_created:number;products_skipped:number;archived_skipped:number;
}
@Component({standalone:true,imports:[FormsModule],templateUrl:'./spoolman-import.component.html'})
export class SpoolmanImportComponent {
  readonly auth=inject(AuthService);readonly http=inject(HttpClient);
  readonly notice=inject(NoticeService);readonly data=inject(InventoryService);
  readonly busy=signal(false);readonly error=signal('');
  readonly preview=signal<Preview|null>(null);
  source='spoolman';selected:File|null=null;confirmed=false;
  onFile(event:Event):void{
    this.selected=(event.target as HTMLInputElement).files?.[0]||null;
    this.preview.set(null);this.confirmed=false;
  }
  private async perform(dryRun:boolean):Promise<Preview>{
    if(!this.selected)throw new Error('Choose a Spoolman JSON file.');
    const bytes=await this.selected.text();
    const route='/api/import/spoolman?source='+encodeURIComponent(this.source)
      +'&dry_run='+(dryRun?'true':'false');
    return firstValueFrom(this.http.post<Preview>(route,bytes,
      {headers:new HttpHeaders({'Content-Type':'application/json'})}));
  }
  async previewImport():Promise<void>{
    if(!this.auth.canEdit()||this.busy())return;
    this.busy.set(true);this.error.set('');this.preview.set(null);this.confirmed=false;
    try{this.preview.set(await this.perform(true));}
    catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
  async commit():Promise<void>{
    if(!this.auth.canEdit()||!this.confirmed||!this.preview()||this.busy())return;
    if(this.preview()?.source!==this.source){
      this.error.set('Source identifier changed. Validate and preview the snapshot again.');
      this.confirmed=false;return;
    }
    this.busy.set(true);this.error.set('');
    try{
      const result=await this.perform(false);
      this.preview.set(null);this.confirmed=false;await this.data.load();
      this.notice.show('Imported '+result.spools_created+' new spools; '+result.spools_skipped+' already imported.');
    }catch(e){this.error.set(apiError(e));}
    finally{this.busy.set(false);}
  }
}
