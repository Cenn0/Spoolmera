import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from './i18n';
@Component({standalone: true, imports: [RouterLink,TranslatePipe], template: `
  <section class="page-head"><div><span class="eyebrow">{{'ACCESS' | t}}</span><h1>{{'Access' | t}} <em>{{'restricted.' | t}}</em></h1>
  <p>{{'Your account does not have permission to open this page.' | t}}</p></div></section>
  <a class="btn primary" routerLink="/">{{'Back to overview' | t}}</a>
`})
export class AccessDeniedComponent {}
@Component({standalone: true, template: ''})
export class LoginRouteComponent {}
