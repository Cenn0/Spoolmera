import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { describe, expect, it } from 'vitest';
import { adminGuard, authenticatedGuard, editorGuard } from './route-guards';
import { AccessDeniedComponent, LoginRouteComponent } from './access-denied.component';
import { UsersComponent } from '../features/administration/administration.component';
import { AuthService } from '../auth.service';
import { authMock } from '../testing/fixtures';

describe('role-aware deep links',()=>{
  for(const role of ['viewer','editor'] as const)it('redirects '+role+' away from user administration before constructing it',async()=>{
    TestBed.configureTestingModule({providers:[{provide:AuthService,useValue:authMock(role)},provideRouter([
      {path:'users',component:UsersComponent,canActivate:[adminGuard]},
      {path:'access-denied',component:AccessDeniedComponent},
    ])]});
    const harness=await RouterTestingHarness.create('/users');expect(TestBed.inject(Router).url).toBe('/access-denied');expect(harness.routeNativeElement?.textContent).toContain('Access');
  });
  it('blocks a viewer deep link to editor-only operations',async()=>{
    TestBed.configureTestingModule({providers:[{provide:AuthService,useValue:authMock('viewer')},provideRouter([
      {path:'diagnostics',component:UsersComponent,canActivate:[editorGuard]},{path:'access-denied',component:AccessDeniedComponent},
    ])]});await RouterTestingHarness.create('/diagnostics');expect(TestBed.inject(Router).url).toBe('/access-denied');
  });
  it('preserves the exact application return URL when a protected session is missing',async()=>{
    const auth=authMock('viewer');auth.user.set(null);
    TestBed.configureTestingModule({providers:[{provide:AuthService,useValue:auth},provideRouter([
      {path:'spools',component:UsersComponent,canActivate:[authenticatedGuard]},{path:'login',component:LoginRouteComponent},
    ])]});await RouterTestingHarness.create('/spools?archived=archived');const router=TestBed.inject(Router);
    expect(router.parseUrl(router.url).queryParams['returnUrl']).toBe('/spools?archived=archived');expect(router.url).toContain('/login?');
  });
});
