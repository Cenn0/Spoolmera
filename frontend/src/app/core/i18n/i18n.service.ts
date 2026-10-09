import { DOCUMENT } from '@angular/common';
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { dateText, grams, money } from '../../models';
import { DE, translateKnownError } from './translations';
import { LANGUAGE_STORAGE_KEY, Language, LocalizedMessage, MessageParams, MessageValue, browserLanguage, supportedLanguage } from './types';

@Injectable({providedIn: 'root'})
export class I18nService {
  private readonly document = inject(DOCUMENT);
  private readonly destroy = inject(DestroyRef);
  private readonly window = this.document.defaultView;
  private readonly selected = signal<Language>(this.initialLanguage());
  readonly language = this.selected.asReadonly();
  readonly locale = computed(() => this.language() === 'de' ? 'de-DE' : 'en-US');

  constructor() {
    this.updateDocument();
    const onStorage = (event: StorageEvent): void => {
      if (event.key !== LANGUAGE_STORAGE_KEY) return;
      const language = supportedLanguage(event.newValue);
      if (event.newValue !== null && !language) return;
      this.selected.set(language ?? this.detectBrowserLanguage());
      this.updateDocument();
    };
    this.window?.addEventListener('storage', onStorage);
    this.destroy.onDestroy(() => this.window?.removeEventListener('storage', onStorage));
  }

  private detectBrowserLanguage(): Language {
    const navigator = this.window?.navigator;
    return browserLanguage(navigator?.languages?.length ? navigator.languages : [navigator?.language ?? 'en']);
  }

  private initialLanguage(): Language {
    try {
      const stored = supportedLanguage(this.window?.localStorage.getItem(LANGUAGE_STORAGE_KEY));
      if (stored) return stored;
    } catch { /* Storage can be blocked; browser preferences still work. */ }
    try {
      const cookie = this.document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith('fm_language='));
      const saved = supportedLanguage(cookie?.slice('fm_language='.length));
      if (saved) return saved;
    } catch { /* A blocked cookie jar must not block application startup. */ }
    return this.detectBrowserLanguage();
  }

  setLanguage(value: string): void {
    const language = supportedLanguage(value);
    if (!language) return;
    this.selected.set(language);
    this.updateDocument();
    try { this.window?.localStorage.setItem(LANGUAGE_STORAGE_KEY, language); } catch { /* Selection still works for this page. */ }
    try {
      const secure = this.window?.location.protocol === 'https:' ? '; Secure' : '';
      this.document.cookie = `fm_language=${language}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;
    } catch { /* Label pages can fall back to Accept-Language. */ }
  }

  private updateDocument(): void {
    this.document.documentElement.lang = this.language();
    this.document.title = this.t('Filament Manager · Material inventory');
  }

  message(key: string, params?: MessageParams): LocalizedMessage {
    return {key, params: params ? {...params} : undefined};
  }

  t(value: MessageValue | null | undefined, params?: MessageParams): string {
    if (value == null) return '';
    const key = typeof value === 'string' ? value : value.key;
    const arguments_ = typeof value === 'string' ? params : value.params;
    let text = this.language() === 'de' ? (DE[key] ?? translateKnownError(key) ?? key) : key;
    if (arguments_) text = text.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (placeholder, name: string) => {
      const parameter = arguments_[name];
      if (parameter === undefined) return placeholder;
      if (parameter === null) return '';
      return typeof parameter === 'object' ? this.t(parameter) : typeof parameter === 'number' ? this.number(parameter) : String(parameter);
    });
    return text;
  }

  number(value: number, options?: Intl.NumberFormatOptions): string {
    return Number.isFinite(value) ? new Intl.NumberFormat(this.locale(), options).format(value) : '—';
  }
  grams(value: number): string { return grams(value, this.locale()); }
  dateText(value: string | null | undefined): string { return dateText(value, this.locale()); }
  dateOnly(value: string | null | undefined): string {
    if (!value) return '—';
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!match || Number.isNaN(Date.parse(value))) return '—';
    return this.language() === 'de' ? `${match[3]}.${match[2]}.${match[1]}` : value;
  }
  money(cents: number | null | undefined, currency: string): string {
    return cents == null ? this.t('Not recorded') : money(cents, currency, this.locale());
  }
}
