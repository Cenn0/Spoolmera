import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService } from './i18n.service';
import type { MessageParams, MessageValue } from './types';

// Language is application state rather than a pipe argument. An impure pipe
// reevaluates existing views without destroying a form or reopening a dialog.
@Pipe({name: 't', standalone: true, pure: false})
export class TranslatePipe implements PipeTransform {
  private readonly i18n = inject(I18nService);
  transform(value: MessageValue | null | undefined, params?: MessageParams): string {
    return this.i18n.t(value, params);
  }
}
