import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ManagedUser } from './auth.service';
import { ApiJob, ApiPrinter, ApiJobMaterial, ApiMultiJobInput, ApiDiagnostics, ApiAlerts, ApiSlot, ApiReadiness, ApiInspection, ApiPrinterOperation, ApiScaleMeasurement } from './core/api/generated-contracts';
import { ConsumptionSnapshot, ConsumptionInput, ConsumptionResult } from './features/print-jobs/consumption-contracts';

export type Printer = ApiPrinter;
export type JobMaterial = ApiJobMaterial;
export interface CloudReceipt {
  source:string;event_id:string;job_id:number;disposition:string;received_at:string;
}
export interface SliceProfiles {enabled:boolean;profiles:string[];}
export interface PrinterCapabilities {write_enabled:boolean;max_upload_bytes:number;}
export interface PrinterCommand {
  id:string;action:'start'|'pause'|'resume'|'cancel';
  state:'sending'|'acknowledged'|'unknown'|'rejected'|'confirmed'|'cleared';
  http_status:number|null;detail:string;created_at:string;updated_at:string;
}
export type PrintJob = ApiJob;
export type JobReadiness=ApiReadiness;
export type PrinterSlot=ApiSlot;
export type FileInspection=ApiInspection;
export type PrinterOperation=ApiPrinterOperation;
export interface AutomationToken {id:number;label:string;scope:'inventory_read'|'events_read';
  created_at:string;revoked_at:string|null;}
export interface IssuedToken {id:number;label:string;scope:'inventory_read'|'events_read';token:string;warning:string;}
export type ScaleMeasurement=ApiScaleMeasurement;
export interface PrinterInput {name:string;kind:string;base_url:string;token_env:string;enabled:boolean;}
@Injectable({providedIn:'root'})
export class WorkspaceService {
  private readonly http=inject(HttpClient);
  alerts():Promise<ApiAlerts>{return firstValueFrom(this.http.get<ApiAlerts>('/api/alerts'));}
  printerOperations(id:number):Promise<PrinterOperation[]>{return firstValueFrom(this.http.get<PrinterOperation[]>('/api/printers/'+id+'/operations'));}
  clearUploadOperation(printerId:number,operationId:string,reason:string):Promise<void>{return firstValueFrom(this.http.post<void>('/api/printers/'+printerId+'/operations/'+encodeURIComponent(operationId)+'/clear',{reason}));}
  diagnostics():Promise<ApiDiagnostics>{return firstValueFrom(this.http.get<ApiDiagnostics>('/api/diagnostics'));}
  consumption(id:number):Promise<ConsumptionSnapshot>{return firstValueFrom(this.http.get<ConsumptionSnapshot>('/api/jobs/'+id+'/consumption'));}
  reconcileConsumption(id:number,body:ConsumptionInput):Promise<ConsumptionResult>{return firstValueFrom(this.http.post<ConsumptionResult>('/api/jobs/'+id+'/consumption',body));}
  printerCapabilities():Promise<PrinterCapabilities>{
    return firstValueFrom(this.http.get<PrinterCapabilities>('/api/printers/capabilities'));
  }
  cloudEvents():Promise<CloudReceipt[]> {
    return firstValueFrom(this.http.get<CloudReceipt[]>('/api/cloud/events'));
  }
  slicerProfiles():Promise<SliceProfiles>{
    return firstValueFrom(this.http.get<SliceProfiles>('/api/slicing/profiles'));
  }
  async sliceStl(file:File,profile:string):Promise<{content:Blob;estimated:string|null}>{
    const response=await firstValueFrom(this.http.post('/api/slicing/slice?profile='+encodeURIComponent(profile),
      file,{observe:'response',responseType:'blob',
            headers:new HttpHeaders({'Content-Type':'application/octet-stream'})}));
    return {content:response.body || new Blob(),estimated:response.headers.get('X-Estimated-Grams')};
  }
  async uploadJob(jobId:number,file:File):Promise<void>{
    await firstValueFrom(this.http.post('/api/jobs/'+jobId+'/upload?file_name='+encodeURIComponent(file.name),
      file,{headers:new HttpHeaders({'Content-Type':'application/octet-stream'})}));
  }
  jobCommands(jobId:number):Promise<PrinterCommand[]>{
    return firstValueFrom(this.http.get<PrinterCommand[]>('/api/jobs/'+jobId+'/commands'));
  }
  clearPrinterCommand(id:string,reason:string):Promise<void>{
    return firstValueFrom(this.http.post<void>('/api/printers/commands/'+encodeURIComponent(id)+'/clear',{reason}));
  }
  startJob(jobId:number):Promise<void>{
    return firstValueFrom(this.http.post<void>('/api/jobs/'+jobId+'/start',{}));
  }
  controlPrinter(printerId:number,action:'pause'|'resume'|'cancel'):Promise<void>{
    return firstValueFrom(this.http.post<void>('/api/printers/'+printerId+'/control',{action}));
  }
  createMultiJob(body:ApiMultiJobInput):Promise<{id:number}>{
    return firstValueFrom(this.http.post<{id:number}>('/api/jobs/multi',body));
  }
  readiness(jobId:number):Promise<JobReadiness> {
    return firstValueFrom(this.http.get<JobReadiness>('/api/jobs/'+jobId+'/readiness'));
  }
  reserve(jobId:number):Promise<JobReadiness> {
    return firstValueFrom(this.http.post<JobReadiness>('/api/jobs/'+jobId+'/reservation',{}));
  }
  release(jobId:number):Promise<JobReadiness> {
    return firstValueFrom(this.http.delete<JobReadiness>('/api/jobs/'+jobId+'/reservation'));
  }
  printerSlots(printerId:number):Promise<PrinterSlot[]> {
    return firstValueFrom(this.http.get<PrinterSlot[]>('/api/printers/'+printerId+'/slots'));
  }
  assignSlot(printerId:number,tool:number,spoolId:number):Promise<void> {
    return firstValueFrom(this.http.put<void>('/api/printers/'+printerId+'/slots/'+tool,
      {spool_id:spoolId}));
  }
  unloadSlot(printerId:number,tool:number):Promise<void> {
    return firstValueFrom(this.http.delete<void>('/api/printers/'+printerId+'/slots/'+tool));
  }
  inspectFile(file:File):Promise<FileInspection> {
    return firstValueFrom(this.http.post<FileInspection>(
      '/api/jobs/inspect?name='+encodeURIComponent(file.name),file,
      {headers:new HttpHeaders({'Content-Type':'application/octet-stream'})}));
  }
  automationTokens():Promise<AutomationToken[]>{
    return firstValueFrom(this.http.get<AutomationToken[]>('/api/admin/automation-tokens'));
  }
  createAutomationToken(label:string,scope:'inventory_read'|'events_read'):Promise<IssuedToken>{
    return firstValueFrom(this.http.post<IssuedToken>('/api/admin/automation-tokens',{label,scope}));
  }
  revokeAutomationToken(id:number):Promise<void>{
    return firstValueFrom(this.http.delete<void>('/api/admin/automation-tokens/'+id));
  }
  scaleMeasurements():Promise<ScaleMeasurement[]>{
    return firstValueFrom(this.http.get<ScaleMeasurement[]>('/api/scales/measurements'));
  }
  reviewScale(id:number,action:'approve'|'discard',note:string):Promise<void>{
    return firstValueFrom(this.http.post<void>('/api/scales/measurements/'+id+'/review',{action,note}));
  }
  printers():Promise<Printer[]> {return firstValueFrom(this.http.get<Printer[]>('/api/printers'));}
  jobs():Promise<PrintJob[]> {return firstValueFrom(this.http.get<PrintJob[]>('/api/jobs'));}
  users():Promise<ManagedUser[]> {return firstValueFrom(this.http.get<ManagedUser[]>('/api/auth/users'));}
  addPrinter(body:PrinterInput):Promise<{id:number}> {
    return firstValueFrom(this.http.post<{id:number}>('/api/printers',body));
  }
  updatePrinter(id:number,body:PrinterInput):Promise<{id:number}>{
    return firstValueFrom(this.http.put<{id:number}>('/api/printers/'+id,body));
  }
  probe(id:number):Promise<{state:string;filename:string}> {
    return firstValueFrom(this.http.post<{state:string;filename:string}>('/api/printers/'+id+'/probe',{}));
  }
  poll(id:number):Promise<{state:string;filename:string;updated_jobs:number}>{
    return firstValueFrom(this.http.post<{state:string;filename:string;updated_jobs:number}>('/api/printers/'+id+'/poll',{}));
  }
  createJob(body:{printer_id:number;spool_id:number;file_name:string;estimated_g:number;note:string}):Promise<{id:number}>{
    return firstValueFrom(this.http.post<{id:number}>('/api/jobs',body));
  }
  importJob(file:File,printer_id:number,spool_id:number,estimated_g:number|null):Promise<{id:number;estimated_g:number}>{
    const params=new URLSearchParams({printer_id:String(printer_id),spool_id:String(spool_id),file_name:file.name});
    if(estimated_g)params.set('estimated_g',String(estimated_g));
    return firstValueFrom(this.http.post<{id:number;estimated_g:number}>('/api/jobs/import?'+params,
      file,{headers:new HttpHeaders({'Content-Type':'application/octet-stream'})}));
  }
  resolveJob(id:number,action:'debit'|'discard'):Promise<{status:string}>{
    return firstValueFrom(this.http.post<{status:string}>('/api/jobs/'+id+'/resolve',{action}));
  }
  cancelJob(id:number):Promise<void>{return firstValueFrom(this.http.post<void>('/api/jobs/'+id+'/cancel',{}));}
  createUser(body:{username:string;password:string;role:string}):Promise<{id:number}>{
    return firstValueFrom(this.http.post<{id:number}>('/api/auth/users',body));
  }
  updateUser(id:number,body:{role?:string;enabled?:boolean;password?:string}):Promise<{id:number}>{
    return firstValueFrom(this.http.patch<{id:number}>('/api/auth/users/'+id,body));
  }
}
