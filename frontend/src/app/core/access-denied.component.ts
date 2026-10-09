import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
@Component({standalone: true, imports: [RouterLink], template: `
  <section class="page-head"><div><span class="eyebrow">ACCESS</span><h1>Access <em>restricted.</em></h1>
  <p>Your account does not have permission to open this page.</p></div></section>
  <a class="btn primary" routerLink="/">Back to overview</a>
`})
export class AccessDeniedComponent {}
@Component({standalone: true, template: ''})
export class LoginRouteComponent {}
