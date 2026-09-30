"""GTK clipboard bridge and desktop keyring. Secrets never go to disk here."""
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import subprocess
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Secret', '1')
from gi.repository import Gtk, Gdk, GLib, Secret


class Vault:
    schema = Secret.Schema.new('io.snippop.Login', Secret.SchemaFlags.NONE, {'reference': Secret.SchemaAttributeType.STRING})

    def put(self, ref, username, password):
        if not Secret.password_store_sync(self.schema, {'reference': ref}, Secret.COLLECTION_DEFAULT,
                'SnipPop login', json.dumps({'username': username, 'password': password}), None):
            raise RuntimeError('The system keyring did not save this login.')

    def get(self, ref):
        value = Secret.password_lookup_sync(self.schema, {'reference': ref}, None)
        if value is None:
            raise RuntimeError('This password is unavailable. Unlock the keyring or edit the login to save it again.')
        return json.loads(value)

    def remove(self, ref):
        Secret.password_clear_sync(self.schema, {'reference': ref}, None)


class Target(C.Structure):
    _fields_ = [('target', C.c_char_p), ('flags', C.c_uint), ('info', C.c_uint)]


class Clipboard:
    """GTK3 omits set_with_data from GI; use its documented C ABI."""
    def __init__(self):
        self.lib = C.CDLL('libgtk-3.so.0')
        self.gdk = C.CDLL('libgdk-3.so.0')
        self.gdk.gdk_atom_intern_static_string.argtypes = [C.c_char_p]
        self.gdk.gdk_atom_intern_static_string.restype = C.c_void_p
        self.lib.gtk_clipboard_get.argtypes = [C.c_void_p]
        self.lib.gtk_clipboard_get.restype = C.c_void_p
        self.ptr = self.lib.gtk_clipboard_get(self.gdk.gdk_atom_intern_static_string(b'CLIPBOARD'))
        self.Get = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_uint, C.c_void_p)
        self.Clear = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)
        self.lib.gtk_clipboard_set_with_data.argtypes = [C.c_void_p, C.POINTER(Target), C.c_uint, self.Get, self.Clear, C.c_void_p]
        self.lib.gtk_clipboard_set_with_data.restype = C.c_int
        self.lib.gtk_selection_data_get_target.argtypes = [C.c_void_p]
        self.lib.gtk_selection_data_get_target.restype = C.c_void_p
        self.lib.gtk_selection_data_set.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, C.c_int]
        self.lib.gtk_clipboard_clear.argtypes = [C.c_void_p]
        self.callbacks = {}
        self.serial = 0
        self.active_serial = None

    def set(self, plain, rich=None, image=None, secret=False):
        self.serial += 1
        serial = self.serial
        data = [('UTF8_STRING', plain.encode()), ('text/plain;charset=utf-8', plain.encode()), ('text/plain', plain.encode())]
        if rich:
            data.append(('text/html', ('<meta charset="utf-8">' + rich).encode()))
        if image:
            data.append(('image/png', image))
        if secret:
            # Hints respected by some clipboard managers, not a universal guarantee.
            data.extend([('x-kde-passwordManagerHint', b'secret'), ('application/x-keepassxc-secret', b'')])
        def provide(_clipboard, selection, index, _user):
            payload = data[index][1]
            self.lib.gtk_selection_data_set(selection, self.lib.gtk_selection_data_get_target(selection), 8, payload, len(payload))
        def clear(*_):
            if self.active_serial == serial:
                self.active_serial = None
            # Release C callback references only after this callback has returned.
            def release():
                self.callbacks.pop(serial, None)
                return False
            GLib.idle_add(release)
        get_cb, clear_cb = self.Get(provide), self.Clear(clear)
        targets = (Target * len(data))(*(Target(m.encode(), 0, i) for i, (m, _) in enumerate(data)))
        self.callbacks[serial] = (get_cb, clear_cb, targets, data)
        if not self.lib.gtk_clipboard_set_with_data(self.ptr, targets, len(data), get_cb, clear_cb, None):
            self.callbacks.pop(serial, None)
            raise RuntimeError('Could not publish the clipboard.')
        self.active_serial = serial
        if secret:
            def expire():
                # Ownership loss removes this serial: never erase a newer clipboard.
                if self.active_serial == serial:
                    self.lib.gtk_clipboard_clear(self.ptr)
                return False
            GLib.timeout_add_seconds(20, expire)


def paste_command():
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        executable = shutil.which('ydotool')
        candidates = [os.environ.get('YDOTOOL_SOCKET', ''), f'/run/user/{os.getuid()}/.ydotool_socket']
        socket = next((p for p in candidates if p and Path(p).exists()), None)
        if not executable or not socket:
            raise RuntimeError('Direct paste needs a running ydotool service on Wayland. You can still use Copy from the menu.')
        env = os.environ.copy()
        env['YDOTOOL_SOCKET'] = socket
        # Release invocation modifiers before synthesizing Ctrl+V.
        return [executable, 'key', '29:0', '97:0', '42:0', '54:0', '56:0', '100:0', '29:1', '47:1', '47:0', '29:0'], env
    executable = shutil.which('xdotool')
    if not executable:
        raise RuntimeError('Install xdotool to enable direct paste on X11.')
    return [executable, 'key', '--clearmodifiers', 'ctrl+v'], os.environ.copy()


def send_paste():
    command, env = paste_command()
    result = subprocess.run(command, env=env, capture_output=True, timeout=5)
    if result.returncode:
        raise RuntimeError('The desktop input helper could not paste. Check that its service is running.')
