import { ThemePickerComponent } from './core/ui/theme-picker.component';
import { Component, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from './auth.service';
import { apiError } from './inventory.service';
import { LanguagePickerComponent, TranslatePipe } from './core/i18n';

@Component({
  selector:'sm-login', standalone:true, imports:[FormsModule,LanguagePickerComponent,ThemePickerComponent,TranslatePipe],
  styles: [`.login-brand strong { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
    .login-brand small { line-height: 1.4; }`],
  template: `
    <main class="login-screen">
      <section class="login-card">
        <div class="login-language"><sm-theme-picker /><sm-language-picker /></div>
        <div class="login-brand"><img class="brand-mark" src="/spoolmera-mark.svg" alt="" aria-hidden="true">
          <strong>{{'SPOOLMERA' | t}} <small>{{'3D PRINTING WORKSPACE' | t}}</small></strong></div>
        <span class="eyebrow">{{'SELF-HOSTED MATERIAL WORKSPACE' | t}}</span>
        <h1>{{(auth.needsSetup()?'Create the first administrator':'Welcome back.') | t}}</h1>
        <p class="helper">{{(auth.needsSetup()
          ?'Initial setup requires the bootstrap token configured on your server.'
          :'Sign in to access your spool inventory and printer connections.') | t}}</p>
        @if(error()) {<div class="form-error" role="alert">{{error() | t}}</div>}
        <form #loginForm="ngForm" (ngSubmit)="submit()">
          <label>{{'Username' | t}}<input type="text" name="username" [(ngModel)]="username" required maxlength="60" autocomplete="username" autofocus></label>
          <label>{{'Password' | t}}<input type="password" name="password" [(ngModel)]="password" required
            [minlength]="auth.needsSetup()?14:1" maxlength="128" [autocomplete]="auth.needsSetup()?'new-password':'current-password'"></label>
          @if(auth.needsSetup()){
            <label>{{'Bootstrap token' | t}}<input type="password" name="token" [(ngModel)]="bootstrapToken" required
              autocomplete="off" [placeholder]="'From SPOOLMERA_BOOTSTRAP_TOKEN' | t"></label>
          }
          <button class="btn primary" type="submit" [disabled]="busy()||loginForm.invalid">
            {{(busy()?'Working…':auth.needsSetup()?'Create administrator':'Sign in') | t}}
          </button>
        </form>
        <p class="login-footnote">{{'Credentials and inventory remain on your self-hosted server.' | t}}</p>
      </section>
    </main>
  `
})
export class LoginComponent {
  readonly auth=inject(AuthService);
  readonly authenticated=output<void>();
  readonly busy=signal(false);
  readonly error=signal('');
  username='';password='';bootstrapToken='';
  async submit():Promise<void> {
    if(this.busy())return;
    this.busy.set(true);this.error.set('');
    try{
      if(this.auth.needsSetup())await this.auth.setup(this.username,this.password,this.bootstrapToken);
      else await this.auth.login(this.username,this.password);
      this.password='';this.bootstrapToken='';this.authenticated.emit();
    }catch(error){this.error.set(apiError(error));}
    finally{this.busy.set(false);}
  }
}
