import { Component, inject } from '@angular/core';
import { TranslatePipe } from '../i18n';
import { ThemeService } from '../theme.service';

@Component({
  selector: 'fm-theme-picker', standalone: true, imports: [TranslatePipe],
  template: `<label class="theme-picker">
    <span class="theme-symbol" aria-hidden="true">{{theme.dark() ? '☾' : '☀'}}</span>
    <select [value]="theme.preference()" (change)="theme.setPreference($any($event.target).value)" [attr.aria-label]="'Appearance'|t">
      <option value="system">{{'System theme'|t}}</option>
      <option value="light">{{'Light theme'|t}}</option>
      <option value="dark">{{'Dark theme'|t}}</option>
    </select>
  </label>`
})
export class ThemePickerComponent { readonly theme = inject(ThemeService); }
