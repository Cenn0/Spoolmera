import { I18nService, TranslatePipe } from '../../core/i18n';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../auth.service';
import { DialogService } from '../../dialog.service';
import { InventoryService } from '../../inventory.service';
import { SpoolVisualComponent } from '../../core/ui/spool-visual.component';

@Component({standalone:true, imports:[TranslatePipe,RouterLink,SpoolVisualComponent],templateUrl:'../../products.html'})
export class ProductsComponent {
  readonly i18n=inject(I18nService); readonly data=inject(InventoryService);
  readonly dialogs=inject(DialogService); readonly auth=inject(AuthService);
  readonly grams=(value:number)=>this.i18n.grams(value);
  readonly query=signal(''); readonly material=signal(''); readonly stockOnly=signal(false);
  readonly materials=computed(()=>Array.from(new Set(this.data.products().map(p=>p.material))).sort());
  readonly filtered=computed(()=>{
    const query=this.query().trim().toLocaleLowerCase(this.i18n.locale());
    return this.data.products().filter(p=>[p.brand,p.name,p.material,p.color_name].join(' ').toLocaleLowerCase(this.i18n.locale()).includes(query)
      &&(!this.material()||p.material===this.material())&&(!this.stockOnly()||p.total_remaining_g>0));
  });
}
