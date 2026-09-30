import os, sys, tempfile, subprocess, socket, threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
tmp=tempfile.TemporaryDirectory(prefix='snippop-writer-')
os.environ['SNIPPOP_DATA_DIR']=tmp.name+'/data'
os.environ['SNIPPOP_NO_IMPORT']='1'
from snippop import *
import uno
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
proc=subprocess.Popen(['/usr/bin/libreoffice','-env:UserInstallation='+Path(tmp.name+'/lo').as_uri(),f'--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext','--norestore','--nodefault','--nofirststartwizard'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
app=App();app.register(None);app.activate();snip=app.window;snip.hide()
snip.store.save('writer.test','<p><b>SnipPop Writer</b></p><table><tr><td>Cell A</td><td>Cell B</td></tr></table>');snip.refresh()
loop=GLib.MainLoop();errors=[];doc=None;attempts=0;context=None

def connect():
    global doc,attempts,context
    attempts+=1
    try:
        local=uno.getComponentContext()
        resolver=local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local)
        context=resolver.resolve(f'uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext')
        desktop=context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',context)
        doc=desktop.loadComponentFromURL('private:factory/swriter','_blank',0,())
        GLib.timeout_add(1800,start)
        return False
    except Exception:
        if attempts<20:return True
        errors.append('Could not start isolated Writer');loop.quit();return False

def start():
    text,rich,image=snip.payload(snip.selected())
    snip.clip.set(text,rich,image)
    dispatcher=context.ServiceManager.createInstanceWithContext('com.sun.star.frame.DispatchHelper',context)
    def dispatch():
        try:
            dispatcher.executeDispatch(doc.CurrentController.Frame,'.uno:Paste','',0,())
            GLib.idle_add(verify)
        except Exception as e:
            errors.append(str(e)); GLib.idle_add(loop.quit)
    threading.Thread(target=dispatch,daemon=True).start()
    return False

def verify():
    try:
        assert 'SnipPop Writer' in doc.Text.String, repr(doc.Text.String)
        assert doc.TextTables.Count==1, 'Table was not preserved'
        assert doc.TextTables.getByIndex(0).getCellByName('A1').String=='Cell A'
        print('PASS: LibreOffice Writer rich paste and table cells')
    except Exception as e:errors.append(str(e))
    loop.quit();return False
GLib.timeout_add(500,connect)
GLib.timeout_add_seconds(18,lambda:(errors.append('Writer timed out'),loop.quit(),False)[-1])
loop.run()
if doc:
    try: doc.close(True)
    except Exception: pass
proc.terminate();snip.destroy()
if errors:raise RuntimeError(errors)
