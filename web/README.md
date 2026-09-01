# Dashboard

Hand-written HTML, CSS and JavaScript. No framework, no build step, no bundler,
no CDN, no web fonts fetched from someone else's server, no analytics, no
telemetry, no vendor banner in the corner of your own application.

Served as static files by our own API at `/`. Editing `app.js` and reloading is
the entire development loop.

## Why no framework

Three reasons, in order of weight.

1. **No third-party branding or attribution in a tool you run for yourself.**
   Several otherwise-good dashboard frameworks put their own name, link or
   copyright into the rendered page. That is fine for their business and wrong
   for this project.
2. **No build step means contributors need nothing but a text editor.** No
   toolchain version to match, no `node_modules`, no lockfile drift, and the
   Docker image needs no Node at all.
3. **The UI is genuinely simple.** A list, a detail view, a settings form. A
   framework would be more code than the thing it renders.

## Internationalisation

Every string comes from `i18n/<lang>.json` — a flat JSON object with dot-path
keys and `{named}` placeholders. `app.js` fetches English and the chosen locale,
merges them so a missing key degrades rather than breaking, and sets the
document's `lang` and `dir`. There is no build step and no restart.

`styles.css` uses logical properties throughout, so a right-to-left locale is the
`dir` attribute and nothing else. Adding a language is one file:
[`../docs/LOCALIZATION.md`](../docs/LOCALIZATION.md).

## Files

| File | Purpose |
|---|---|
| `index.html` | Shell, navigation and view container |
| `app.js` | Catalogue, router, API client, every view |
| `styles.css` | Design tokens and layout; light, dark, LTR and RTL |
| `i18n/en.json` | The reference catalogue |
| `i18n/pt.json` | A complete second locale |
| `i18n/_meta.json` | The format, the placeholder rules and the tone guidance |
| `icon.svg` | Our own mark. No third-party logo appears anywhere. |
| `manifest.webmanifest` | Installable on a phone |
| `sw.js` | Service worker — offline read of what you already loaded |

## Information architecture

**Today** is the landing view: a finite, ranked list of what matters to you now.
It ends. There is no infinite scroll, because a feed that never ends is a design
decision about your attention, and this one is made differently.

Each item shows its **matched rules as chips** — "AI governance +5", "Brazil +4".
Tap one to see the profile line that fired. The ranking is never a mystery.

- **Setup** — the first-run wizard. Language, storage, source bundles, interests.
  Shown automatically until configuration is complete, and reachable again from
  Settings.
- **Today** — ranked feed, finite, with a clear end.
- **Search** — keyword or semantic depending on tier; the mode is labelled.
- **Article** — full stored text, translation toggle, source and archive state.
- **Sources** — health, lifecycle badges, per-source enable and disable.
- **Profile** — edit interests and see the feed re-rank live.
- **Settings** — language, storage, source bundles, collection behaviour and AI
  models. Every option carries contextual help written for a reader who has never
  heard of the thing it configures.
- **Status** — capability level, provider health, pending enrichment.

## Mobile

Same code. CSS grid collapses to a single column, targets are at least 44px, and
the manifest makes it installable. There is no separate mobile app to maintain
and no app store to answer to.
