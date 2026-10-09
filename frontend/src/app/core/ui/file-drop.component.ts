import { Component, input, output, signal } from '@angular/core';
import { TranslatePipe } from '../i18n';

/** Both file picker and drop use exactly the same validation and preview path. */
@Component({
  selector: 'fm-file-drop', standalone: true, imports: [TranslatePipe],
  template: `<div class="file-drop" [class.drop-active]="over()" [class.is-disabled]="disabled()"
    (dragenter)="enter($event)" (dragover)="hover($event)" (dragleave)="leave($event)" (drop)="drop($event)">
    <span class="file-drop-icon" aria-hidden="true">↥</span>
    <strong>{{label()|t}}</strong>
    <span class="helper">{{'Drop one file here or choose a file.'|t}}</span>
    <button type="button" class="btn ghost" [disabled]="disabled()" (click)="picker.click()">{{'Choose file'|t}}</button>
    <input #picker class="sr-only" type="file" tabindex="-1" [accept]="accept()" [disabled]="disabled()"
      [attr.aria-label]="label()|t" (change)="choose($event)">
    <small class="file-types">{{accept()}}</small>
    @if(error()){<p role="alert" class="form-error">{{error()|t}}</p>}
  </div>`
})
export class FileDropComponent {
  readonly label = input('Upload file');
  readonly accept = input.required<string>();
  readonly maxBytes = input(10 * 1024 * 1024);
  readonly disabled = input(false);
  readonly selected = output<File>();
  readonly rejected = output<string>();
  readonly over = signal(false);
  readonly error = signal('');
  private depth = 0;

  private isFile(event: DragEvent): boolean { return Array.from(event.dataTransfer?.types ?? []).includes('Files'); }
  enter(event: DragEvent): void {
    if (!this.isFile(event)) return;
    event.preventDefault(); event.stopPropagation();
    this.depth++; this.over.set(!this.disabled());
  }
  hover(event: DragEvent): void {
    if (!this.isFile(event)) return;
    event.preventDefault(); event.stopPropagation();
    if (event.dataTransfer) event.dataTransfer.dropEffect = this.disabled() ? 'none' : 'copy';
  }
  leave(event: DragEvent): void {
    event.preventDefault(); event.stopPropagation();
    this.depth = Math.max(0, this.depth - 1);
    if (!this.depth) this.over.set(false);
  }
  drop(event: DragEvent): void {
    if (!this.isFile(event)) return;
    event.preventDefault(); event.stopPropagation();
    this.depth = 0; this.over.set(false);
    if (this.disabled()) return;
    this.acceptFiles(Array.from(event.dataTransfer?.files ?? []));
  }
  choose(event: Event): void {
    const picker = event.target as HTMLInputElement;
    const files = Array.from(picker.files ?? []);
    picker.value = ''; // Selecting the same file again must trigger change.
    if (files.length && !this.disabled()) this.acceptFiles(files);
  }
  acceptFiles(files: readonly File[]): void {
    if (this.disabled()) return;
    this.error.set('');
    let error = '';
    const file = files[0];
    const extensions = this.accept().split(',').map(value => value.trim().toLowerCase()).filter(value => value.startsWith('.'));
    if (files.length !== 1) error = 'Choose exactly one file. Nothing has been uploaded.';
    else if (!extensions.some(extension => file.name.toLowerCase().endsWith(extension))) error = 'This file type is not supported here.';
    else if (file.size === 0) error = 'This file is empty.';
    else if (file.size > this.maxBytes()) error = 'This file exceeds the allowed upload size.';
    if (error) { this.error.set(error); this.rejected.emit(error); return; }
    this.selected.emit(file);
  }
}
