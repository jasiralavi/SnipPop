#!/usr/bin/python3
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gio, Gtk
binding = '<Control><Super>x'
wanted = Gtk.accelerator_parse(binding)
media = Gio.Settings.new('org.gnome.settings-daemon.plugins.media-keys')
path = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/snippop/'
paths = list(media.get_strv('custom-keybindings'))
for schema in ('org.gnome.desktop.wm.keybindings', 'org.gnome.mutter.keybindings', 'org.gnome.settings-daemon.plugins.media-keys'):
    settings = Gio.Settings.new(schema)
    for key in settings.props.settings_schema.list_keys():
        value = settings.get_value(key)
        if value.get_type_string() == 'as':
            for candidate in value.unpack():
                if candidate.startswith('<') and Gtk.accelerator_parse(candidate) == wanted:
                    raise SystemExit('Shortcut already in use; launcher installed without a global shortcut.')
for other in paths:
    if other == path: continue
    settings = Gio.Settings.new_with_path('org.gnome.settings-daemon.plugins.media-keys.custom-keybinding', other)
    if Gtk.accelerator_parse(settings.get_string('binding')) == wanted:
        raise SystemExit('Shortcut already in use; launcher installed without a global shortcut.')
shortcut = Gio.Settings.new_with_path('org.gnome.settings-daemon.plugins.media-keys.custom-keybinding', path)
shortcut.set_string('name','SnipPop')
shortcut.set_string('command',str(Path.home()/'Softwares/SnipPop/launch_snippop.sh'))
shortcut.set_string('binding',binding)
if path not in paths:
    media.set_strv('custom-keybindings',paths+[path])
Gio.Settings.sync()
print('SnipPop shortcut: Ctrl+Super+X')
