# Translations

Vantage's interface is available in 17 languages:

| Code | Language | Code | Language |
|---|---|---|---|
| `en` | English | `ko` | 한국어 |
| `de` | Deutsch | `ms` | Bahasa Melayu |
| `es` | Español (España) | `pl` | Polski |
| `es-MX` | Español (México) | `pt-BR` | Português (Brasil) |
| `fr` | Français | `ru` | Русский |
| `hi` | हिन्दी | `tr` | Türkçe |
| `it` | Italiano | `vi` | Tiếng Việt |
| `ja` | 日本語 | `zh-CN` | 简体中文 |
| | | `zh-TW` | 繁體中文 |

## Choosing a language

**Settings → Interface → Look → Language**. By default Vantage follows your browser's language. `zh-HK` and `zh-TW` map to Traditional Chinese, other `zh` to Simplified, and any `pt` to Brazilian Portuguese. A language Vantage does not have falls back to English.

Two kinds of text are not part of Vantage's translations:

- **Game names**: units, buildings, technologies, civilisations, maps and their descriptions. These come from the game's own string tables, in the language you picked.
- **Taunts** are played in the taunt language in **Settings → Sound** (the interface language by default).

Messages the game itself produced, such as chat, appear as they were sent.

## How it works

The interface is written in English. Every piece of text goes through a function `t()`, and the English text itself is the lookup key:

```js
t('Show Elo')                                  // a plain string
t('{p} is under attack', { p: playerName(3) }) // placeholders in braces
```

Translations live in `src/vantage/web/i18n/`:

| File | Contents |
|---|---|
| `<code>.json` | One per language: a JSON object mapping each English string to its translation. |
| `_source.json`, `_source_extra.json`, `_source_extra2.json` | Lists of the English strings to translate (the source catalogue). |

When the language changes, the browser loads `<code>.json`. A string with no entry, or an empty entry, is shown in English, so a missing translation never breaks the interface.

Entries starting with `key:` translate key names shown in hotkey labels, for example `"key:Ctrl": "Strg"` or `"key:Space": "Leertaste"`. Only the displayed label changes. Bindings are always stored in English.

Placeholders such as `{p}`, `{n}` and `{time}` must be kept exactly as they are. Their order in the sentence can change.

## Improving a translation

1. Edit `src/vantage/web/i18n/<code>.json`. Keep the English keys unchanged and change only the values.
2. Reload Vantage in the browser. No build step or restart is needed for a source checkout run with `uv run vantage serve`.
3. To find strings that are still untranslated, use the interface in your language, then run this in the browser's developer console:

   ```js
   [...window.__i18nMisses]
   ```

   It lists every English string that was shown without a translation.
4. Open a pull request. Corrections from native speakers are especially welcome.

## Adding a language

1. Copy an existing translation, such as `de.json`, to `<code>.json` and translate every value.
2. Add the language to `LANGS` in `src/vantage/web/i18n.js`, with its name in that language.
3. Check the result with `window.__i18nMisses` as above.

Game names in the new language need the game itself to ship that language.

## Adding a new string (developers)

1. Write the English text in the code inside `t('…')`.
2. Add the same English text to one of the `_source*.json` lists.
3. Add a translation for it to every `<code>.json`. Until you do, that language shows the English text.

See the [development guide](https://github.com/dkapellusch/vantage-aoe2/blob/main/docs/development.md#adding-a-translation-string).
