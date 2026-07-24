# Gemtext editor

Build setup for the vendored javascript bundle at
`geminiportal/static/gemtext-editor.js`.

The bundle progressively enhances the textarea on the titan:// upload
form with a [CodeMirror 6](https://codemirror.net) editor that
live-styles gemtext line types (headings, links, quotes, lists, and
preformatted blocks). If javascript is disabled, the form falls back
to the plain textarea.

The editor source lives in `gemtext-editor.mjs`, and the visual styles
live in `geminiportal/static/gemtext-editor.css`.

## Rebuilding the bundle

Node is only needed to rebuild the bundle after changing
`gemtext-editor.mjs` or upgrading CodeMirror; it's not required to
deploy or run the app.

```
npm install
npm run build
```

Commit the regenerated `geminiportal/static/gemtext-editor.js` along
with the `package-lock.json` if any dependencies were updated.
