"""Isolated desktop smoke test: never reads the real snippet database."""
import os
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = tempfile.TemporaryDirectory()
os.environ['SNIPPOP_DATA_DIR'] = tmp.name
os.environ['SNIPPOP_NO_IMPORT'] = '1'
from snippop import *
import cairo
app = App()
app.register(None)
app.activate()
window = app.window
window.store.save('signature.work', '<p><b>Alex Morgan</b><br>Design &amp; Operations</p><table><tr><td>Monday</td><td>Planning</td></tr></table>')
window.store.save('website', '<a href="https://example.org">Company website</a>')
window.refresh()
loop = GLib.MainLoop()
failed = []
def test():
    try:
        window.clip.set('Plain sample', '<b>Rich sample</b>')
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        assert clip.wait_for_text() == 'Plain sample'
        data = clip.wait_for_contents(Gdk.Atom.intern('text/html', False))
        assert b'<b>Rich sample</b>' in bytes(data.get_data())
        print('PASS: multi-format clipboard')
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 4, 4)
        pixbuf.fill(0x4862e880)
        _, png = pixbuf.save_to_bufferv('png', [], [])
        window.clip.set('', image=bytes(png))
        readback = clip.wait_for_image()
        assert readback and readback.get_width() == 4 and readback.get_has_alpha()
        print('PASS: native image clipboard with transparency')
        width, height = window.get_size()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        window.draw(cairo.Context(surface))
        surface.write_to_png('/tmp/snippop-search.png')
        editor = Editor(window, window.store.search()[1])
        def editor_test():
            def result(web, res, *_):
                try:
                    content = web.run_javascript_finish(res).get_js_value().to_string()
                    assert content and 'error' not in content.lower()
                    width, height = editor.get_size()
                    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                    editor.draw(cairo.Context(s))
                    s.write_to_png('/tmp/snippop-editor.png')
                    print('PASS: rich editor loaded and content retrieved')
                except Exception as exc:
                    failed.append(str(exc))
                editor.destroy()
                window.destroy()
                loop.quit()
            editor.js('getContent()', result)
            return False
        GLib.timeout_add(2500, editor_test)
    except Exception as exc:
        failed.append(str(exc))
        loop.quit()
    return False
GLib.timeout_add(1200, test)
GLib.timeout_add_seconds(15, lambda: (failed.append('Timed out'), loop.quit(), False)[-1])
loop.run()
if failed:
    raise RuntimeError(failed)
print('PASS: desktop smoke test')
