import { Routes } from '@angular/router';
import { JobsComponent, PrintersComponent, UsersComponent, AccountComponent } from './workflow-pages';
import { DashboardComponent, SpoolsComponent, ProductsComponent, HistoryComponent, IntegrationsComponent } from './pages';

export const routes: Routes = [
  {path: '', component: DashboardComponent, title: 'Overview — Filament Manager'},
  {path: 'spools', component: SpoolsComponent, title: 'Spools — Filament Manager'},
  {path: 'filaments', component: ProductsComponent, title: 'Filaments — Filament Manager'},
  {path: 'history', component: HistoryComponent, title: 'History — Filament Manager'},
  {path: 'jobs', component: JobsComponent, title: 'Print jobs — Filament Manager'},
  {path: 'printers', component: PrintersComponent, title: 'Printers — Filament Manager'},
  {path: 'users', component: UsersComponent, title: 'Users — Filament Manager'},
  {path: 'account', component: AccountComponent, title: 'Account — Filament Manager'},
  {path: 'integrations', component: IntegrationsComponent, title: 'Integrations — Filament Manager'},
  {path: '**', redirectTo: ''},
];
