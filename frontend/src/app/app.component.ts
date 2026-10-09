import { Component, DestroyRef, HostListener, OnInit, effect, inject, signal, untracked } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter } from 'rxjs';
import { DialogService, NoticeService } from './dialog.service';
import { InventoryService, apiError } from './inventory.service';
import { DialogsComponent } from './dialogs.component';
import { AuthService } from './auth.service';
import { LoginComponent } from './login.component';
import { I18nService, LanguagePickerComponent, TranslatePipe } from './core/i18n';

@Component({selector: 'fm-root', standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, DialogsComponent, LoginComponent, LanguagePickerComponent, TranslatePipe],
  templateUrl: './app.component.html'})
export class AppComponent implements OnInit {
  readonly i18n = inject(I18nService);
  readonly inventory = inject(InventoryService);
  readonly auth = inject(AuthService);
  readonly dialogs = inject(DialogService);
  readonly notices = inject(NoticeService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  readonly navOpen = signal(false);
  readonly dateText=(value: string | null | undefined)=>this.i18n.dateText(value);
  roleLabel(role: string | undefined): string {
    return this.i18n.t(({admin: 'Admin', editor: 'Editor', viewer: 'Viewer'} as Record<string, string>)[role ?? ''] ?? role ?? '');
  }
  private wasSignedIn=false;
  readonly year = new Date().getFullYear();
  constructor() {
    effect(() => {
      const signedIn=!!this.auth.user();
      if (!signedIn) untracked(() => {
        this.dialogs.close();this.inventory.reset();this.notices.clear();
        if(this.wasSignedIn&&!this.router.url.startsWith('/login'))void this.router.navigate(['/login'],{queryParams:{returnUrl:this.router.url}});
      });
      this.wasSignedIn=signedIn;
    });
    this.router.events.pipe(filter(event => event instanceof NavigationEnd), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => { void this.refreshInventory(); this.closeNav(); });
  }
  async ngOnInit(): Promise<void> {
    try { await this.auth.ensureReady(); } catch { return; }
    if (this.auth.user()) await this.afterLogin();
  }
  async retryAuthentication(): Promise<void> {
    try { await this.auth.init(); if (this.auth.user()) await this.afterLogin(); } catch { /* AuthService shows the error. */ }
  }
  @HostListener('window:focus')
  async refreshInventory(): Promise<void> {
    if (this.auth.user() && !this.inventory.loading()) await this.inventory.load();
  }
  async afterLogin(): Promise<void> {
    await this.inventory.load();
    const params = new URLSearchParams(window.location.search);
    const returnUrl = params.get('returnUrl');
    const safeReturn=returnUrl?.startsWith('/')&&!returnUrl.startsWith('//')&&!returnUrl.startsWith('/login')?returnUrl:'/';
    const uid = params.get('spool') || new URL(safeReturn,window.location.origin).searchParams.get('spool');
    if (uid) {
      try {
        const spool = await this.inventory.spoolByUid(uid);
        await this.router.navigate(['/spools'], {queryParams: spool.archived_at ? {archived: 'archived'} : {}});
        this.dialogs.open({kind: 'details', id: spool.id, spool});
      } catch (error) { this.notices.show(apiError(error), true); }
    } else if (this.router.url.startsWith('/login')) {
      // Only an application-relative path may be resumed after authentication.
      await this.router.navigateByUrl(safeReturn);
    }
  }
  openSpool(): void {
    if (!this.inventory.products().length) {
      this.notices.show('Create a filament product before registering a spool.'); this.dialogs.open({kind: 'product'});
    } else this.dialogs.open({kind: 'spool'});
  }
  closeNav(): void { this.navOpen.set(false); }
}
