#!/usr/bin/python3
"""SnipPop — a local, keyboard-first snippet library."""
import base64
import html
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, Gdk, Gio, GLib, WebKit2, GdkPixbuf, Pango
from core import Store, normalize, plain_html, web_url
from desktop import Clipboard, Vault, paste_command, send_paste

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('SNIPPOP_DATA_DIR', str(Path.home() / '.local/share/snippop')))
LEGACY = Path.home() / 'Softwares/Snippets/snippets.db'


def message(parent, text):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.INFO,
                               buttons=Gtk.ButtonsType.OK, text=text)
    dialog.run()
    dialog.destroy()


def button(label, callback):
    b = Gtk.Button(label=label)
    b.connect('clicked', lambda *_: callback())
    return b


def raster_data(data):
    loader = GdkPixbuf.PixbufLoader()
    loader.write(data)
    loader.close()
    pixbuf = loader.get_pixbuf()
    if pixbuf.get_width() * pixbuf.get_height() > 40000000:
        raise ValueError('Image is too large. Please resize it first.')
    ok, png = pixbuf.save_to_bufferv('png', [], [])
    return bytes(png)


class Editor(Gtk.Window):
    def __init__(self, owner, row=None, login=False, duplicate=False):
        super().__init__(title='Add Login' if login else 'Edit Snippet' if row else 'Add Snippet', transient_for=owner)
        self.owner, self.row, self.login, self.duplicate = owner, row, login, duplicate
        self.set_default_size(740, 570 if not login else 360)
        self.set_modal(True)
        self.set_border_width(18)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(box)
        self.keyword = Gtk.Entry(placeholder_text='Keyword — e.g. sig.work or My Gmail')
        box.pack_start(Gtk.Label(label='Keyword', xalign=0), False, False, 0)
        box.pack_start(self.keyword, False, False, 0)
        self.tags = Gtk.Entry(placeholder_text='Tags (comma-separated; search with #tag)')
        if owner.store.setting('tags', False):
            box.pack_start(self.tags, False, False, 0)
        if login:
            self.username = Gtk.Entry(placeholder_text='Username · Enter to paste')
            self.password = Gtk.Entry(placeholder_text='Password · Ctrl+Enter to paste', visibility=False)
            self.password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            self.password.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, 'view-reveal-symbolic')
            self.password.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, 'Show password')
            self.password.set_icon_activatable(Gtk.EntryIconPosition.SECONDARY, True)
            self.password.connect('icon-press', self.toggle_password)
            self.link = Gtk.Entry(placeholder_text='Link (optional) · Shift+Enter to open')
            for label, field in [('Username', self.username), ('Password', self.password), ('Link', self.link)]:
                box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
                box.pack_start(field, False, False, 0)
            box.pack_start(Gtk.Label(label='Passwords are stored in your system keyring.', xalign=0), False, False, 0)
        else:
            manager = WebKit2.UserContentManager()
            manager.register_script_message_handler('action')
            manager.register_script_message_handler('importHtml')
            manager.connect('script-message-received::action', self.web_action)
            manager.connect('script-message-received::importHtml', self.import_html)
            context = WebKit2.WebContext.new_ephemeral()
            self.web = WebKit2.WebView(web_context=context, user_content_manager=manager)
            self.web.get_settings().set_enable_write_console_messages_to_stdout(False)
            self.web.connect('decide-policy', self.policy)
            self.web.connect('load-changed', self.loaded)
            self.web.load_html((ROOT / 'editor.html').read_text(), None)
            box.pack_start(self.web, True, True, 0)
        actions = Gtk.Box(spacing=8)
        if not login:
            actions.pack_start(button('Capture clipboard', self.capture), False, False, 0)
        actions.pack_end(button('Save · Ctrl+S', self.save), False, False, 0)
        actions.pack_end(button('Cancel', self.destroy), False, False, 0)
        box.pack_end(actions, False, False, 0)
        if row:
            self.keyword.set_text(row['keyword'] + (' copy' if duplicate else ''))
            self.tags.set_text(row['tags'])
            if login:
                self.username.set_text(row['plain'])
                self.link.set_text(row['link'])
                self.password.set_placeholder_text('Leave blank to copy the saved password' if duplicate else 'Leave blank to keep the saved password')
        self.connect('key-press-event', self.key)
        self.show_all()
        self.keyword.grab_focus()
        if duplicate:
            self.keyword.select_region(0, -1)

    def toggle_password(self, entry, position, event):
        if position != Gtk.EntryIconPosition.SECONDARY:
            return
        visible = not entry.get_visibility()
        entry.set_visibility(visible)
        entry.set_icon_from_icon_name(position, 'view-conceal-symbolic' if visible else 'view-reveal-symbolic')
        entry.set_icon_tooltip_text(position, 'Hide password' if visible else 'Show password')

    def policy(self, web, decision, kind):
        if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_request().get_uri()
            if uri != 'about:blank':
                decision.ignore()
                return True
        return False

    def loaded(self, web, event):
        if event == WebKit2.LoadEvent.FINISHED and self.row:
            self.js('setContent(' + json.dumps(self.row['rich']) + ')')

    def js(self, code, callback=None):
        self.web.run_javascript(code, None, callback, None)

    def import_html(self, manager, result):
        try:
            raw = result.get_js_value().to_string()
            clean, _, _, _ = normalize(raw)
            self.js('command("insertHTML",' + json.dumps(clean) + ')')
            if 'src="http' in raw or 'src="file:' in raw:
                message(self, 'Linked images were omitted. Use Image to embed a local copy.')
        except Exception as e:
            message(self, str(e))

    def web_action(self, manager, result):
        action = result.get_js_value().to_string()
        if action == 'save':
            self.save()
        elif action == 'image':
            self.add_image()

    def add_image(self):
        dialog = Gtk.FileChooserDialog(title='Insert image', transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Insert', Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name('Images')
        filt.add_pixbuf_formats()
        dialog.add_filter(filt)
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                path = Path(dialog.get_filename())
                if path.stat().st_size > 15 * 1024 * 1024:
                    raise ValueError('Choose an image smaller than 15 MB.')
                data = raster_data(path.read_bytes())
                self.js('insertImage(' + json.dumps('data:image/png;base64,' + base64.b64encode(data).decode()) + ')')
            except Exception as e:
                message(self, str(e))
        dialog.destroy()

    def capture(self):
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        data = clip.wait_for_contents(Gdk.Atom.intern('text/html', False))
        try:
            if data and data.get_length() > 0:
                clean, _, _, _ = normalize(bytes(data.get_data()).decode('utf-8', errors='replace').rstrip('\x00'))
                self.js('setContent(' + json.dumps(clean) + ')')
            else:
                image = clip.wait_for_image()
                if image:
                    ok, data = image.save_to_bufferv('png', [], [])
                    self.js('setContent(' + json.dumps('<img src="data:image/png;base64,' + base64.b64encode(data).decode() + '">') + ')')
                else:
                    self.js('setContent(' + json.dumps(plain_html(clip.wait_for_text() or '')) + ')')
        except Exception as e:
            message(self, str(e))

    def save(self):
        if self.login:
            self.finish_save('')
        else:
            def received(web, result, *_):
                try:
                    value = web.run_javascript_finish(result).get_js_value().to_string()
                    self.finish_save(value)
                except Exception as e:
                    message(self, str(e))
            self.js('getContent()', received)

    def finish_save(self, rich):
        ref = None
        try:
            keyword = self.keyword.get_text().strip()
            entry_id = self.row['id'] if self.row and not self.duplicate else None
            existing = self.owner.store.db.execute('SELECT id FROM entries WHERE keyword=?', (keyword,)).fetchone()
            if not keyword:
                raise ValueError('A keyword is required.')
            if existing and existing[0] != entry_id:
                raise ValueError('That keyword already exists. Choose another keyword.')
            if self.login:
                username = self.username.get_text().strip()
                link = web_url(self.link.get_text())
                password = self.password.get_text()
                if not username:
                    raise ValueError('A username is required.')
                oldref = self.row['secret_ref'] if self.row else ''
                if not password:
                    if not oldref:
                        raise ValueError('A password is required.')
                    password = self.owner.vault.get(oldref)['password']
                # Write a fresh secret, then commit the reference; failed saves retain the old login.
                ref = uuid.uuid4().hex
                self.owner.vault.put(ref, username, password)
                entry_id = self.owner.store.save(keyword, entry_id=entry_id, username=username, kind='login',
                            link=link, secret_ref=ref, tags=self.tags.get_text())
                ref = None
                self.password.set_text('')
                # Keep previous keyring records so the rotating database backups remain restorable.
            else:
                entry_id = self.owner.store.save(keyword, rich, entry_id=entry_id, tags=self.tags.get_text())
            self.owner.refresh(entry_id)
            self.destroy()
        except Exception as e:
            if ref:
                try:
                    self.owner.vault.remove(ref)
                except Exception:
                    pass
            message(self, str(e))

    def key(self, widget, event):
        key = Gdk.keyval_name(event.keyval).lower()
        if key == 'escape':
            self.destroy()
            return True
        if key == 's' and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.save()
            return True
        return False


class ContentRenderer(Gtk.CellRendererText):
    """Three visible lines, wrapping to the actual column width."""
    def do_get_preferred_height(self, widget):
        layout = widget.create_pango_layout('Ag')
        height = layout.get_pixel_size()[1] * 3 + 12
        return height, height

    def do_get_preferred_height_for_width(self, widget, width):
        return self.do_get_preferred_height(widget)

    def do_render(self, cr, widget, background_area, cell_area, flags):
        layout = widget.create_pango_layout(self.get_property('text') or '')
        layout.set_width(max(1, cell_area.width - 12) * Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        line_height = widget.create_pango_layout('Ag').get_pixel_size()[1]
        layout.set_height(line_height * 3 * Pango.SCALE)
        context = widget.get_style_context()
        context.save()
        state = widget.get_state_flags()
        if flags & Gtk.CellRendererState.SELECTED:
            state |= Gtk.StateFlags.SELECTED
        context.set_state(state)
        cr.save()
        cr.rectangle(cell_area.x, cell_area.y + 6, cell_area.width, line_height * 3)
        cr.clip()
        Gtk.render_layout(context, cr, cell_area.x + 6, cell_area.y + 6, layout)
        cr.restore()
        context.restore()


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='SnipPop')
        self.set_default_size(760, 630)
        self.set_icon_from_file(str(ROOT / 'snippop.svg'))
        self.set_border_width(18)
        self.store = Store(DATA, LEGACY if not os.environ.get('SNIPPOP_NO_IMPORT') else None)
        self.vault, self.clip = Vault(), Clipboard()
        self.busy = False
        self.last_deleted = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(box)
        header = Gtk.Box(spacing=8)
        title = Gtk.Label(xalign=0)
        title.set_markup('<span size="xx-large" weight="bold">SnipPop</span>')
        header.pack_start(title, True, True, 0)
        header.pack_end(button('Settings', self.settings), False, False, 0)
        header.pack_end(button('+ Login', lambda: self.edit(login=True)), False, False, 0)
        header.pack_end(button('+ Snippet', self.edit), False, False, 0)
        box.pack_start(header, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text='Search keyword, content, or #tag…')
        self.search.connect('search-changed', lambda *_: self.refresh())
        box.pack_start(self.search, False, False, 0)
        controls = Gtk.Box(spacing=8)
        self.filters = Gtk.ComboBoxText()
        for key, label in [('all','All · Alt+1'),('pinned','Pinned · Alt+2'),('login','Passwords · Alt+3'),('text','Text only · Alt+4'),('link','Link only · Alt+5'),('image','Image only · Alt+6')]:
            self.filters.append(key, label)
        self.filters.set_active_id('all')
        self.filters.connect('changed', lambda *_: self.refresh())
        self.sort = Gtk.ComboBoxText()
        for key, label in [('newest','Newest · Alt+N'),('oldest','Oldest · Alt+O'),('frequent','Most frequent · Alt+M')]:
            self.sort.append(key, label)
        self.sort.set_active_id(self.store.setting('sort', 'newest'))
        self.sort.connect('changed', self.sort_changed)
        controls.pack_start(self.filters, False, False, 0)
        controls.pack_end(self.sort, False, False, 0)
        box.pack_start(controls, False, False, 0)
        self.model = Gtk.ListStore(str, str, str, str)
        self.tree = Gtk.TreeView(model=self.model)
        for index, title in [(1,'Keyword'),(2,'Content')]:
            render = ContentRenderer() if index == 2 else Gtk.CellRendererText()
            render.set_property('ellipsize', Pango.EllipsizeMode.END)
            render.set_property('ypad', 6)
            render.set_property('yalign', 0.0)
            col = Gtk.TreeViewColumn(title, render, text=index)
            col.set_expand(index == 2)
            col.set_min_width(180 if index == 1 else 70)
            if index == 2:
                col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
                col.set_fixed_width(320)
            self.tree.append_column(col)
        self.tree.connect('row-activated', lambda *_: self.paste())
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.tree)
        box.pack_start(scroll, True, True, 0)
        actions = Gtk.Box(spacing=6)
        for label, callback in [('Paste', self.paste),('Copy', self.copy_menu),('Edit', lambda: self.edit_selected()),
                                ('Pin',self.pin),('Duplicate',self.duplicate),('Delete',self.delete)]:
            actions.pack_start(button(label, callback), False, False, 0)
        box.pack_start(actions, False, False, 0)
        self.connect('key-press-event', self.key)
        self.connect('delete-event', lambda *_: self.dismiss())
        self.refresh()
        self.show_all()
        self.search.grab_focus()

    def dismiss(self):
        self.hide()
        return True

    def sort_changed(self, *_):
        self.store.set_setting('sort', self.sort.get_active_id())
        self.refresh()

    def selected(self):
        model, it = self.tree.get_selection().get_selected()
        return self.store.get(model[it][0]) if it is not None else None

    def refresh(self, selected_id=None):
        if not hasattr(self, 'tree'):
            return
        row = self.selected()
        selected_id = selected_id or (row['id'] if row else None)
        self.model.clear()
        select_it = None
        for r in self.store.search(self.search.get_text(), self.filters.get_active_id(), self.sort.get_active_id()):
            icon = {'login': '🔑', 'text': '📄', 'image': '🖼️', 'link': '🔗', 'mixed': '📄'}.get(r['kind'], '📄')
            label = icon + ' ' + ('★ ' if r['pinned'] else '') + r['keyword']
            it = self.model.append([r['id'], label, '\n'.join(line.strip() for line in r['plain'].splitlines() if line.strip())[:1500] or 'Image', r['kind'].title()])
            if r['id'] == selected_id:
                select_it = it
        if select_it is None:
            select_it = self.model.get_iter_first()
        if select_it is not None:
            self.tree.get_selection().select_iter(select_it)

    def edit(self, login=False):
        Editor(self, login=login)

    def edit_selected(self):
        row = self.selected()
        if row:
            Editor(self, row, login=row['kind'] == 'login')

    def duplicate(self):
        row = self.selected()
        if row:
            Editor(self, row, login=row['kind'] == 'login', duplicate=True)

    def pin(self):
        r = self.selected()
        if r:
            self.store.change(r['id'], 'pinned', not r['pinned'])
            self.refresh(r['id'])

    def delete(self):
        r = self.selected()
        if r:
            self.store.change(r['id'], 'deleted', 1)
            self.last_deleted = r['id']
            self.refresh()

    def payload(self, row, plain=False):
        if row['kind'] == 'login':
            return (self.vault.get(row['secret_ref'])['password'] if plain else row['plain']), None, None
        rich, text, kind, images = normalize(self.store.expand(row['rich'], (row['keyword'],)))
        if plain and not text:
            raise ValueError('This image has no plain-text version. Use Enter to paste the image.')
        png = raster_data(base64.b64decode(images[0].split(',',1)[1])) if kind == 'image' and not plain else None
        return text, None if plain else rich, png

    def paste(self, plain=False, copy_only=False):
        row = self.selected()
        if not row or self.busy:
            return
        try:
            if not copy_only:
                paste_command()
            text, rich, image = self.payload(row, plain)
            self.clip.set(text, rich, image, secret=row['kind'] == 'login' and plain)
        except Exception as e:
            message(self, str(e))
            return
        if copy_only:
            self.store.change(row['id'], 'uses', row['uses'] + 1)
            return
        self.busy = True
        keep = row['kind'] == 'login' or not self.store.setting('close_after_paste', True)
        # Unmap to let the compositor return focus to the preceding application.
        self.hide()
        def dispatch():
            try:
                send_paste()
                self.store.change(row['id'], 'uses', row['uses'] + 1)
                if keep:
                    # Remap without taking keyboard focus away from the destination.
                    self.set_focus_on_map(False)
                    self.show()
                    self.set_focus_on_map(True)
            except Exception as e:
                self.present()
                message(self, str(e))
            finally:
                self.busy = False
            return False
        GLib.timeout_add(350, dispatch)

    def copy_selected(self, plain=False):
        row = self.selected()
        if row:
            # Both copy accelerators copy the username for a login. Password
            # copying remains an explicitly labelled menu action.
            self.paste(plain=plain and row['kind'] != 'login', copy_only=True)

    def copy_menu(self):
        menu = Gtk.Menu()
        row = self.selected()
        login = row and row['kind'] == 'login'
        for label, plain in [('Copy username · Ctrl+C' if login else 'Copy rich · Ctrl+C',False),('Copy password' if login else 'Copy plain · Ctrl+Shift+C',True)]:
            item = Gtk.MenuItem(label=label)
            item.connect('activate', lambda _, p=plain: self.paste(p, True))
            menu.append(item)
        if login:
            item = Gtk.MenuItem(label='Open link · Shift+Enter')
            item.set_sensitive(bool(row['link']))
            item.connect('activate', lambda *_: self.open_link())
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(None)

    def open_link(self):
        row = self.selected()
        if row and row['kind'] == 'login' and row['link']:
            try:
                Gio.AppInfo.launch_default_for_uri(web_url(row['link']), None)
            except Exception as e:
                message(self, str(e))

    def show_shortcuts(self, parent=None):
        dialog = Gtk.Dialog(title='Keyboard shortcuts', transient_for=parent or self, modal=True)
        dialog.add_button('Close', Gtk.ResponseType.CLOSE)
        dialog.set_default_size(620, 580)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        grid = Gtk.Grid(column_spacing=32, row_spacing=10, margin=20)
        rows = [
            ('FUNCTION', 'SHORTCUT'),
            ('Paste rich / username', 'Enter'),
            ('Paste plain / password', 'Ctrl+Enter'),
            ('Open login link', 'Shift+Enter'),
            ('Copy rich / username', 'Ctrl+C'),
            ('Copy plain / username', 'Ctrl+Shift+C'),
            ('Open Settings / Options', 'Ctrl+O'),
            ('Keyboard shortcuts', 'Ctrl+/ or Ctrl+?'),
            ('Add snippet', 'Ctrl+N'),
            ('Add password / login', 'Ctrl+Shift+N'),
            ('Edit selected', 'Ctrl+E'),
            ('Duplicate selected', 'Ctrl+D'),
            ('Pin / unpin', 'Ctrl+P'),
            ('Search', 'Ctrl+F'),
            ('Filter: All', 'Alt+1'),
            ('Filter: Pinned', 'Alt+2'),
            ('Filter: Passwords', 'Alt+3'),
            ('Filter: Text only', 'Alt+4'),
            ('Filter: Link only', 'Alt+5'),
            ('Filter: Image only', 'Alt+6'),
            ('Sort: Newest', 'Alt+N'),
            ('Sort: Oldest', 'Alt+O'),
            ('Sort: Most frequent', 'Alt+M'),
            ('Delete (results focused)', 'Delete'),
            ('Undo delete (results focused)', 'Ctrl+Z'),
            ('Save (editor)', 'Ctrl+S'),
            ('Dismiss', 'Esc'),
        ]
        for index, pair in enumerate(rows):
            for column, text in enumerate(pair):
                label = Gtk.Label(label=text, xalign=0)
                label.override_font(Pango.FontDescription('Monospace Bold 11' if index == 0 else 'Monospace 11'))
                grid.attach(label, column, index, 1, 1)
        scroll.add(grid)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def settings(self):
        d = Gtk.Dialog(title='SnipPop Settings', transient_for=self, modal=True)
        d.add_button('Done', Gtk.ResponseType.CLOSE)
        box = d.get_content_area()
        box.set_border_width(18)
        box.set_spacing(12)
        for key, label, default in [('remember_search','Remember previous search when opening SnipPop',False),('close_after_paste','Close after pasting snippets (logins always stay open)',True),('tags','Show optional tags in the editor',False)]:
            check = Gtk.CheckButton(label=label)
            check.set_active(self.store.setting(key, default))
            check.connect('toggled', lambda w, k=key: self.store.set_setting(k, w.get_active()))
            box.add(check)
        box.add(button('Export snippets…', lambda: self.file_action(False)))
        box.add(button('Import snippets…', lambda: self.file_action(True)))
        box.add(button('Trash / Restore…', self.trash))
        box.add(Gtk.Label(label='Exports exclude logins. Daily database backups retain usernames and keyring references.\nPasswords stay in the system keyring; it must be backed up separately.\nPassword clipboard expires after 20 seconds; clipboard history may retain copies.'))
        box.add(button('Keyboard shortcuts · Ctrl+/', lambda: self.show_shortcuts(d)))
        box.add(button('Quit SnipPop', lambda: self.get_application().quit()))
        d.show_all()
        d.run()
        d.destroy()

    def trash(self):
        d = Gtk.Dialog(title='Trash — select an entry to restore', transient_for=self, modal=True)
        d.add_buttons('Close', Gtk.ResponseType.CANCEL, 'Restore', Gtk.ResponseType.OK)
        combo = Gtk.ComboBoxText()
        for r in self.store.db.execute('SELECT id,keyword FROM entries WHERE deleted=1 ORDER BY updated DESC'):
            combo.append(r['id'], r['keyword'])
        combo.set_active(0)
        d.get_content_area().add(combo)
        d.show_all()
        if d.run() == Gtk.ResponseType.OK and combo.get_active_id():
            self.store.change(combo.get_active_id(), 'deleted', 0)
            self.refresh(combo.get_active_id())
        d.destroy()

    def file_action(self, importing):
        d = Gtk.FileChooserDialog(title='Import snippets' if importing else 'Export snippets', transient_for=self,
                                 action=Gtk.FileChooserAction.OPEN if importing else Gtk.FileChooserAction.SAVE)
        d.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Import' if importing else 'Export', Gtk.ResponseType.OK)
        if not importing:
            d.set_current_name('snippop-export.json')
            d.set_do_overwrite_confirmation(True)
        if d.run() == Gtk.ResponseType.OK:
            try:
                if importing:
                    count = self.store.import_file(d.get_filename())
                    self.refresh()
                    message(self, f'Imported {count} snippets.')
                else:
                    self.store.export(d.get_filename())
            except Exception as e:
                message(self, str(e))
        d.destroy()

    def key(self, widget, event):
        key = Gdk.keyval_name(event.keyval).lower()
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        if key == 'escape':
            self.dismiss()
        elif key in ('return','kp_enter'):
            if shift and not ctrl:
                self.open_link()
            else:
                self.paste(plain=ctrl)
        elif ctrl and key in ('slash', 'question'):
            self.show_shortcuts()
        elif ctrl and key == 'o':
            self.settings()
        elif ctrl and key == 'c':
            self.copy_selected(plain=shift)
        elif ctrl and shift and key == 'n':
            self.edit(login=True)
        elif ctrl and key == 'n':
            self.edit()
        elif ctrl and key == 'e':
            self.edit_selected()
        elif ctrl and key == 'd':
            self.duplicate()
        elif ctrl and key == 'p':
            self.pin()
        elif ctrl and key == 'f':
            self.search.grab_focus()
        elif ctrl and key == 'z' and self.last_deleted and not self.search.has_focus():
            self.store.change(self.last_deleted, 'deleted', 0)
            self.refresh(self.last_deleted)
            self.last_deleted = None
        elif key == 'delete' and self.tree.has_focus():
            self.delete()
        elif alt and key in ('n','o','m'):
            self.sort.set_active_id({'n':'newest','o':'oldest','m':'frequent'}[key])
        elif alt and key in ('1','2','3','4','5','6'):
            self.filters.set_active(int(key)-1)
        elif key in ('down','up') and self.search.has_focus():
            self.tree.grab_focus()
        else:
            return False
        return True


class App(Gtk.Application):
    def __init__(self):
        app_id = 'io.snippop.App'
        if os.environ.get('SNIPPOP_NO_IMPORT') and os.environ.get('SNIPPOP_DATA_DIR'):
            import hashlib
            app_id = 'io.snippop.Test.t' + hashlib.sha256(str(DATA).encode()).hexdigest()[:12]
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.hold()  # Keep serving rich clipboard data after the popup is dismissed.
            self.window = Window(self)
        if not self.window.store.setting('remember_search', False):
            self.window.search.set_text('')
            self.window.refresh()
        self.window.deiconify()
        self.window.set_focus_on_map(True)
        self.window.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.window.show()
        # Remote Gtk.Application activation often has no input timestamp. On
        # X11, use fresh server time so the WM accepts this explicit invocation.
        def foreground():
            window = self.window
            display = window.get_display()
            native = window.get_window()
            timestamp = Gtk.get_current_event_time()
            if display.__class__.__name__ == 'X11Display':
                gi.require_version('GdkX11', '3.0')
                from gi.repository import GdkX11
                timestamp = GdkX11.x11_get_server_time(native)
                pointer = display.get_default_seat().get_pointer()
                _, x, y = pointer.get_position()
                monitor = display.get_monitor_at_point(x, y)
                if monitor:
                    area = monitor.get_workarea()
                    def center():
                        if window.get_visible():
                            frame = native.get_frame_extents()
                            window.set_position(Gtk.WindowPosition.NONE)
                            window.move(area.x + max(0, (area.width - frame.width) // 2),
                                        area.y + max(0, (area.height - frame.height) // 2))
                        return False
                    # Wait for the WM to attach decorations before measuring.
                    GLib.timeout_add(100, center)
            window.present_with_time(timestamp)
            if display.__class__.__name__ == 'X11Display':
                native.raise_()
                native.focus(timestamp)
            window.search.grab_focus()
            return False
        GLib.idle_add(foreground)


if __name__ == '__main__':
    os.umask(0o077)
    sys.exit(App().run(sys.argv))
