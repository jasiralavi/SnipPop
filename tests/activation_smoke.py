import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
tmp=tempfile.TemporaryDirectory()
os.environ['SNIPPOP_DATA_DIR']=tmp.name
os.environ['SNIPPOP_NO_IMPORT']='1'
from snippop import *
app=App();app.register(None);app.activate();w=app.window
other=Gtk.Window(title='SnipPop activation test target');other.set_default_size(200,100)
loop=GLib.MainLoop();errors=[]
def obscure():
    w.move(10,10);w.hide();other.show_all();other.present()
    GLib.timeout_add(500,lambda:(app.activate(),False)[1])
    GLib.timeout_add(1500,verify)
    return False

def verify():
    try:
        assert w.get_visible() and w.is_active(), 'Window did not come to foreground'
        display=w.get_display();_,x,y=display.get_default_seat().get_pointer().get_position()
        area=display.get_monitor_at_point(x,y).get_workarea();frame=w.get_window().get_frame_extents()
        dx=abs(frame.x+frame.width/2-(area.x+area.width/2))
        dy=abs(frame.y+frame.height/2-(area.y+area.height/2))
        assert dx<=3 and dy<=3,(dx,dy)
        print('PASS: repeated activation raises and centers the existing window')
    except Exception as e:errors.append(str(e))
    loop.quit();return False
GLib.timeout_add(600,obscure);loop.run();other.destroy();w.destroy()
if errors:raise RuntimeError(errors)
