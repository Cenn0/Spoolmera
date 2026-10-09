import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { catchError, firstValueFrom, throwError } from 'rxjs';

export interface CurrentUser { id:number; username:string; role:'admin'|'editor'|'viewer'; csrf_token:string }
export interface ManagedUser { id:number; username:string; role:'admin'|'editor'|'viewer'; enabled:number; created_at:string }
const csrfHeader = signal('');

export const csrfInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const protectedApi = request.url.startsWith('/api/') &&
    !/^\/api\/auth\/(login|setup|status)$/.test(request.url) && request.url !== '/api/health';
  if (request.url.startsWith('/api/') &&
      !/^\/api\/auth\/(login|setup)$/.test(request.url) &&
      !['GET','HEAD','OPTIONS'].includes(request.method) && csrfHeader()) {
    request = request.clone({setHeaders:{'X-CSRF-Token':csrfHeader()}});
  }
  return next(request).pipe(catchError((error: unknown) => {
    if (protectedApi && error instanceof HttpErrorResponse && error.status === 401) auth.clear();
    return throwError(() => error);
  }));
};

@Injectable({providedIn:'root'})
export class AuthService {
  private readonly http=inject(HttpClient);
  readonly ready=signal(false);
  readonly error=signal('');
  readonly signingOut=signal(false);
  private initialization:Promise<void>|null=null;
  ensureReady():Promise<void>{return this.ready()?Promise.resolve():(this.initialization ||= this.init());}
  readonly needsSetup=signal(false);
  readonly user=signal<CurrentUser|null>(null);
  readonly isAdmin=computed(()=>this.user()?.role==='admin');
  readonly canEdit=computed(()=>this.user()?.role!=='viewer' && !!this.user());
  async init():Promise<void> {
    this.error.set('');
    try {
      const status=await firstValueFrom(this.http.get<{needs_setup:boolean}>('/api/auth/status'));
      this.needsSetup.set(status.needs_setup);
      if(!status.needs_setup) {
        try {
          this.accept(await firstValueFrom(this.http.get<CurrentUser>('/api/auth/me')));
        } catch(error) {
          if(!(error instanceof HttpErrorResponse && error.status===401)) throw error;
        }
      }
    } catch(error) {
      this.error.set(error instanceof HttpErrorResponse && error.status===0 ? 'Unable to reach the server. Retry loading the sign-in page.' : 'Authentication is unavailable. Retry loading the sign-in page.');
      throw error;
    } finally { this.ready.set(true); }
  }
  private accept(user:CurrentUser):void {
    this.error.set('');
    csrfHeader.set(user.csrf_token);
    this.user.set(user);
    this.needsSetup.set(false);
  }
  async setup(username:string,password:string,token:string):Promise<void> {
    const user=await firstValueFrom(this.http.post<CurrentUser>('/api/auth/setup',
      {username,password},{headers:{'X-Bootstrap-Token':token}}));
    this.accept(user);
  }
  async login(username:string,password:string):Promise<void> {
    this.accept(await firstValueFrom(this.http.post<CurrentUser>('/api/auth/login',{username,password})));
  }
  async logout():Promise<void> {
    if(this.signingOut())return;
    this.signingOut.set(true);this.error.set('');
    try{await firstValueFrom(this.http.post('/api/auth/logout',{}));this.clear();}
    catch{this.error.set('Sign out could not be confirmed. Check the connection and retry.');}
    finally{this.signingOut.set(false);}
  }
  clear():void {csrfHeader.set('');this.user.set(null);}
  async password(old_password:string,new_password:string):Promise<void>{
    const result=await firstValueFrom(this.http.post<{csrf_token:string}>('/api/auth/password',{old_password,new_password}));
    csrfHeader.set(result.csrf_token);
    const user=this.user();if(user)this.user.set({...user,csrf_token:result.csrf_token});
  }
}

