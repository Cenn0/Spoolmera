import { DOCUMENT } from '@angular/common';
import { DestroyRef, Injectable, inject, signal } from '@angular/core';

export type ThemePreference = 'system' | 'light' | 'dark';
export const THEME_KEY = 'filament-manager-theme';
export function themePreference(value: unknown): ThemePreference {
  return value === 'light' || value === 'dark' ? value : 'system';
}

/** Presentation-only state; never changes an account, API request or inventory. */
@Injectable({providedIn: 'root'})
export class ThemeService {
  private readonly document = inject(DOCUMENT);
  private readonly destroy = inject(DestroyRef);
  private readonly window = this.document.defaultView;
  private readonly media = this.window?.matchMedia?.('(prefers-color-scheme: dark)');
  readonly preference = signal<ThemePreference>('system');
  readonly dark = signal(false);

  constructor() {
    try { this.preference.set(themePreference(this.window?.localStorage.getItem(THEME_KEY))); }
    catch { /* Restricted storage must not prevent rendering. */ }
    const onSystemChange = () => this.apply();
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_KEY || event.key === null) {
        this.preference.set(themePreference(event.newValue));
        this.apply();
      }
    };
    this.media?.addEventListener('change', onSystemChange);
    this.window?.addEventListener('storage', onStorage);
    this.destroy.onDestroy(() => {
      this.media?.removeEventListener('change', onSystemChange);
      this.window?.removeEventListener('storage', onStorage);
    });
    this.apply();
  }

  setPreference(value: string): void {
    if (!['system', 'light', 'dark'].includes(value)) return;
    this.preference.set(themePreference(value));
    try { this.window?.localStorage.setItem(THEME_KEY, value); }
    catch { /* Use in-memory preference when persistence is blocked. */ }
    this.apply();
  }

  private apply(): void {
    const dark = this.preference() === 'dark' || (this.preference() === 'system' && !!this.media?.matches);
    this.dark.set(dark);
    this.document.documentElement.dataset['theme'] = dark ? 'dark' : 'light';
    this.document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }
}
