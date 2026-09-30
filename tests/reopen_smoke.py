import os,sys,tempfile,subprocess
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
tmp=tempfile.TemporaryDirectory();os.environ['SNIPPOP_DATA_DIR']=tmp.name;os.environ['SNIPPOP_NO_IMPORT']='1'
from snippop import *
app=App();app.register(None);app.activate();w=app.window
text=w.store.save('Sample','Example');w.store.change(text,'pinned',True)
w.store.save('Login',kind='login',username='sample@example.invalid',secret_ref='dummy')
w.refresh()
assert [c.get_title() for c in w.tree.get_columns()]==['Keyword','Content']
assert any(r[1]=='📄 ★ Sample' for r in w.model)
assert any(r[1]=='🔑 Login' for r in w.model)
event=SimpleNamespace(keyval=Gdk.KEY_N,state=Gdk.ModifierType.CONTROL_MASK|Gdk.ModifierType.SHIFT_MASK)
w.key(w,event)
editors=[x for x in Gtk.Window.list_toplevels() if isinstance(x,Editor)]
assert len(editors)==1 and editors[0].login
editors[0].destroy()
print('PASS: two columns, type-before-pin icons, Ctrl+Shift+N opens login editor')
other=Gtk.Window(title='Isolated focus target');other.set_default_size(250,100)
loop=GLib.MainLoop();errors=[];children=[];phase=0

def launch():
 children.append(subprocess.Popen(['/usr/bin/python3',str(ROOT/'snippop.py')],env=os.environ.copy()))
 GLib.timeout_add(1100,verify)
 return False

def prepare():
 w.search.set_text('Sample')
 if phase==1:
  w.store.set_setting('remember_search',True);w.hide()
 other.show_all();other.present()
 native=other.get_window()
 if other.get_display().__class__.__name__=='X11Display':
  gi.require_version('GdkX11','3.0')
  from gi.repository import GdkX11
  native.focus(GdkX11.x11_get_server_time(native))
 GLib.timeout_add(400,launch)
 return False

def verify():
 global phase
 try:
  assert w.is_active() and w.get_visible(),'Relaunch did not focus SnipPop'
  assert w.search.has_focus(),'Search lacks keyboard focus'
  assert w.search.get_text()==('' if phase==0 else 'Sample')
  print('PASS: remote launch focuses '+('visible window and clears search by default' if phase==0 else 'hidden window and retains search when enabled'))
  if phase==0:
   phase=1;GLib.timeout_add(200,prepare)
  else:loop.quit()
 except Exception as e:errors.append(str(e));loop.quit()
 return False
GLib.timeout_add(600,prepare)
GLib.timeout_add_seconds(10,lambda:(errors.append('Timed out'),loop.quit(),False)[-1])
loop.run();other.destroy();w.destroy()
for child in children:child.wait(timeout=3)
if errors:raise RuntimeError(errors)
