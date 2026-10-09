import { Routes } from '@angular/router';
import { authenticatedGuard, adminGuard, editorGuard } from './core/route-guards';

export const routes: Routes = [
  {path: 'login', loadComponent: () => import('./core/access-denied.component').then(m => m.LoginRouteComponent), title: 'Sign in — Filament Manager'},
  {path: '', canActivate: [authenticatedGuard], canActivateChild: [authenticatedGuard], children: [
    {path: '', loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent), title: 'Overview — Filament Manager'},
    {path: 'spools', loadComponent: () => import('./features/spools/spools.component').then(m => m.SpoolsComponent), title: 'Spools — Filament Manager'},
    {path: 'spools/batch', canActivate: [editorGuard], loadComponent: () => import('./features/spools/batch-spools.component').then(m => m.BatchSpoolsComponent), title: 'Register rolls — Filament Manager'},
    {path: 'import/spoolman', canActivate: [editorGuard], loadComponent: () => import('./features/import/spoolman-import.component').then(m => m.SpoolmanImportComponent), title: 'Spoolman import — Filament Manager'},
    {path: 'catalog', loadComponent: () => import('./features/catalog/catalog.component').then(m => m.CatalogComponent), title: 'Material catalog — Filament Manager'},
    {path: 'filaments', loadComponent: () => import('./features/filaments/filaments.component').then(m => m.ProductsComponent), title: 'Filaments — Filament Manager'},
    {path: 'history', loadComponent: () => import('./features/history/history.component').then(m => m.HistoryComponent), title: 'History — Filament Manager'},
    {path: 'restock', loadComponent: () => import('./features/restock/restock.component').then(m => m.RestockComponent), title: 'Restock — Filament Manager'},
    {path: 'integrations', loadComponent: () => import('./features/integrations/integrations.component').then(m => m.IntegrationsComponent), title: 'Integrations — Filament Manager'},
    {path: 'jobs', loadComponent: () => import('./features/print-jobs/print-jobs.component').then(m => m.JobsComponent), title: 'Print jobs — Filament Manager'},
    {path: 'printers', loadComponent: () => import('./features/printers/printers.component').then(m => m.PrintersComponent), title: 'Printers — Filament Manager'},
    {path: 'diagnostics', canActivate: [editorGuard], loadComponent: () => import('./features/operations/operations.component').then(m => m.OperationsComponent), title: 'Operations — Filament Manager'},
    {path: 'users', canActivate: [adminGuard], loadComponent: () => import('./features/administration/administration.component').then(m => m.UsersComponent), title: 'Users — Filament Manager'},
    {path: 'account', loadComponent: () => import('./features/account/account.component').then(m => m.AccountComponent), title: 'Account — Filament Manager'},
    {path: 'access-denied', loadComponent: () => import('./core/access-denied.component').then(m => m.AccessDeniedComponent), title: 'Access restricted — Filament Manager'},
  ]},
  {path: '**', redirectTo: ''},
];
