import os
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = tempfile.TemporaryDirectory()
os.environ['SNIPPOP_DATA_DIR'] = tmp.name
os.environ['SNIPPOP_NO_IMPORT'] = '1'
from snippop import *
app = App()
app.register(None)
app.activate()
snip = app.window
snip.hide()
target = Gtk.Window(title='SnipPop isolated paste test')
field = Gtk.Entry()
target.add(field)
target.show_all()
target.present()
field.grab_focus()
snip.store.save('test', 'SnipPop paste verified')
snip.refresh()
loop = GLib.MainLoop()
errors = []
def invoke():
    snip.present()
    GLib.timeout_add(600, paste)
    return False

def paste():
    snip.paste()
    GLib.timeout_add(1300, verify)
    return False

def verify():
    try:
        assert field.get_text() == 'SnipPop paste verified', repr(field.get_text())
        assert not snip.get_visible()
        print('PASS: direct Wayland paste into prior application')
        snip.store.set_setting('close_after_paste', False)
        field.set_text('')
        snip.present()
        GLib.timeout_add(600, paste_kept)
    except Exception as exc:
        errors.append(str(exc)); loop.quit()
    return False

def paste_kept():
    snip.paste()
    GLib.timeout_add(1300, verify_kept)
    return False

def verify_kept():
    try:
        assert field.get_text() == 'SnipPop paste verified', repr(field.get_text())
        assert snip.get_visible()
        assert target.is_active(), 'SnipPop stole focus'
        print('PASS: keep-open paste retains destination focus')
        # Only temporary synthetic credentials are used, then removed.
        ref = 'test-' + uuid.uuid4().hex
        try:
            snip.vault.put(ref, 'test@example.invalid', 'synthetic-test-password')
            assert snip.vault.get(ref)['password'] == 'synthetic-test-password'
            print('PASS: system keyring store/retrieve')
        finally:
            snip.vault.remove(ref)
    except Exception as exc:
        errors.append(str(exc))
    loop.quit()
    return False
GLib.timeout_add(800, invoke)
GLib.timeout_add_seconds(20, lambda: (errors.append('Timed out'), loop.quit(), False)[-1])
loop.run()
target.destroy(); snip.destroy()
if errors:
    raise RuntimeError(errors)
