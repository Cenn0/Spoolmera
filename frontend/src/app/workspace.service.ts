import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ManagedUser } from './auth.service';

export interface Printer {
  id:number; name:string; kind:'moonraker'|'octoprint'; base_url:string;
  token_env:string; enabled:number; created_at:string;
}
export interface JobMaterial {
  tool:number; spool_id:number;estimated_g:number;movement_id:number|null;
  spool_uid:string;brand:string;product_name:string;
}
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
export interface PrintJob {
  id:number; printer_id:number;printer_name:string;spool_id:number;spool_uid:string;
  brand:string;product_name:string;file_name:string;estimated_g:number;
  status:'pending'|'printing'|'completed'|'needs_review'|'cancelled';
  movement_id:number|null;note:string;external_job_id:string|null;created_at:string;
  start_command_state:PrinterCommand['state']|null;
  materials:JobMaterial[];
}
export interface JobReadiness {
  job_id:number;status:string;ready:boolean;reserved:boolean;
  materials:{tool:number;spool_id:number;estimated_g:number;remaining_g:number;
    available_g:number;others_reserved_g:number;own_reservation_g:number|null;
    brand:string;product_name:string;ready:boolean;loaded_match:boolean}[];
}
export interface PrinterSlot {tool:number;spool_id:number;spool_uid:string;brand:string;product_name:string;}
export interface FileInspection {
  file_stored:boolean;verified:boolean;source:string;needs_manual_estimate:boolean;
  plates:{plate:number;materials:{tool:number;estimated_g:number}[]}[];
}
export interface PrinterInput {name:string;kind:string;base_url:string;token_env:string;enabled:boolean;}
@Injectable({providedIn:'root'})
export class WorkspaceService {
  private readonly http=inject(HttpClient);
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
  createMultiJob(body:{printer_id:number;file_name:string;note:string;
    materials:{tool:number;spool_id:number;estimated_g:number}[]}):Promise<{id:number}>{
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
