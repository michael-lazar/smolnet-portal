/*
 * Gemtext (text/gemini) editor for the titan:// upload form.
 *
 * Progressively enhances the plain <textarea> with a CodeMirror editor
 * that live-styles gemtext line types. If javascript is disabled, the
 * form falls back to the plain textarea.
 *
 * This file is bundled into geminiportal/static/gemtext-editor.js,
 * which is
 * committed to the repository. See the README for build instructions.
 */
import {defaultKeymap, history, historyKeymap} from "@codemirror/commands";
import {StreamLanguage, syntaxHighlighting} from "@codemirror/language";
import {EditorView, keymap} from "@codemirror/view";
import {tagHighlighter, tags} from "@lezer/highlight";

// Line-based tokenizer for the gemtext grammar. Every line is a single
// token, except for link lines which are split into (marker, url, text).
// The only state that carries across lines is the ``` preformat toggle.
const gemtext = StreamLanguage.define({
    name: "gemtext",
    startState: () => ({pre: false, link: null, quote: false}),
    token(stream, state) {
        if (stream.sol()) {
            state.link = null;
            state.quote = false;
            if (stream.match("```")) {
                state.pre = !state.pre;
                stream.skipToEnd();
                return "preMarker";
            } else if (state.pre) {
                stream.skipToEnd();
                return "preText";
            } else if (stream.match("###")) {
                stream.skipToEnd();
                return "h3";
            } else if (stream.match("##")) {
                stream.skipToEnd();
                return "h2";
            } else if (stream.match("#")) {
                stream.skipToEnd();
                return "h1";
            } else if (stream.match("* ")) {
                return "listMarker";
            } else if (stream.match(">")) {
                state.quote = true;
                return "quoteMarker";
            } else if (stream.match("=>")) {
                stream.eatSpace();
                state.link = "url";
                return "linkMarker";
            } else {
                stream.skipToEnd();
                return null;
            }
        } else if (state.quote) {
            stream.skipToEnd();
            return "quote";
        } else if (state.link === "url") {
            stream.eatWhile(/\S/);
            state.link = "text";
            return "linkUrl";
        } else if (state.link === "text") {
            stream.skipToEnd();
            return "linkText";
        } else {
            stream.skipToEnd();
            return null;
        }
    },
    tokenTable: {
        h1: tags.heading1,
        h2: tags.heading2,
        h3: tags.heading3,
        quote: tags.quote,
        quoteMarker: tags.processingInstruction,
        listMarker: tags.list,
        linkMarker: tags.processingInstruction,
        linkUrl: tags.url,
        linkText: tags.link,
        preMarker: tags.meta,
        preText: tags.monospace,
    },
});

// Map the tokens to CSS classes, the styles are defined in gemtext-editor.css
const gemtextHighlighter = tagHighlighter([
    {tag: tags.heading1, class: "gt-h1"},
    {tag: tags.heading2, class: "gt-h2"},
    {tag: tags.heading3, class: "gt-h3"},
    {tag: tags.quote, class: "gt-quote"},
    {tag: tags.list, class: "gt-list"},
    {tag: tags.processingInstruction, class: "gt-marker"},
    {tag: tags.url, class: "gt-url"},
    {tag: tags.link, class: "gt-link"},
    {tag: tags.meta, class: "gt-marker"},
    {tag: tags.monospace, class: "gt-pre"},
]);

// Drafts are persisted across page loads, keyed per titan URL. Storage
// may be unavailable (e.g. private browsing) so failures are ignored.
const draftKey = "titan-draft:" + window.location.pathname;

function loadDraft() {
    try {
        return window.localStorage.getItem(draftKey) || "";
    } catch {
        return "";
    }
}

function saveDraft(text) {
    try {
        if (text) {
            window.localStorage.setItem(draftKey, text);
        } else {
            window.localStorage.removeItem(draftKey);
        }
    } catch {
        // pass
    }
}

function enhance() {
    const textarea = document.getElementById("titan-content");
    if (!textarea || !textarea.form) {
        return;
    }

    let saveTimer = null;
    let submitted = false;

    const view = new EditorView({
        doc: textarea.value || loadDraft(),
        extensions: [
            gemtext,
            syntaxHighlighting(gemtextHighlighter),
            history(),
            keymap.of([...defaultKeymap, ...historyKeymap]),
            EditorView.lineWrapping,
            EditorView.contentAttributes.of({
                "aria-label": textarea.getAttribute("aria-label") || "",
                spellcheck: "true",
            }),
            EditorView.updateListener.of((update) => {
                if (update.docChanged) {
                    clearTimeout(saveTimer);
                    saveTimer = setTimeout(() => saveDraft(view.state.doc.toString()), 500);
                }
            }),
        ],
    });

    // The hidden textarea is still what's submitted with the form, so
    // copy the editor contents back into it first. Submitting also
    // discards the saved draft.
    textarea.form.addEventListener("submit", () => {
        textarea.value = view.state.doc.toString();
        submitted = true;
        clearTimeout(saveTimer);
        saveDraft("");
    });

    // Flush the draft when navigating away, otherwise the last ~500ms
    // of typing would be lost on refresh.
    window.addEventListener("pagehide", () => {
        if (!submitted) {
            clearTimeout(saveTimer);
            saveDraft(view.state.doc.toString());
        }
    });

    textarea.insertAdjacentElement("beforebegin", view.dom);
    textarea.hidden = true;
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", enhance);
} else {
    enhance();
}
