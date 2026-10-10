import { Component, inject } from '@angular/core';
import { I18nService } from './i18n.service';
import { TranslatePipe } from './translate.pipe';

@Component({selector: 'sm-language-picker', standalone: true, imports: [TranslatePipe], template: `
  <label class="language-picker">
    <span>{{'Language' | t}}</span>
    <select [value]="i18n.language()" (change)="i18n.setLanguage($any($event.target).value)"
      [attr.aria-label]="'Interface language' | t">
      <option value="en" lang="en">English</option>
      <option value="de" lang="de">Deutsch</option>
    </select>
  </label>
`})
export class LanguagePickerComponent { readonly i18n = inject(I18nService); }
