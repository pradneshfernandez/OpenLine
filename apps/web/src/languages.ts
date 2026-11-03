/** Call languages: every language Gnani Prisma (speech-to-text) and Timbre (voices) support.
 *  Mirrors LANGUAGES in apps/api/app/voice/i18n.py. */
export const LANGUAGES = [
  { code: 'en', name: 'English', native: 'English' },
  { code: 'hi', name: 'Hindi', native: 'हिन्दी' },
  { code: 'bn', name: 'Bengali', native: 'বাংলা' },
  { code: 'gu', name: 'Gujarati', native: 'ગુજરાતી' },
  { code: 'kn', name: 'Kannada', native: 'ಕನ್ನಡ' },
  { code: 'ml', name: 'Malayalam', native: 'മലയാളം' },
  { code: 'mr', name: 'Marathi', native: 'मराठी' },
  { code: 'pa', name: 'Punjabi', native: 'ਪੰਜਾਬੀ' },
  { code: 'ta', name: 'Tamil', native: 'தமிழ்' },
  { code: 'te', name: 'Telugu', native: 'తెలుగు' },
] as const

export type LangCode = (typeof LANGUAGES)[number]['code']
export const LANG_CODES = LANGUAGES.map((l) => l.code) as LangCode[]

/** 'ta', 'ta-IN', 'Tamil', 'Tamil (ta)' or 'தமிழ்' → 'ta' (undefined if it isn't a call language). */
export function langCodeOf(value: string): LangCode | undefined {
  const low = value.trim().toLowerCase()
  return LANGUAGES.find((l) => low === l.code || low.split('-')[0] === l.code || low.includes(`(${l.code})`)
    || low.startsWith(l.name.toLowerCase()) || (l.native !== l.name && value.includes(l.native)))?.code
}

/** English name of a call language ('ta' → 'Tamil'); unknown values come back as they are. */
export const langName = (value: string) => LANGUAGES.find((l) => l.code === langCodeOf(value))?.name ?? value

/** Label for pickers and chips: 'தமிழ் Tamil', or 'English'. */
export function langLabel(value: string) {
  const l = LANGUAGES.find((x) => x.code === langCodeOf(value))
  if (!l) return value
  return l.native === l.name ? l.name : `${l.native} ${l.name}`
}

/** For the `lang` attribute, so the right font and line-breaking apply. */
export const langAttr = (value: string) => {
  const c = langCodeOf(value)
  return c && c !== 'en' ? c : undefined
}

export const LANG_OPTIONS = LANGUAGES.map((l) => ({ value: l.code, label: l.native === l.name ? l.name : `${l.native} ${l.name}` }))

/** A question's text in the interview language. Form language keys look like "Tamil (ta)", "Hindi" or "default". */
export function labelIn(labels: Record<string, string>, lang: string) {
  const code = langCodeOf(lang) ?? 'en'
  const hit = Object.entries(labels).find(([k]) => langCodeOf(k) === code)
    ?? (code === 'en' ? Object.entries(labels).find(([k]) => /^default$/i.test(k)) : undefined)
  return hit?.[1] ?? Object.values(labels)[0]
}
