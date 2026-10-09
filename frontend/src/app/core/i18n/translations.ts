import { UI_DE } from './ui.de';
import { COMMON_DE } from './common.de';
import { ERRORS_DE } from './errors.de';
import { INVENTORY_DE } from './inventory.de';
import { SYSTEM_DE } from './system.de';
import { WORKFLOWS_DE } from './workflows.de';
import type { TranslationCatalog } from './types';

export const CATALOGS: readonly TranslationCatalog[] = [COMMON_DE, ERRORS_DE, INVENTORY_DE, SYSTEM_DE, WORKFLOWS_DE, UI_DE];
export const DE: TranslationCatalog = Object.freeze(Object.assign(Object.create(null), ...CATALOGS));

const errorPatterns = Object.entries(ERRORS_DE).filter(([source]) => /\{[A-Za-z]/.test(source))
  .sort(([left], [right]) => right.replace(/\{[^}]+\}/g, '').length - left.replace(/\{[^}]+\}/g, '').length)
  .map(([source, target]) => {
  const names: string[] = [];
  let start = 0;
  let pattern = '^';
  for (const match of source.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)) {
    pattern += escapeRegex(source.slice(start, match.index)) + '(.+?)';
    names.push(match[1]);
    start = match.index! + match[0].length;
  }
  pattern += escapeRegex(source.slice(start)) + '$';
  return {regex: new RegExp(pattern), names, target};
});

function escapeRegex(text: string): string { return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

const FIELD_LABELS: Readonly<Record<string, string>> = {
  username:'Benutzername',password:'Passwort',old_password:'Aktuelles Passwort',new_password:'Neues Passwort',
  name:'Name',brand:'Marke',material:'Material',color_name:'Farbname',color_hex:'Farbcode',diameter_mm:'Durchmesser',
  density_g_cm3:'Dichte',initial_g:'Anfangsgewicht',remaining_g:'Restgewicht',gross_g:'Bruttogewicht',tare_g:'Leergewicht',
  estimated_g:'Geschätzter Verbrauch',actual_g:'Istverbrauch',grams:'Gramm',count:'Anzahl',note:'Notiz',notes:'Notizen',
  location:'Standort',reason:'Begründung',role:'Rolle',file_name:'Dateiname',base_url:'Serveradresse',token_env:'Tokenvariable',
  temperature_c:'Temperatur',duration_minutes:'Dauer',low_stock_threshold_g:'Warnschwelle',target_stock_g:'Zielbestand',
  purchased_on:'Kaufdatum',purchase_price_cents:'Kaufpreis',purchase_currency:'Währung',batch:'Charge',
};

// Backend error prose is a separate boundary from translated labels. Match only
// known application templates; retain unfamiliar diagnostics verbatim.
export function translateKnownError(source: string, depth = 0): string | undefined {
  if (source.length > 8192 || depth > 4) return undefined;
  if (DE[source] !== undefined) return DE[source];
  if (source.includes(' · ')) {
    const parts = source.split(' · ');
    const translated = parts.map(part => translateKnownError(part, depth + 1) ?? part);
    return translated.some((part, index) => part !== parts[index]) ? translated.join(' · ') : undefined;
  }
  if (source.startsWith('Value error, ')) return translateKnownError(source.slice(13), depth + 1) ?? source.slice(13);
  const field = /^([A-Za-z_][A-Za-z0-9_.\[\]-]*): (.+)$/.exec(source);
  if (field) {
    const message = translateKnownError(field[2], depth + 1);
    if (message !== undefined) return (FIELD_LABELS[field[1]] ?? field[1]) + ': ' + message;
  }
  for (const {regex, names, target} of errorPatterns) {
    const match = regex.exec(source);
    if (match) return target.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (_, name: string) => match[names.indexOf(name) + 1]);
  }
  return undefined;
}
