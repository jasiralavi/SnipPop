import os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
tmp=tempfile.TemporaryDirectory(prefix='snippop-login-')
os.environ['SNIPPOP_DATA_DIR']=tmp.name
os.environ['SNIPPOP_NO_IMPORT']='1'
from snippop import *
app=App();app.register(None);app.activate();w=app.window;w.hide()
target=Gtk.Window(title='SnipPop isolated login test');field=Gtk.Entry();target.add(field);target.show_all();target.present();field.grab_focus()
ref='test-'+uuid.uuid4().hex
password='Synthetic SnipPop login test!'
w.vault.put(ref,'test@example.invalid',password)
entry=w.store.save('Test Login',kind='login',username='test@example.invalid',secret_ref=ref,link='example.invalid')
w.refresh(entry)
loop=GLib.MainLoop();errors=[]
def start():
    w.present();GLib.timeout_add(500,lambda:(w.key(w,SimpleNamespace(keyval=Gdk.KEY_Return,state=Gdk.ModifierType.CONTROL_MASK)),False)[1]);GLib.timeout_add(1700,verify);return False

def verify():
    try:
        assert field.get_text()==password
        assert w.get_visible() and target.is_active()
        assert password.encode() not in w.store.path.read_bytes()
        print('PASS: Ctrl+Enter pastes login password, stays open, keeps destination focus, and does not store password in SQLite')
        # Accelerate only the clipboard TTL in this isolated test process.
        GLib.timeout_add_seconds=lambda seconds,callback: GLib.timeout_add(450,callback)
        w.clip.set('temporary secret',secret=True)
        GLib.timeout_add(800,expired)
    except Exception as e:errors.append(str(e));loop.quit()
    return False

def expired():
    try:
        clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        assert clip.wait_for_text()!='temporary secret'
        w.clip.set('old secret',secret=True)
        clip.set_text('new ordinary clipboard',-1)
        GLib.timeout_add(800,replaced)
    except Exception as e:errors.append(str(e));loop.quit()
    return False

def replaced():
    try:
        assert Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()=='new ordinary clipboard'
        print('PASS: password expiry clears its own clipboard and preserves replacement clipboard content')
    except Exception as e:errors.append(str(e))
    loop.quit();return False
GLib.timeout_add(700,start)
GLib.timeout_add(12000,lambda:(errors.append('Timed out'),loop.quit(),False)[-1])
try:loop.run()
finally:w.vault.remove(ref);w.destroy();target.destroy()
if errors:raise RuntimeError(errors)
