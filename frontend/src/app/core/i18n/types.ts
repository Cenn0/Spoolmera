export type Language = 'en' | 'de';
export type TranslationCatalog = Readonly<Record<string, string>>;
export interface LocalizedMessage {
  readonly key: string;
  readonly params?: MessageParams;
}
export type MessageValue = string | LocalizedMessage;
export type MessageParams = Readonly<Record<string, string | number | boolean | LocalizedMessage | null | undefined>>;

export const LANGUAGE_STORAGE_KEY = 'filament-manager.language';

export function supportedLanguage(value: string | null | undefined): Language | null {
  return value === 'en' || value === 'de' ? value : null;
}

export function browserLanguage(languages: readonly string[]): Language {
  for (const candidate of languages) {
    const language = supportedLanguage(candidate.trim().toLowerCase().split(/[-_]/)[0]);
    if (language) return language;
  }
  return 'en';
}
