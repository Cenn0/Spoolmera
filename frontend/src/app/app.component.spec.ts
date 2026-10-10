import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { Subject } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppComponent } from './app.component';
import { AuthService } from './auth.service';
import { DialogService, NoticeService } from './dialog.service';
import { InventoryService } from './inventory.service';
import { authMock, inventoryMock, spool } from './testing/fixtures';

describe('startup spool links and route-specific filters', () => {
  let data: ReturnType<typeof inventoryMock>;
  let previousUrl: string;
  const router = {url: '/', events: new Subject(), navigate: vi.fn(), navigateByUrl: vi.fn()};
  const dialogs = {open: vi.fn(), close: vi.fn()};
  const notices = {show: vi.fn(), clear: vi.fn()};

  beforeEach(() => {
    previousUrl = window.location.href;
    data = inventoryMock();
    vi.clearAllMocks();
    router.navigate.mockResolvedValue(true);
    router.navigateByUrl.mockResolvedValue(true);
    TestBed.configureTestingModule({providers: [
      {provide: InventoryService, useValue: data},
      {provide: AuthService, useValue: authMock('editor')},
      {provide: Router, useValue: router},
      {provide: DialogService, useValue: dialogs},
      {provide: NoticeService, useValue: notices},
    ]});
    TestBed.overrideComponent(AppComponent, {set: {template: '', imports: []}});
  });

  afterEach(() => window.history.replaceState(null, '', previousUrl));

  async function open(path: string): Promise<void> {
    window.history.replaceState(null, '', path);
    router.url = path;
    await TestBed.createComponent(AppComponent).componentInstance.afterLogin();
  }

  for (const filter of ['17', spool().uid]) {
    it('leaves the history spool filter in its own route on direct load: ' + filter, async () => {
      const path = '/history?spool=' + filter;
      await open(path);
      expect(data.spoolByUid).not.toHaveBeenCalled();
      expect(dialogs.open).not.toHaveBeenCalled();
      expect(notices.show).not.toHaveBeenCalled();
      expect(router.navigate).not.toHaveBeenCalled();
      expect(router.navigateByUrl).not.toHaveBeenCalled();
      expect(window.location.pathname + window.location.search).toBe(path);
    });
  }

  it('resumes a numeric history filter after login without a UUID lookup or error', async () => {
    const target = '/history?spool=17&source=manual';
    await open('/login?returnUrl=' + encodeURIComponent(target));
    expect(data.spoolByUid).not.toHaveBeenCalled();
    expect(dialogs.open).not.toHaveBeenCalled();
    expect(notices.show).not.toHaveBeenCalled();
    expect(router.navigateByUrl).toHaveBeenCalledWith(target);
  });

  it('opens an existing active root QR link after an authenticated page load', async () => {
    const physicalSpool = spool();
    await open('/?spool=' + physicalSpool.uid);
    expect(data.spoolByUid).toHaveBeenCalledWith(physicalSpool.uid);
    expect(router.navigate).toHaveBeenCalledWith(['/spools'], {queryParams: {}});
    expect(dialogs.open).toHaveBeenCalledWith({kind: 'details', id: physicalSpool.id, spool: physicalSpool});
  });

  it('resumes an archived root QR link after login with the archived inventory filter', async () => {
    const archived = spool({archived_at: '2026-10-01T10:00:00Z'});
    data.spoolByUid.mockResolvedValue(archived);
    await open('/login?returnUrl=' + encodeURIComponent('/?spool=' + archived.uid));
    expect(data.spoolByUid).toHaveBeenCalledWith(archived.uid);
    expect(router.navigate).toHaveBeenCalledWith(['/spools'], {queryParams: {archived: 'archived'}});
    expect(dialogs.open).toHaveBeenCalledWith({kind: 'details', id: archived.id, spool: archived});
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });
});
