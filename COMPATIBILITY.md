# SnipPop 0.1 verification — 22 September 2026

Passed:
- Eight automated storage/content tests: migration leaves original database unchanged, generated plain text, HTML sanitization, search ranking, sorting/filtering, keyword uniqueness, trash, export exclusion of logins, import, placeholder cycles, and URL validation.
- Native search window and WebKit rich editor load, render, and return saved content.
- HTML and plain clipboard formats can be read back; PNG clipboard preserves transparency.
- Direct paste into a separate GTK input on the current desktop.
- Keep-open mode returns focus to the destination.
- System keyring saves/reads/deletes a synthetic credential.
- Ctrl+Enter login paste keeps SnipPop open and password bytes are absent from its SQLite database.
- Password expiry clears its own selection without erasing newer clipboard contents.
- Chrome local contenteditable page receives rich HTML, table and plain fallback.
- LibreOffice Writer imports formatted text and actual table cells from the clipboard.

Unresolved:
- Firefox local-page test receives Ctrl+V in the correct focused input, but neither paste event nor document change is observed. Its temporary profile reports a Wayland connection failure and falls back to X11. Focus, plain-text clipboard and backend checks are included in the diagnostic test. Do not treat Firefox compatibility as verified.

Not yet verified:
- Gmail and Google Docs application-specific handling, particularly embedded images and complex signatures.
- GIMP (not found on PATH); actual PNG clipboard data is implemented and independently tested.

Desktop tests use temporary profiles and synthetic content, never existing browser sessions or real passwords. browser_smoke.py defaults to Chrome; set SNIPPOP_TEST_BROWSER=firefox for the Firefox diagnostic. The tests temporarily replace clipboard contents.
