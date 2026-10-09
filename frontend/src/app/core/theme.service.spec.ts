import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { THEME_KEY, ThemeService } from './theme.service';

describe('theme preference without account side effects', () => {
  let media: MediaQueryList;
  beforeEach(() => {
    localStorage.removeItem(THEME_KEY);
    media=Object.assign(new EventTarget(),{matches:false,media:'(prefers-color-scheme: dark)'}) as MediaQueryList;
    vi.stubGlobal('matchMedia',vi.fn(()=>media));
  });
  afterEach(()=>{TestBed.resetTestingModule();vi.unstubAllGlobals();vi.restoreAllMocks();localStorage.removeItem(THEME_KEY);delete document.documentElement.dataset['theme'];document.documentElement.style.colorScheme='';});
  it('follows the system until explicitly overridden',()=>{
    const service=TestBed.inject(ThemeService);
    expect(service.dark()).toBe(false);
    Object.assign(media,{matches:true});media.dispatchEvent(new Event('change'));
    expect(service.dark()).toBe(true);
    service.setPreference('light');expect(service.dark()).toBe(false);
    media.dispatchEvent(new Event('change'));expect(service.dark()).toBe(false);
    service.setPreference('system');expect(service.dark()).toBe(true);
  });
  it('restores a saved theme and persists changes',()=>{
    localStorage.setItem(THEME_KEY,'dark');const service=TestBed.inject(ThemeService);
    expect(document.documentElement.dataset['theme']).toBe('dark');
    expect(service.preference()).toBe('dark');
    service.setPreference('light');expect(localStorage.getItem(THEME_KEY)).toBe('light');
    expect(document.documentElement.style.colorScheme).toBe('light');
    service.setPreference('javascript:bad');expect(service.preference()).toBe('light');
  });
  it('works with blocked storage and synchronizes cross-tab changes',()=>{
    vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new Error('blocked');});
    vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new Error('blocked');});
    const service=TestBed.inject(ThemeService);
    expect(()=>service.setPreference('dark')).not.toThrow();
    expect(service.dark()).toBe(true);
    window.dispatchEvent(new StorageEvent('storage',{key:THEME_KEY,newValue:'light'}));
    expect(service.dark()).toBe(false);
  });
  it('cleans up listeners when the injector is destroyed',()=>{
    const listener=vi.spyOn(media,'removeEventListener');TestBed.inject(ThemeService);
    TestBed.resetTestingModule();expect(listener).toHaveBeenCalledWith('change',expect.any(Function));
  });
});
