import { Injectable, signal } from '@angular/core';
import type { Spool } from './models';
import type { ProductInput } from './models';
import type { MessageValue } from './core/i18n/types';

export type DialogKind = 'product' | 'spool' | 'details' | 'movement' | 'csv' | 'weigh' | 'drying';
export interface DialogRequest {
  kind: DialogKind;
  id?: number;
  spool?: Spool;
  productId?: number;
  catalog?: Partial<ProductInput>;
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
  readonly message = signal<MessageValue>('');
  readonly isError = signal(false);
  show(message: MessageValue, isError = false): void {
    this.isError.set(isError);
    this.message.set(message);
  }
  clear(): void { this.message.set(''); }
}
