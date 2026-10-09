import { Component, HostListener, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { WorkspaceService } from '../../workspace.service';
import { ApiAlerts, ApiDiagnostics } from '../../core/api/generated-contracts';
import { RequestOwner } from '../../core/request-owner';
import { apiError } from '../../inventory.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { TranslatePipe } from '../../core/i18n/translate.pipe';
@Component({standalone:true,imports:[RouterLink,TranslatePipe],templateUrl:'./operations.component.html'})
export class OperationsComponent implements OnInit, OnDestroy {
  readonly i18n=inject(I18nService);readonly api=inject(WorkspaceService);readonly state=signal<ApiDiagnostics|null>(null);readonly alerts=signal<ApiAlerts|null>(null);
  readonly error=signal('');readonly loading=signal(false);readonly dateText=(value:string|null)=>this.i18n.dateText(value);readonly grams=(value:number)=>this.i18n.grams(value);
  private readonly requests=new RequestOwner();
  ngOnInit():void{void this.refresh();}ngOnDestroy():void{this.requests.invalidate();}
  @HostListener('window:focus') onFocus():void{void this.refresh();}
  bytes(value:number|null):string{
    if(value===null)return '—';
    const amount=value<1024*1024?value/1024:value/(1024*1024);
    return this.i18n.number(amount,{minimumFractionDigits:1,maximumFractionDigits:1})+(value<1024*1024?' KiB':' MiB');
  }
  commandLabel(action:string):string{
    return this.i18n.t(({pause:'Pause print',resume:'Resume print',cancel:'Cancel print'} as Record<string,string>)[action]??action);
  }
  alertMessage(alert:ApiAlerts['alerts'][number]):string{
    if(alert.category==='job_review')return this.i18n.t('Review actual material usage for print job #{id}.',{id:alert.entity_id});
    if(alert.category==='printer_offline')return this.i18n.t('Printer #{id} could not be observed in at least three consecutive polling attempts.',{id:alert.entity_id});
    const match=/^Spool #(\d+) has (\d+) g remaining \(threshold (\d+) g\)\.$/.exec(alert.message);
    if(alert.category==='low_stock'&&match)return this.i18n.t('Spool #{id} has {remaining} remaining (threshold {threshold}).',{
      id:match[1],remaining:this.i18n.grams(Number(match[2])),threshold:this.i18n.grams(Number(match[3]))
    });
    return this.i18n.t(alert.message);
  }
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
