import { Routes } from '@angular/router';
import { DashboardComponent, SpoolsComponent, ProductsComponent, HistoryComponent, IntegrationsComponent } from './pages';

export const routes: Routes = [
  {path: '', component: DashboardComponent, title: 'Overview — Filament Manager'},
  {path: 'spools', component: SpoolsComponent, title: 'Spools — Filament Manager'},
  {path: 'filaments', component: ProductsComponent, title: 'Filaments — Filament Manager'},
  {path: 'history', component: HistoryComponent, title: 'History — Filament Manager'},
  {path: 'integrations', component: IntegrationsComponent, title: 'Integrations — Filament Manager'},
  {path: '**', redirectTo: ''},
];
