import { Component, HostListener, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { WorkspaceService } from '../../workspace.service';
import { ApiAlerts, ApiDiagnostics } from '../../core/api/generated-contracts';
import { RequestOwner } from '../../core/request-owner';
import { apiError } from '../../inventory.service';
import { dateText, grams } from '../../models';
@Component({standalone:true,imports:[RouterLink],templateUrl:'./operations.component.html'})
export class OperationsComponent implements OnInit, OnDestroy {
  readonly api=inject(WorkspaceService);readonly state=signal<ApiDiagnostics|null>(null);readonly alerts=signal<ApiAlerts|null>(null);
  readonly error=signal('');readonly loading=signal(false);readonly dateText=dateText;readonly grams=grams;
  private readonly requests=new RequestOwner();
  ngOnInit():void{void this.refresh();}ngOnDestroy():void{this.requests.invalidate();}
  @HostListener('window:focus') onFocus():void{void this.refresh();}
  bytes(value:number|null):string{return value===null?'—':value<1024*1024?(value/1024).toFixed(1)+' KiB':(value/(1024*1024)).toFixed(1)+' MiB';}
  async refresh():Promise<void>{
    const owner=this.requests.begin();this.loading.set(true);this.error.set('');
    const results=await Promise.allSettled([this.api.diagnostics(),this.api.alerts()]);
    if(!this.requests.owns(owner))return;
    const [diagnostics,alerts]=results;
    if(diagnostics.status==='fulfilled')this.state.set(diagnostics.value);
    if(alerts.status==='fulfilled')this.alerts.set(alerts.value);
    this.error.set(results.flatMap(result=>result.status==='rejected'?[apiError(result.reason)]:[]).join(' · '));
    this.loading.set(false);
  }
}
