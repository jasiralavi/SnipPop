"""Paste into an isolated Chrome page; collect the browser's actual clipboard formats."""
import os, sys, tempfile, subprocess, threading, json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = tempfile.TemporaryDirectory(prefix='snippop-browser-')
os.environ['SNIPPOP_DATA_DIR'] = tmp.name + '/data'
os.environ['SNIPPOP_NO_IMPORT'] = '1'
from snippop import *
received = []; requests = []
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        requests.append(self.path)
        body = b'''<!doctype html><title>SnipPop compatibility test</title><h2>SnipPop isolated paste test</h2><div contenteditable autofocus style="border:1px solid;padding:30px" id="e">Paste target</div><script>const target=document.getElementById('e');target.focus();fetch('/ready');document.addEventListener('keydown',k=>fetch('/key?code='+k.code+'&ctrl='+k.ctrlKey+'&target='+document.activeElement.id));let previous=target.innerHTML;setInterval(()=>{target.focus();if(target.innerHTML!==previous){previous=target.innerHTML;fetch('/result',{method:'POST',body:JSON.stringify({source:'dom',types:[],plain:target.innerText,html:target.innerHTML})})}},500);document.addEventListener('paste',event=>{let c=event.clipboardData;fetch('/result',{method:'POST',body:JSON.stringify({types:[...c.types],plain:c.getData('text/plain'),html:c.getData('text/html')})})});</script>'''
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200); self.end_headers()
server = HTTPServer(('127.0.0.1',0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
app=App(); app.register(None); app.activate(); snip=app.window; snip.hide()
snip.store.save('browser.test','<p><b>SnipPop bold</b></p><table><tr><td>Cell A</td><td>Cell B</td></tr></table>')
snip.refresh()
browser = os.environ.get('SNIPPOP_TEST_BROWSER', 'chrome')
url = 'http://127.0.0.1:' + str(server.server_port)
command = ['/usr/bin/firefox', '--no-remote', '--profile', tmp.name+'/firefox', url] if browser == 'firefox' else ['/usr/bin/google-chrome','--user-data-dir='+tmp.name+'/chrome','--no-first-run','--no-default-browser-check','--app='+url]
Path(tmp.name+'/firefox').mkdir(exist_ok=True)
Path(tmp.name+'/firefox/user.js').write_text('user_pref("network.proxy.type", 0);\nuser_pref("browser.aboutwelcome.enabled", false);\nuser_pref("browser.shell.checkDefaultBrowser", false);\nuser_pref("browser.startup.homepage_override.mstone", "ignore");\nuser_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);\n')
log=open(tmp.name+'/browser.log','w+')
proc=subprocess.Popen(command,stdout=log,stderr=log)
loop=GLib.MainLoop(); errors=[]
plain_test = bool(os.environ.get('SNIPPOP_TEST_PLAIN'))
if plain_test:
    snip.clip.set = lambda plain,*args,**kwargs: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(plain,-1)
def start():
    if browser == 'firefox':
        found=subprocess.run(['xdotool','search','--onlyvisible','--pid',str(proc.pid),'--name','SnipPop compatibility test'],capture_output=True,text=True)
        print('Firefox test windows:',found.stdout.strip())
        if found.stdout.strip():
            subprocess.run(['xdotool','windowactivate','--sync',found.stdout.splitlines()[0]],timeout=3)
    GLib.timeout_add(700, show_snip); return False
def show_snip():
    before=subprocess.run(['xdotool','getwindowfocus','getwindowname'],capture_output=True,text=True).stdout.strip()
    print('Before popup focused test:', 'SnipPop compatibility test' in before)
    import snippop as module
    original=module.send_paste
    def traced():
        current=subprocess.run(['xdotool','getwindowfocus','getwindowname'],capture_output=True,text=True).stdout.strip()
        print('Before paste focused test:', 'SnipPop compatibility test' in current)
        original()
    module.send_paste=traced
    snip.present(); GLib.timeout_add(700, lambda: (snip.paste(),False)[1]); GLib.timeout_add(2500, verify); return False
def verify():
    try:
        assert received, 'Browser did not receive a paste event'
        if not plain_test:
            assert received[-1].get('source') == 'dom' or 'text/html' in received[-1]['types'], received[-1]['types']
            assert '<b>SnipPop bold</b>' in received[-1]['html']
            assert '<table>' in received[-1]['html']
        assert 'Cell A' in received[-1]['plain']
        print('PASS: ' + browser + ' receives rich HTML, table and plain fallback')
    except Exception as e:
        errors.append(str(e))
        log.flush(); log.seek(0); print('Browser exit:',proc.poll(),'Requests:',requests); print(log.read()[-2000:])
    loop.quit(); return False
GLib.timeout_add(8000,start)
loop.run(); snip.destroy(); proc.terminate(); server.shutdown()
if errors: raise RuntimeError(errors)
