import os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
tmp=tempfile.TemporaryDirectory();os.environ['SNIPPOP_DATA_DIR']=tmp.name;os.environ['SNIPPOP_NO_IMPORT']='1'
from snippop import *
import cairo
app=App();app.register(None);app.activate();w=app.window
rich=w.store.save('rich','<b>Bold example</b>')
login=w.store.save('login',kind='login',username='test@example.invalid',secret_ref='not-a-real-secret')
w.refresh(rich)
clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
ctrl=Gdk.ModifierType.CONTROL_MASK;shift=Gdk.ModifierType.SHIFT_MASK;alt=Gdk.ModifierType.MOD1_MASK

def press(key,state):
    return w.key(w,SimpleNamespace(keyval=key,state=state))

def close_dialog(title,screenshot=False):
    def close():
        for d in Gtk.Window.list_toplevels():
            if isinstance(d,Gtk.Dialog) and d.get_title()==title:
                if screenshot:
                    width,height=d.get_size();surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,width,height)
                    d.draw(cairo.Context(surface));surface.write_to_png('/tmp/snippop-shortcuts.png')
                d.response(Gtk.ResponseType.CLOSE)
        return False
    GLib.timeout_add(350,close)

loop=GLib.MainLoop();errors=[]
def check():
    try:
        assert press(Gdk.KEY_c,ctrl)
        assert clip.wait_for_text()=='Bold example'
        assert clip.wait_is_target_available(Gdk.Atom.intern('text/html',False))
        assert press(Gdk.KEY_C,ctrl|shift)
        assert clip.wait_for_text()=='Bold example'
        assert not clip.wait_is_target_available(Gdk.Atom.intern('text/html',False))
        for key,expected in [(Gdk.KEY_3,'login'),(Gdk.KEY_4,'text'),(Gdk.KEY_5,'link'),(Gdk.KEY_6,'image')]:
            press(key,alt);assert w.filters.get_active_id()==expected
        press(Gdk.KEY_3,alt)
        assert w.selected()['id']==login
        press(Gdk.KEY_c,ctrl);assert clip.wait_for_text()=='test@example.invalid'
        press(Gdk.KEY_C,ctrl|shift);assert clip.wait_for_text()=='test@example.invalid'
        print('PASS: rich/plain copy, login username copy, and remapped filters')
        close_dialog('SnipPop Settings');assert press(Gdk.KEY_o,ctrl)
        close_dialog('Keyboard shortcuts',True);assert press(Gdk.KEY_slash,ctrl)
        close_dialog('Keyboard shortcuts');assert press(Gdk.KEY_question,ctrl|shift)
        print('PASS: Settings and both shortcut-guide accelerators')
        editor=Editor(w,login=True)
        assert not editor.password.get_visibility()
        editor.password.emit('icon-press',Gtk.EntryIconPosition.SECONDARY,None)
        assert editor.password.get_visibility()
        editor.password.emit('icon-press',Gtk.EntryIconPosition.SECONDARY,None)
        assert not editor.password.get_visibility()
        editor.destroy()
        print('PASS: reveal/conceal icon; password starts masked')
    except Exception as e:errors.append(repr(e))
    loop.quit();return False
GLib.timeout_add(600,check);loop.run();w.destroy()
if errors:raise RuntimeError(errors)
