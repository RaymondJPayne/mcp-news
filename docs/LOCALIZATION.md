# Adding a language

Every user-visible string in this application comes from one flat JSON file per
language. Adding a language is copying `web/i18n/en.json`, translating the
values, and adding three lines to `web/i18n/_meta.json`. There is no build step,
no compiler, no `.po` file, no string extraction pass, and nothing to install.

This is deliberate. The format is the dullest thing that works, so that a
translator with a text editor and a language model with one pass can both do the
job correctly.

---

## 1. The format

```
web/i18n/
├── _meta.json     what the format is, and which locales exist
├── en.json        English — the reference. Every other file mirrors its keys.
└── pt.json        Portuguese — a complete second locale, not a stub.
```

Each locale file is **one flat JSON object**. No nesting, no arrays, no comments.

```json
{
  "setup.storage.title": "Where to keep your articles",
  "today.end": "That is all {count} items above your threshold.",
  "common.count_articles.one": "1 article"
}
```

| Rule | Why |
|---|---|
| Keys are stable dot-paths and are **never translated**. | They are how the code finds the string. |
| Values are plain strings. | They are inserted as text, never as HTML. |
| Placeholders are `{named}` in curly braces. | Named, so a translator can move them within the sentence. |
| Every placeholder in English must appear in the translation, exactly once unless English repeats it. | A dropped placeholder silently loses information. |
| No markup in values. Write `&`, `<` and `"` literally. | The dashboard sets `textContent`, so tags would be shown, not rendered. |
| A key ending `.one` is the singular of the key without it. | The only plural machinery here, and it is optional. |

## 2. Adding a locale

1. Copy the reference file:

   ```bash
   cp web/i18n/en.json web/i18n/de.json
   ```

2. Translate **every value**. Leave every key untouched.

3. Declare it in `web/i18n/_meta.json`:

   ```json
   "de": { "name": "German", "endonym": "Deutsch", "dir": "ltr" }
   ```

   `endonym` is the language's name in itself — it is what the reader picking a
   language sees, because someone who does not read English cannot find
   "German" in a list. `dir` is `ltr` or `rtl`.

4. Check it:

   ```bash
   uv run pytest tests/test_i18n_parity.py
   ```

   That fails if a key is missing, if a key exists that English does not have,
   if placeholders do not match, or if a value contains markup.

5. Restart nothing. Pick the language in Settings; it takes effect immediately.

A missing key falls back to English at runtime, so a half-finished translation
degrades rather than breaking. The test still fails on it, because a partial
catalogue is a bug even when it does not look like one on screen.

## 3. Right-to-left languages

Set `"dir": "rtl"` in `_meta.json` and you are finished. The dashboard sets the
document's `dir` attribute from that value, and `web/styles.css` uses logical
properties throughout — `margin-inline`, `inset-inline-start`,
`border-inline-start`, `text-align: start` — so the whole layout mirrors without
a second stylesheet. A test asserts that no physical `margin-left` or
`padding-right` creeps back in.

Arabic and Hebrew are expected. If something does not mirror correctly, that is a
bug in the stylesheet, not something for the translation to work around.

## 4. Tone

The tone is set in `_meta.json` and repeated here because it matters more than
any individual word.

Plain, calm, direct. Address the reader as *you*. Explain rather than command.
Avoid jargon; where a technical term is unavoidable, the help text beside it must
define it in ordinary language. No exclamation marks. No marketing.

Two things stay untranslated: **mcp-news**, which is a product name, and the
names of feed formats such as RSS, Atom and JSON Feed, which are the terms
publishers themselves use.

Help text is the part most worth spending time on. Roughly a third of the
catalogue is `*.help*` keys, and they exist for a reader who has never heard of a
bind mount, an embedding model or a half-life. Translate the explanation, not the
words.

## 5. Where the strings are used

| Prefix | Screen |
|---|---|
| `nav.*`, `common.*` | Chrome and shared controls |
| `setup.*` | The first-run wizard |
| `today.*` | The ranked feed |
| `search.*`, `article.*` | Search and the article view |
| `sources.*` | The source list and the add-a-source form |
| `profile.*` | The interests editor |
| `settings.*` | Every settings screen, including its help text |
| `status.*`, `tier.*` | Status, and the capability level in the header |
| `err.*` | Messages the server sends as keys rather than sentences |

The server never sends an English sentence. An API error is
`{"error": {"key": "err.source.unreachable", "params": {}}}`, and the browser —
which knows the reader's language — turns it into words. If you add an error
path in Python, add its key to `en.json` in the same change;
`tests/test_api.py` fails otherwise.
