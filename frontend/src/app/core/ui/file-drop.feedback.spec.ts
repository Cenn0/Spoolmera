import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { I18nService } from '../i18n';
import { FileDropComponent } from './file-drop.component';

describe('file drop limit feedback', () => {
  let fixture: ComponentFixture<FileDropComponent>;
  let component: FileDropComponent;
  let selected: File[];
  beforeEach(() => {
    TestBed.resetTestingModule(); TestBed.inject(I18nService).setLanguage('en');
    fixture = TestBed.createComponent(FileDropComponent); component = fixture.componentInstance;
    fixture.componentRef.setInput('accept', '.csv'); fixture.componentRef.setInput('maxBytes', 2 * 1024 * 1024);
    selected = []; component.selected.subscribe(file => selected.push(file)); fixture.detectChanges();
  });
  afterEach(() => TestBed.resetTestingModule());
  it('shows the limit before selection and connects it to both picker controls', () => {
    const limit = fixture.nativeElement.querySelector('#' + component.limitId);
    expect(limit.textContent).toContain('Maximum file size: 2 MiB');
    expect(fixture.nativeElement.querySelector('button').getAttribute('aria-describedby')).toContain(component.limitId);
    expect(fixture.nativeElement.querySelector('input').getAttribute('aria-describedby')).toContain(component.limitId);
  });
  it('still hands off the exact File to the authoritative parent', () => {
    const file = new File(['abc'], 'inventory.csv'); component.acceptFiles([file]);
    expect(selected).toEqual([file]); expect(selected[0]).toBe(file);
  });
  it('localizes binary units without emitting a new selection', () => {
    expect(component.sizeText(1280)).toBe('1.25 KiB');
    TestBed.inject(I18nService).setLanguage('de'); fixture.detectChanges();
    expect(component.sizeText(1280)).toBe('1,25 KiB');
    expect(fixture.nativeElement.textContent).toContain('Maximale Dateigröße: 2 MiB');
    expect(selected).toEqual([]);
  });
  it('keeps the displayed limit aligned with accepted and rejected sizes', () => {
    fixture.componentRef.setInput('maxBytes', 3); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Maximum file size: 3 B');
    const boundary = new File(['abc'], 'boundary.csv'); component.acceptFiles([boundary]);
    component.acceptFiles([new File(['abcd'], 'too-large.csv')]);
    expect(selected).toEqual([boundary]); expect(component.error()).toBe('This file exceeds the allowed upload size.');
  });
  it('assigns distinct description targets to multiple drop zones', () => {
    const second = TestBed.createComponent(FileDropComponent); second.componentRef.setInput('accept', '.stl'); second.detectChanges();
    expect(second.componentInstance.limitId).not.toBe(component.limitId);
    expect(second.componentInstance.labelId).not.toBe(component.labelId);
    second.destroy();
  });
});
