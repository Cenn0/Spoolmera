import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ManagedUser } from './auth.service';

export interface Printer {
  id:number; name:string; kind:'moonraker'|'octoprint'; base_url:string;
  token_env:string; enabled:number; created_at:string;
}
export interface PrintJob {
  id:number; printer_id:number;printer_name:string;spool_id:number;spool_uid:string;
  brand:string;product_name:string;file_name:string;estimated_g:number;
  status:'pending'|'printing'|'completed'|'needs_review'|'cancelled';
  movement_id:number|null;note:string;external_job_id:string|null;created_at:string;
}
export interface PrinterInput {name:string;kind:string;base_url:string;token_env:string;enabled:boolean;}
@Injectable({providedIn:'root'})
export class WorkspaceService {
  private readonly http=inject(HttpClient);
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
