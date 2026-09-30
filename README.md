# SnipPop

A native Linux snippet library with one rich editor, automatically generated plain text, and system-keyring logins.

Run `./launch_snippop.sh` or use your configured global shortcut (Super+X). Re-running the launcher brings the existing window forward. Closing the popup leaves a small background process serving clipboard data; Settings → Quit exits it.

## Installation

Install the desktop dependencies listed below, then run:

```sh
/usr/bin/python3 install.py
```

This installs the application under `~/Softwares/SnipPop` and adds an app-menu launcher. Set your preferred global shortcut in the desktop's Keyboard settings. The optional `register_shortcut.py` helper adds **Ctrl+Super+X** only if unused; it does not select Super+X automatically.

The repository contains application code and synthetic test fixtures only. Snippet databases, keyring contents, exports, and local backups are not included.

## Daily use

| Shortcut | Action |
|---|---|
| Enter | Paste rich content, image, or login username |
| Ctrl+Enter | Paste plain text or login password |
| Shift+Enter | Open selected login's link in the default browser |
| Ctrl+O | Settings / Options |
| Ctrl+/ or Ctrl+? | Keyboard shortcut guide |
| Ctrl+C | Copy rich content or login username |
| Ctrl+Shift+C | Copy plain content or login username |
| Ctrl+N | Add snippet |
| Ctrl+Shift+N | Add login |
| Ctrl+E | Edit |
| Ctrl+D | Duplicate into a new editor |
| Ctrl+P | Pin/unpin |
| Alt+1…6 | All, pinned, passwords, text only, link only, image only |
| Alt+N / Alt+O / Alt+M | Newest, oldest, most frequent |
| Ctrl+F | Search |
| Delete | Move selected result to Trash (results must have focus) |
| Ctrl+Z | Undo last deletion (results must have focus) |
| Esc | Dismiss |
| Ctrl+S | Save in the editor |

Search examines keyword and generated plain content only. Exact keyword matches rank first; chosen sort resolves ties. Tags are hidden by default and can be enabled in Settings. A link-only snippet is a URL or one linked label. Tables and mixed image/text content appear under All or Pinned.

Login entries always stay open on paste. Settings controls close-after-paste for other snippets. The popup briefly hides to return focus to the preceding application, then reappears without taking focus if keep-open applies. Choose the destination field before opening SnipPop. Opening a login link never submits a login.

## Content

Paste rich content directly into the editor, use Capture clipboard, or write with the formatting toolbar. Insert local images with Image. Images are embedded in the stored HTML and travel with JSON exports. Plain text is generated on save; images without text have no plain-paste action.

HTML is normalized to a supported subset; scripts, event handlers and remote resources are removed. Linked/remote images must be inserted as local copies. Complex email or Google Docs layouts may change; whole-document headers, footers and page settings are outside snippet scope. Image-only snippets offer actual PNG clipboard data. Mixed snippets offer HTML plus a plain fallback; browser web editors may handle embedded images differently.

Existing `@d@`, `@t@`, `@dt@`, `@dt:YYYY-MM-DD@` and `@keyword@` references are supported. References cannot expand login entries. Fill-in fields and automatic expansion while typing are not included in this first release.

## Storage and recovery

The first launch imports the existing `/home/jasir/Softwares/Snippets/snippets.db` without modifying it. Data lives in `~/.local/share/snippop/snippop.db` with user-only permissions. Up to seven daily database backups are kept alongside it. Settings provides portable JSON import/export and Trash restore. JSON exports exclude logins.

The database stores login keyword, username, link and opaque keyring reference. Passwords and a copy of the username are stored through libsecret in the system keyring. Passwords never enter the SQLite database, ordinary export or logs. Editing a login creates a new secret record; previous secret records are retained so older database backups still work. Deletion is reversible Trash, not permanent credential erasure. Back up the system keyring separately: a database backup cannot reconstruct passwords on another machine.

The keyring may prompt to unlock. Password clipboard contents expire after 20 seconds if SnipPop still owns that selection. A clipboard manager may retain its own copy despite confidentiality hints. SnipPop pastes into the focused field and does not validate the website origin; use domain-aware browser password-manager filling if that protection is required.

## Desktop dependencies

System Python 3, PyGObject, GTK 3, WebKitGTK 4.1, libsecret, and Cairo are used. On Ubuntu the relevant packages are `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1`, `gir1.2-secret-1`.

Wayland direct paste uses an existing ydotool service at `$YDOTOOL_SOCKET` or `/run/user/$UID/.ydotool_socket`; SnipPop does not install or grant privileges to an input service. X11 uses xdotool. Copy remains available if direct paste is unavailable.

To set a global shortcut, assign the launcher in desktop Keyboard settings. The app shortcuts above apply while SnipPop is focused.

## Tests

`/usr/bin/python3 -m unittest discover -s tests -v` runs storage, HTML, migration, search, export and placeholder tests. Desktop smoke tests use isolated data and synthetic content; run only in a desktop session. They create temporary windows and replace the clipboard. The keyring test creates and removes a synthetic credential.

The login editor’s eye icon toggles password visibility. Passwords start masked.

Search starts empty on each launch by default. Enable **Remember previous search when opening SnipPop** in Settings to retain the current search between openings. Type icons appear before the pin star in the Keyword column; mixed rich content uses the document icon.

## Tag filtering

Type `#nk` in the search box to match the exact tag `nk`, ignoring case. Tags in the editor are comma-separated; a leading `#` in a saved tag is optional. Combine tags with text (`#nk invoice`) or require multiple tags (`#nk #work`). Tag filters also combine with the selected type or Pinned filter and sort order. Filtering existing tags works even when the optional Tags editor field is hidden.
