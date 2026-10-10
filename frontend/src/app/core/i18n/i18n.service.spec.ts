import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthService } from '../../auth.service';
import { LoginComponent } from '../../login.component';
import { I18nService } from './i18n.service';
import { TranslatePipe } from './translate.pipe';
import { CATALOGS } from './translations';
import { LANGUAGE_STORAGE_KEY, LocalizedMessage, browserLanguage } from './types';

@Component({standalone:true, imports:[TranslatePipe], template:'<p>{{message | t}}</p>'})
class MessageHost { message: LocalizedMessage = {key:'Welcome {name}',params:{name:'<img src=x onerror=alert(1)>'}}; }

describe('runtime language preferences and rendering', () => {
  beforeEach(() => {
    TestBed.resetTestingModule();
    localStorage.removeItem(LANGUAGE_STORAGE_KEY);
    document.cookie = 'spoolmera_language=; Path=/; Max-Age=0';
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en-US']);
  });
  afterEach(() => {
    TestBed.resetTestingModule();
    vi.restoreAllMocks();
    localStorage.removeItem(LANGUAGE_STORAGE_KEY);
    document.cookie = 'spoolmera_language=; Path=/; Max-Age=0';
    document.documentElement.lang = 'en';
  });

  it('negotiates regional browser languages in order and falls back to English', () => {
    expect(browserLanguage(['fr-FR', 'de-AT', 'en-US'])).toBe('de');
    expect(browserLanguage(['en-GB', 'de-DE'])).toBe('en');
    expect(browserLanguage(['es-ES', 'ja-JP'])).toBe('en');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['de-DE', 'en']);
    expect(TestBed.inject(I18nService).language()).toBe('de');
    expect(document.documentElement.lang).toBe('de');
  });

  it('honors an explicit saved selection and synchronizes document, cookie and storage', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    document.cookie = 'spoolmera_language=de; Path=/';
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['de-DE']);
    const i18n = TestBed.inject(I18nService);
    expect(i18n.language()).toBe('en');
    i18n.setLanguage('de');
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('de');
    expect(document.cookie).toContain('spoolmera_language=de');
    expect(document.documentElement.lang).toBe('de');
    expect(document.title).toContain('Materialbestand');
    i18n.setLanguage('fr');
    expect(i18n.language()).toBe('de');
  });

  it('ignores malformed stored values and supports a valid cookie fallback', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, '<script>');
    document.cookie = 'spoolmera_language=de; Path=/';
    expect(TestBed.inject(I18nService).language()).toBe('de');
  });

  it('still starts and switches if browser storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {throw new DOMException('Blocked', 'SecurityError');});
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {throw new DOMException('Blocked', 'SecurityError');});
    const i18n = TestBed.inject(I18nService);
    expect(i18n.language()).toBe('en');
    expect(() => i18n.setLanguage('de')).not.toThrow();
    expect(i18n.t('Sign in')).toBe('Anmelden');
  });

  it('updates an already open tab when another tab changes the preference', () => {
    const i18n = TestBed.inject(I18nService);
    window.dispatchEvent(new StorageEvent('storage', {key:LANGUAGE_STORAGE_KEY,newValue:'de'}));
    expect(i18n.language()).toBe('de');
    expect(document.documentElement.lang).toBe('de');
    window.dispatchEvent(new StorageEvent('storage', {key:LANGUAGE_STORAGE_KEY,newValue:'invalid'}));
    expect(i18n.language()).toBe('de');
  });

  it('resolves stored messages and nested errors in the current language', () => {
    const i18n = TestBed.inject(I18nService);
    const message = i18n.message('Unable to load inventory: {error}', {error:i18n.message('Invalid credentials.')});
    expect(i18n.t(message)).toBe('Unable to load inventory: Invalid credentials.');
    i18n.setLanguage('de');
    expect(i18n.t(message)).toBe('Bestand konnte nicht geladen werden: Ungültige Zugangsdaten.');
    expect(i18n.t('Missing {amount}', {amount:1.75})).toBe('Missing 1,75');
    i18n.setLanguage('en');
    expect(i18n.t(message)).toBe('Unable to load inventory: Invalid credentials.');
  });

  it('translates known validation details and retains precise field and error context', () => {
    const i18n = TestBed.inject(I18nService); i18n.setLanguage('de');
    expect(i18n.t('password: String should have at least 14 characters')).toBe('Passwort: Der Text muss mindestens 14 Zeichen enthalten');
    expect(i18n.t('Input should be greater than or equal to 1')).toBe('Der Wert muss mindestens 1 betragen');
    expect(i18n.t('Row 3: invalid spool values.')).toBe('Zeile 3: Ungültige Spulenwerte.');
    expect(i18n.t('Value error, Consumption must be greater than zero.')).toBe('Der Verbrauch muss größer als null sein.');
    expect(i18n.t('Request failed (HTTP 503).')).toBe('Die Anfrage ist fehlgeschlagen (HTTP 503).');
    expect(i18n.t('Printer XYZ: external diagnostic 4711')).toBe('Printer XYZ: external diagnostic 4711');
    expect(i18n.t('constructor')).toBe('constructor');
    expect(i18n.t('__proto__')).toBe('__proto__');
  });

  it('formats numbers, weights, prices and calendar dates without changing their values', () => {
    const i18n = TestBed.inject(I18nService);
    expect(i18n.grams(1250)).toBe('1.25 kg');
    expect(i18n.dateOnly('2026-10-09')).toBe('2026-10-09');
    i18n.setLanguage('de');
    expect(i18n.grams(1250)).toBe('1,25 kg');
    expect(i18n.number(1234.5)).toBe('1.234,5');
    expect(i18n.money(12345,'EUR')).toMatch(/123,45\s+€/);
    expect(i18n.money(null,'EUR')).toBe('Nicht erfasst');
    expect(i18n.dateOnly('2026-10-09')).toBe('09.10.2026');
    expect(i18n.dateText('invalid')).toBe('—');
  });

  it('switches login copy without recreating the form or discarding entered credentials', async () => {
    const auth = {needsSetup:signal(false),login:vi.fn(),setup:vi.fn()};
    TestBed.configureTestingModule({providers:[{provide:AuthService,useValue:auth}]});
    const fixture = TestBed.createComponent(LoginComponent);
    fixture.componentInstance.username = 'draft-user';
    fixture.componentInstance.password = '  exact draft password  ';
    fixture.detectChanges(); await fixture.whenStable();
    const form = fixture.nativeElement.querySelector('form');
    const password = fixture.nativeElement.querySelector('input[name="password"]');
    const picker: HTMLSelectElement = fixture.nativeElement.querySelector('sm-language-picker select');
    picker.value = 'de'; picker.dispatchEvent(new Event('change')); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('h1').textContent).toBe('Willkommen zurück.');
    expect(fixture.nativeElement.querySelector('form')).toBe(form);
    expect(fixture.nativeElement.querySelector('input[name="password"]')).toBe(password);
    expect(password.value).toBe('  exact draft password  ');
    expect(fixture.componentInstance.username).toBe('draft-user');
    expect(auth.login).not.toHaveBeenCalled();
    picker.value = 'en'; picker.dispatchEvent(new Event('change')); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('h1').textContent).toBe('Welcome back.');
  });

  it('renders interpolated values as text without interpreting markup', () => {
    const fixture = TestBed.createComponent(MessageHost); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('img')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('<img src=x onerror=alert(1)>');
  });

  it('keeps shared translations consistent and preserves all named parameters', () => {
    const seen = new Map<string,string>();
    const parameters = (value:string) => [...new Set([...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(match=>match[1]))].sort();
    for (const catalog of CATALOGS) for (const [source,translation] of Object.entries(catalog)) {
      expect(translation.trim(), source).not.toBe('');
      expect(parameters(translation),source).toEqual(parameters(source));
      if (seen.has(source)) expect(translation,source).toBe(seen.get(source));
      seen.set(source,translation);
    }
  });
});
