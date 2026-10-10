import { Routes } from '@angular/router';
import { authenticatedGuard, adminGuard, editorGuard } from './core/route-guards';

export const routes: Routes = [
  {path: 'login', loadComponent: () => import('./core/access-denied.component').then(m => m.LoginRouteComponent), title: 'Sign in — Spoolmera'},
  {path: '', canActivate: [authenticatedGuard], canActivateChild: [authenticatedGuard], children: [
    {path: '', loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent), title: 'Overview — Spoolmera'},
    {path: 'spools', loadComponent: () => import('./features/spools/spools.component').then(m => m.SpoolsComponent), title: 'Spools — Spoolmera'},
    {path: 'spools/batch', canActivate: [editorGuard], loadComponent: () => import('./features/spools/batch-spools.component').then(m => m.BatchSpoolsComponent), title: 'Register rolls — Spoolmera'},
    {path: 'import/spoolman', canActivate: [editorGuard], loadComponent: () => import('./features/import/spoolman-import.component').then(m => m.SpoolmanImportComponent), title: 'Spoolman import — Spoolmera'},
    {path: 'catalog', loadComponent: () => import('./features/catalog/catalog.component').then(m => m.CatalogComponent), title: 'Material catalog — Spoolmera'},
    {path: 'filaments', loadComponent: () => import('./features/filaments/filaments.component').then(m => m.ProductsComponent), title: 'Filaments — Spoolmera'},
    {path: 'history', loadComponent: () => import('./features/history/history.component').then(m => m.HistoryComponent), title: 'History — Spoolmera'},
    {path: 'restock', loadComponent: () => import('./features/restock/restock.component').then(m => m.RestockComponent), title: 'Restock — Spoolmera'},
    {path: 'integrations', loadComponent: () => import('./features/integrations/integrations.component').then(m => m.IntegrationsComponent), title: 'Integrations — Spoolmera'},
    {path: 'jobs', loadComponent: () => import('./features/print-jobs/print-jobs.component').then(m => m.JobsComponent), title: 'Print jobs — Spoolmera'},
    {path: 'printers', loadComponent: () => import('./features/printers/printers.component').then(m => m.PrintersComponent), title: 'Printers — Spoolmera'},
    {path: 'diagnostics', canActivate: [editorGuard], loadComponent: () => import('./features/operations/operations.component').then(m => m.OperationsComponent), title: 'Operations — Spoolmera'},
    {path: 'users', canActivate: [adminGuard], loadComponent: () => import('./features/administration/administration.component').then(m => m.UsersComponent), title: 'Users — Spoolmera'},
    {path: 'account', loadComponent: () => import('./features/account/account.component').then(m => m.AccountComponent), title: 'Account — Spoolmera'},
    {path: 'access-denied', loadComponent: () => import('./core/access-denied.component').then(m => m.AccessDeniedComponent), title: 'Access restricted — Spoolmera'},
  ]},
  {path: '**', redirectTo: ''},
];
