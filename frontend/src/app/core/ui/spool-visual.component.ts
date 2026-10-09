import { Component, computed, input } from '@angular/core';

/** Decorative reel; adjacent text conveys color, material and stock accessibly. */
@Component({
  selector: 'fm-spool-visual', standalone: true,
  host: {'aria-hidden': 'true'},
  template: `<div class="reel" [style.--filament]="safeColor()" [style.--fill]="fill() + '%'">
    <div class="reel-winding"></div><div class="reel-hub"><span></span></div>
  </div>`
})
export class SpoolVisualComponent {
  readonly color = input<string | null>('#77858a');
  readonly percentage = input(100);
  readonly safeColor = computed(() => /^#[\da-f]{6}$/i.test(this.color() ?? '') ? this.color()! : '#77858a');
  readonly fill = computed(() => Number.isFinite(this.percentage()) ? Math.max(0, Math.min(100, this.percentage())) : 0);
}
