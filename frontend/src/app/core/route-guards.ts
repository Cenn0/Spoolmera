import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../auth.service';

export const authenticatedGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService), router = inject(Router);
  try { await auth.ensureReady(); } catch { /* The sign-in screen exposes the error. */ }
  return auth.user() ? true : router.createUrlTree(['/login'], {queryParams: {returnUrl: state.url}});
};
export const adminGuard: CanActivateFn = async () => {
  const auth = inject(AuthService), router = inject(Router);
  try { await auth.ensureReady(); } catch { return router.createUrlTree(['/login']); }
  return auth.isAdmin() ? true : router.createUrlTree(['/access-denied']);
};
export const editorGuard: CanActivateFn = async () => {
  const auth = inject(AuthService), router = inject(Router);
  try { await auth.ensureReady(); } catch { return router.createUrlTree(['/login']); }
  return auth.canEdit() ? true : router.createUrlTree(['/access-denied']);
};
