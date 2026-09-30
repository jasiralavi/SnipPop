import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Store, normalize, plain_html, web_url


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'data')

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_html_plain_and_active_content(self):
        rich, plain, kind, _ = normalize('<p>Hello <b>Sam</b></p><script>password</script><table><tr><td>A</td><td>B</td></tr></table><img src="https://track.invalid/a"><a href="javascript:alert(1)">link</a>')
        self.assertNotIn('script', rich)
        self.assertNotIn('password', plain)
        self.assertNotIn('javascript', rich)
        self.assertNotIn('track.invalid', rich)
        self.assertIn('A\tB', plain)
        self.assertEqual(kind, 'mixed')

    def test_image_and_link(self):
        self.assertEqual(normalize('<img src="data:image/png;base64,YQ==">')[2], 'image')
        self.assertEqual(normalize('https://example.org')[2], 'link')
        self.assertEqual(normalize('<a href="https://example.org">Example</a>')[2], 'link')
        self.assertEqual(normalize('<p>Before <a href="https://example.org">Example</a></p>')[2], 'text')

    def test_search_sort_filter(self):
        a = self.store.save('zeta', '<b>target</b>')
        b = self.store.save('target', '<i>second</i>')
        self.store.change(a, 'uses', 10)
        self.assertEqual(self.store.search('target', sort='frequent')[0]['id'], b)
        self.assertEqual(self.store.search(sort='oldest')[0]['id'], a)
        self.assertEqual(self.store.search(sort='frequent')[0]['id'], a)
        self.store.change(b, 'pinned', 1)
        self.assertEqual([r['id'] for r in self.store.search(filter_by='pinned')], [b])
        self.store.change(b, 'deleted', 1)
        self.assertEqual(len(self.store.search()), 1)
        self.store.change(b, 'deleted', 0)
        self.assertEqual(len(self.store.search()), 2)

    def test_tag_filters(self):
        invoice = self.store.save('Invoice', 'Monthly payment', tags=' NK , work')
        note = self.store.save('Note', 'Invoice details', tags='#nk, personal')
        self.store.save('Other', 'nk invoice', tags='nks')
        self.store.save('Untagged', 'nk invoice')
        self.assertEqual({r['id'] for r in self.store.search('#nk')}, {invoice, note})
        self.assertEqual({r['id'] for r in self.store.search('#NK')}, {invoice, note})
        self.assertEqual([r['id'] for r in self.store.search('#nk #work')], [invoice])
        self.assertEqual([r['id'] for r in self.store.search('#nk monthly')], [invoice])
        self.assertEqual([r['id'] for r in self.store.search('monthly #nk')], [invoice])
        self.assertEqual(self.store.search('#missing'), [])
        self.assertEqual(self.store.search('#n'), [])
        self.store.change(note, 'pinned', True)
        self.assertEqual([r['id'] for r in self.store.search('#nk', filter_by='pinned')], [note])
        self.assertEqual(self.store.search('#nk invoice')[0]['id'], invoice)
        self.store.change(invoice, 'deleted', True)
        self.assertEqual([r['id'] for r in self.store.search('#nk')], [note])

    def test_hash_in_ordinary_text_is_not_tag(self):
        entry = self.store.save('C# reference', 'https://example.org/#anchor')
        self.assertEqual(self.store.search('C#')[0]['id'], entry)
        self.assertEqual(self.store.search('https://example.org/#anchor')[0]['id'], entry)

    def test_unique_and_generated_plain(self):
        entry = self.store.save('Work', '<p>One</p>')
        self.store.save('Work', '<p>Two</p>', entry_id=entry)
        self.assertEqual(self.store.get(entry)['plain'], 'Two')
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save('work', '<p>Duplicate</p>')

    def test_logins_not_in_export_or_expansion(self):
        self.store.save('gmail', username='me@example.org', kind='login', secret_ref='opaque', link='mail.google.com')
        self.store.save('hello', 'Hello')
        out = Path(self.tmp.name) / 'export.json'
        self.store.export(out)
        self.assertNotIn('me@example.org', out.read_text())
        self.assertNotIn('opaque', out.read_text())
        self.assertEqual(self.store.expand('@gmail@'), '@gmail@')
        self.assertEqual(self.store.import_file(out), 1)

    def test_legacy_import_preserved_and_idempotent(self):
        legacy = Path(self.tmp.name) / 'old.db'
        conn = sqlite3.connect(legacy)
        conn.execute('CREATE TABLE snippets (id INTEGER PRIMARY KEY, abbreviation TEXT, content TEXT)')
        conn.execute('INSERT INTO snippets VALUES (1,?,?)', ('old','<literal>\nline'))
        conn.commit()
        conn.close()
        before = legacy.read_bytes()
        self.store.import_legacy(legacy)
        self.store.import_legacy(legacy)
        self.assertEqual(legacy.read_bytes(), before)
        self.assertEqual(len(self.store.search()), 1)
        self.assertEqual(self.store.search()[0]['plain'], '<literal>\nline')

    def test_placeholders_cycle_and_dates(self):
        self.store.save('one', '@two@')
        self.store.save('two', '@one@')
        self.assertLess(len(self.store.expand('@one@')), 100)
        self.assertRegex(self.store.expand('@dt:YYYY-MM-DD@'), r'^\d{4}-\d{2}-\d{2}$')
        self.assertIn('September', self.store.expand('@dt:MMMM@') if __import__('datetime').datetime.now().month == 9 else 'September')

    def test_url_validation(self):
        self.assertEqual(web_url('mail.google.com'), 'https://mail.google.com')
        for value in ['javascript://alert(1)', 'file:///etc/passwd', 'https://user:pw@example.org', 'https://bad host']:
            with self.assertRaises(ValueError):
                web_url(value)

if __name__ == '__main__':
    unittest.main()
