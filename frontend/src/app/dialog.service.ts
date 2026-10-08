import { Injectable, signal } from '@angular/core';

export type DialogKind = 'product' | 'spool' | 'details' | 'movement' | 'csv';
export interface DialogRequest {
  kind: DialogKind;
  id?: number;
  productId?: number;
  mode?: 'consume' | 'adjust';
}
@Injectable({providedIn: 'root'})
export class DialogService {
  readonly active = signal<DialogRequest | null>(null);
  open(request: DialogRequest): void { this.active.set({...request}); }
  close(): void { this.active.set(null); }
}
@Injectable({providedIn: 'root'})
export class NoticeService {
  readonly message = signal('');
  readonly isError = signal(false);
  show(message: string, isError = false): void {
    this.isError.set(isError);
    this.message.set(message);
  }
  clear(): void { this.message.set(''); }
}
