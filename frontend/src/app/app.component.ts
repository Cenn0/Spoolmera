import { Component, OnInit, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { DialogService, NoticeService } from './dialog.service';
import { InventoryService } from './inventory.service';
import { DialogsComponent } from './dialogs.component';
import { AuthService } from './auth.service';
import { LoginComponent } from './login.component';
import { apiError } from './inventory.service';

@Component({
  selector: 'fm-root',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, DialogsComponent, LoginComponent],
  templateUrl: './app.component.html'
})
export class AppComponent implements OnInit {
  readonly inventory = inject(InventoryService);
  readonly auth = inject(AuthService);
  readonly dialogs = inject(DialogService);
  readonly notices = inject(NoticeService);
  private readonly router = inject(Router);
  readonly navOpen = signal(false);
  readonly year = new Date().getFullYear();

  async ngOnInit(): Promise<void> {
    try { await this.auth.init(); }
    catch(error) { this.notices.show('Authentication unavailable: '+apiError(error), true); }
    if (this.auth.user()) await this.afterLogin();
  }
  async afterLogin(): Promise<void> {
    await this.inventory.load();
    const uid = new URLSearchParams(window.location.search).get('spool');
    if (uid) {
      window.history.replaceState(null, '', window.location.pathname);
      const spool = this.inventory.spools().find(item => item.uid === uid);
      if (spool) {
        await this.router.navigateByUrl('/spools');
        this.dialogs.open({kind: 'details', id: spool.id});
      } else {
        this.notices.show('This spool is unavailable or archived.', true);
      }
    }
  }
  openSpool(): void {
    if (!this.inventory.products().length) {
      this.notices.show('Create a filament product before registering a spool.');
      this.dialogs.open({kind:'product'});
    } else {
      this.dialogs.open({kind:'spool'});
    }
  }
  closeNav(): void { this.navOpen.set(false); }
}
