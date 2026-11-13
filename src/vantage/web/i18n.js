// Interface translations. Keys are the English text; `static/i18n/<lang>.json`
// maps them to the translation. Game names (units, techs, civs) come from the
// game's own string tables in the chosen language, via the server.

export const LANGS = {
  en: 'English', de: 'Deutsch', es: 'Español (España)', 'es-MX': 'Español (México)', fr: 'Français',
  hi: 'हिन्दी', it: 'Italiano', ja: '日本語', ko: '한국어', ms: 'Bahasa Melayu', pl: 'Polski',
  'pt-BR': 'Português (Brasil)', ru: 'Русский', tr: 'Türkçe', vi: 'Tiếng Việt', 'zh-CN': '简体中文',
  'zh-TW': '繁體中文',
};

let dict = {};
export let language = 'en';

export function detectLanguage() {
  const nav = (navigator.language || 'en').toLowerCase();
  for (const code of Object.keys(LANGS)) if (code.toLowerCase() === nav) return code;
  const base = nav.split('-')[0];
  if (base === 'zh') return nav.includes('tw') || nav.includes('hk') ? 'zh-TW' : 'zh-CN';
  if (base === 'pt') return 'pt-BR';
  return LANGS[base] ? base : 'en';
}

export async function setLanguage(lang) {
  language = LANGS[lang] ? lang : 'en';
  dict = language === 'en' ? {} : await fetch(`/static/i18n/${language}.json`).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  document.documentElement.lang = language;
  // Text rendered once at startup (e.g. the event filter buttons) re-renders itself on this.
  document.dispatchEvent(new CustomEvent('vantage:language', { detail: language }));
  translateStatic();
}

// t('{a} killed {b}', {a, b}) -> translated text with the values filled in.
export function t(text, vars) {
  let out = dict[text] || text;
  // Diagnostics: untranslated keys seen at runtime (window.__i18nMisses), for coverage checks.
  if (language !== 'en' && !dict[text] && typeof text === 'string' && text) (window.__i18nMisses ||= new Set()).add(text);
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
  return out;
}

// Display text for a key combination ("Ctrl+Space", "F11 / Alt+Enter"): modifier and
// key names follow the language ('key:<name>' entries); single characters and F-keys
// stay as they are. The combo strings used for matching and storing never change.
export function keyLabel(text) {
  const name = (p) => {
    const v = dict[`key:${p}`];
    if (!v && language !== 'en' && /^[A-Za-z][A-Za-z ()]+$/.test(p)) (window.__i18nMisses ||= new Set()).add(`key:${p}`);
    return v || p;
  };
  return String(text).split(' / ').map((combo) => {
    if (dict[`key:${combo}`]) return dict[`key:${combo}`];
    const parts = [];
    let rest = combo;
    for (;;) {
      const m = rest.match(/^(Ctrl|Alt|Shift|Meta)\+(.+)$/);
      if (!m) break;
      parts.push(m[1]); rest = m[2];
    }
    parts.push(rest);
    return parts.map(name).join('+');
  }).join(' / ');
}

// Static markup: elements carry their English title text; translate in place.
// Tooltips follow document.body.dataset.tooltips (settings.tooltipShowMode):
// 'off' blanks them, 'names' drops the detail after the name ("Fog of war:
// click cycles… (Alt+F)" -> "Fog of war"), 'detailed' keeps everything.
export function translateStatic() {
  const mode = (document.body && document.body.dataset.tooltips) || 'detailed';
  for (const el of document.querySelectorAll('[title]')) {
    if (el.dataset.i18nTitle == null) el.dataset.i18nTitle = el.getAttribute('title');
    const text = el.hasAttribute('data-tip') ? el.dataset.i18nTitle : t(el.dataset.i18nTitle);
    el.setAttribute('title', mode === 'off' ? '' : mode === 'names' ? tooltipName(text) : mode === 'detail' ? tooltipDetail(text) : text);
  }
  for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  // Accessible names of controls drawn as a glyph (−, ⚑, ‹): what they do, in the interface language.
  for (const el of document.querySelectorAll('[data-i18n-label]')) el.setAttribute('aria-label', t(el.dataset.i18nLabel));
}

// The detail part of a tooltip (everything after the name); the whole text when there is none.
export function tooltipDetail(text) {
  const m = String(text).match(/^[^:—]*?(?::| —) (.+)$/);
  return m ? m[1].trim() : String(text);
}

// The name part of a tooltip: text before a ':' / ' — ' detail and without a
// trailing "(hotkey)".
export function tooltipName(text) {
  return String(text).split(/: | — /)[0].replace(/\s*\([^)]*\)\s*$/, '').trim();
}
