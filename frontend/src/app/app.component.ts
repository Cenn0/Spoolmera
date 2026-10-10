import { ThemePickerComponent } from './core/ui/theme-picker.component';
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

@Component({selector: 'sm-root', standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, DialogsComponent, LoginComponent, LanguagePickerComponent, ThemePickerComponent, TranslatePipe],
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
    // QR links are rooted at /?spool=<uid>. Other routes, such as history,
    // use their own spool query parameter and must keep that filter intact.
    const spoolLinkUid = (url: URL): string | null => url.pathname === '/' ? url.searchParams.get('spool') : null;
    const uid = spoolLinkUid(new URL(window.location.href)) || (this.router.url.startsWith('/login')
      ? spoolLinkUid(new URL(safeReturn,window.location.origin)) : null);
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
  private navTrigger: HTMLElement | null = null;
  toggleNav(): void {
    if (this.navOpen()) { this.closeNav(); return; }
    this.navTrigger = document.activeElement as HTMLElement | null;
    this.navOpen.set(true);
    requestAnimationFrame(() => document.querySelector<HTMLElement>('.drawer-close')?.focus());
  }
  closeNav(): void {
    const open = this.navOpen(); this.navOpen.set(false);
    if (open) requestAnimationFrame(() => {
      const target = this.navTrigger?.getClientRects().length ? this.navTrigger : document.querySelector<HTMLElement>('#main-content');
      target?.focus();
    });
  }
  @HostListener('window:resize')
  closeDesktopDrawer(): void { if (this.navOpen() && window.innerWidth > 760) this.closeNav(); }
  @HostListener('document:keydown', ['$event'])
  navigationKeys(event: KeyboardEvent): void {
    if (!this.navOpen()) return;
    if (event.key === 'Escape') { event.preventDefault(); this.closeNav(); }
    if (event.key === 'Tab') {
      const elements = Array.from(document.querySelectorAll<HTMLElement>('.sidebar a, .sidebar button'))
        .filter(element => element.getClientRects().length > 0);
      const first = elements[0], last = elements.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }
  @HostListener('window:dragover', ['$event'])
  @HostListener('window:drop', ['$event'])
  preventFileNavigation(event: DragEvent): void {
    if (Array.from(event.dataTransfer?.types ?? []).includes('Files')) event.preventDefault();
  }
}
