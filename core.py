"""Storage and safe rich-content normalization; no desktop dependencies."""
import base64
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from datetime import datetime
from urllib.parse import urlsplit


def web_url(value):
    value = value.strip()
    if not value:
        return ''
    if '://' not in value:
        value = 'https://' + value
    p = urlsplit(value)
    _ = p.port  # Validate a supplied port before accepting the URL.
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or any(c.isspace() for c in value):
        raise ValueError('Enter a valid HTTP or HTTPS link.')
    return value


class CleanHTML(HTMLParser):
    allowed = set('p div span br b strong i em u s strike ul ol li blockquote pre code h1 h2 h3 h4 a img table thead tbody tfoot tr td th hr font'.split())
    blocked = set('script style iframe object embed svg math form input button textarea template head'.split())
    styles = set('color background-color font-family font-size font-weight font-style text-decoration text-align line-height margin margin-left margin-right margin-top margin-bottom padding padding-left padding-right padding-top padding-bottom border border-collapse border-color border-width border-style width height vertical-align white-space'.split())

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.text, self.images = [], [], []
        self.skip = 0
        self.table = False

    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:
            self.skip += 1
            return
        if self.skip or tag not in self.allowed:
            return
        safe = []
        for k, v in attrs:
            if v is None:
                continue
            if k == 'style':
                parts = []
                for decl in v.split(';'):
                    prop, _, val = decl.partition(':')
                    if prop.strip().lower() in self.styles and not re.search(r'url|expression|@|\\|[<>]', val, re.I):
                        parts.append(prop.strip().lower() + ':' + val.strip())
                if parts:
                    safe.append(('style', ';'.join(parts)))
            elif tag == 'a' and k == 'href':
                if re.match(r'^(https?://|mailto:)', v, re.I):
                    safe.append((k, v))
            elif tag == 'img' and k == 'src':
                # Self-contained raster images only. Never execute or fetch snippet content.
                if re.fullmatch(r'data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]+', v):
                    safe.append((k, v))
                    self.images.append(v)
            elif k in ('colspan', 'rowspan', 'width', 'height') and re.fullmatch(r'[0-9]{1,4}%?', v):
                safe.append((k, v))
            elif k in ('title', 'alt') or (tag == 'font' and k in ('color', 'face', 'size')):
                safe.append((k, v))
        if tag == 'img' and not any(k == 'src' for k, _ in safe):
            return
        if tag == 'table':
            self.table = True
        if tag in ('br', 'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'pre', 'blockquote'):
            self.text.append('\n')
        if tag == 'li':
            self.text.append('• ')
        self.out.append('<' + tag + ''.join(' ' + k + '="' + html.escape(v, quote=True) + '"' for k, v in safe) + '>')

    def handle_endtag(self, tag):
        if tag in self.blocked:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in self.allowed and tag not in ('br', 'img', 'hr'):
            self.out.append('</' + tag + '>')
        if tag in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'pre', 'blockquote'):
            self.text.append('\n')
        elif tag in ('td', 'th'):
            self.text.append('\t')

    def handle_data(self, value):
        if not self.skip:
            self.out.append(html.escape(value))
            self.text.append(value)


def normalize(value):
    if len(value.encode()) > 25 * 1024 * 1024:
        raise ValueError('Snippet is too large (maximum 25 MB).')
    parser = CleanHTML()
    parser.feed(value)
    plain = re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(parser.text)).strip()
    rich = ''.join(parser.out)
    kind = 'mixed' if parser.table or parser.images else 'text'
    if len(parser.images) == 1 and not plain and not parser.table:
        kind = 'image'
    elif not parser.images and not parser.table:
        if re.fullmatch(r'https?://\S+', plain):
            kind = 'link'
        elif len(re.findall('<a ', rich)) == 1 and re.sub('<[^>]+>', '', rich).strip() == plain:
            # A single linked label; reject extra text outside that anchor.
            if re.fullmatch(r'(?:<[^>]+>\s*)*<a [^>]*>[^<]+</a>(?:\s*</[^>]+>)*', rich):
                kind = 'link'
    return rich, plain, kind, parser.images


def plain_html(text):
    return '<div>' + html.escape(text).replace('\n', '<br>') + '</div>'


class Store:
    def __init__(self, folder, legacy=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.folder / 'snippop.db'
        self.db = sqlite3.connect(self.path)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS entries (
          id TEXT PRIMARY KEY, keyword TEXT NOT NULL COLLATE NOCASE UNIQUE,
          plain TEXT NOT NULL, rich TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
          link TEXT NOT NULL DEFAULT '', secret_ref TEXT NOT NULL DEFAULT '',
          pinned INTEGER NOT NULL DEFAULT 0, tags TEXT NOT NULL DEFAULT '',
          created TEXT NOT NULL, updated TEXT NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
          deleted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        if legacy and not self.setting('legacy_imported', False):
            self.import_legacy(legacy)
        self.backup()

    def setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def import_legacy(self, path):
        path = Path(path)
        if not path.exists():
            return
        old = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            rows = old.execute('SELECT abbreviation,content FROM snippets ORDER BY id').fetchall()
            with self.db:
                for keyword, content in rows:
                    if not self.db.execute('SELECT 1 FROM entries WHERE keyword=?', (keyword,)).fetchone():
                        self.save(keyword, plain_html(content))
                self.set_setting('legacy_imported', True)
        finally:
            old.close()

    def save(self, keyword, rich='', *, entry_id=None, username='', kind=None, link='', secret_ref='', tags=''):
        keyword = keyword.strip()
        if not keyword:
            raise ValueError('A keyword is required.')
        if kind == 'login':
            if not username.strip() or not secret_ref:
                raise ValueError('Username and a saved password are required.')
            plain, rich, link = username.strip(), '', web_url(link)
        else:
            rich, plain, kind, images = normalize(rich)
            if not plain and not images:
                raise ValueError('Add text or an image to the snippet.')
        stamp = datetime.now().isoformat(timespec='microseconds')
        entry_id = entry_id or uuid.uuid4().hex
        with self.db:
            self.db.execute('''INSERT INTO entries
            (id,keyword,plain,rich,kind,link,secret_ref,tags,created,updated)
            VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            keyword=excluded.keyword,plain=excluded.plain,rich=excluded.rich,kind=excluded.kind,
            link=excluded.link,secret_ref=excluded.secret_ref,tags=excluded.tags,updated=excluded.updated''',
            (entry_id, keyword, plain, rich, kind, link, secret_ref, tags, stamp, stamp))
        return entry_id

    def get(self, entry_id):
        return self.db.execute('SELECT * FROM entries WHERE id=?', (entry_id,)).fetchone()

    def search(self, query='', filter_by='all', sort='newest'):
        rows = list(self.db.execute('SELECT * FROM entries WHERE deleted=0'))
        q = query.casefold().strip()
        # Standalone #tokens are exact tag filters; C# and URL fragments remain text.
        tag_pattern = r'(?<!\S)#([^\s#]+)'
        required_tags = set(re.findall(tag_pattern, q))
        if required_tags:
            q = ' '.join(re.sub(tag_pattern, '', q).split())
            rows = [r for r in rows if required_tags <= {
                tag.strip().lstrip('#').casefold() for tag in r['tags'].split(',') if tag.strip()
            }]
        rows = [r for r in rows if q in r['keyword'].casefold() or q in r['plain'].casefold()]
        if filter_by == 'pinned':
            rows = [r for r in rows if r['pinned']]
        elif filter_by != 'all':
            rows = [r for r in rows if r['kind'] == filter_by]
        rows.sort(key=lambda r: (r['uses'], r['created']) if sort == 'frequent' else r['created'], reverse=sort != 'oldest')
        if q:
            rows.sort(key=lambda r: 0 if r['keyword'].casefold() == q else 1 if r['keyword'].casefold().startswith(q) else 2 if q in r['keyword'].casefold() else 3)
        return rows

    def change(self, entry_id, field, value):
        if field not in ('pinned', 'deleted', 'uses'):
            raise ValueError('Invalid field')
        with self.db:
            self.db.execute(f'UPDATE entries SET {field}=? WHERE id=?', (value, entry_id))

    def backup(self):
        target = self.folder / ('backup-' + datetime.now().strftime('%Y-%m-%d') + '.db')
        if not target.exists():
            dest = sqlite3.connect(target)
            self.db.backup(dest)
            dest.close()
            os.chmod(target, 0o600)
        for old in sorted(self.folder.glob('backup-*.db'))[:-7]:
            old.unlink()

    def export(self, path):
        rows = [dict(r) for r in self.search() if r['kind'] != 'login']
        for r in rows:
            r.pop('secret_ref', None)
        Path(path).write_text(json.dumps({'format': 'snippop-1', 'entries': rows}, ensure_ascii=False, indent=2))
        os.chmod(path, 0o600)

    def import_file(self, path):
        payload = json.loads(Path(path).read_text())
        if payload.get('format') != 'snippop-1':
            raise ValueError('Not a SnipPop export.')
        count = 0
        for row in payload['entries']:
            if row.get('kind') == 'login':
                continue
            keyword = row['keyword']
            while self.db.execute('SELECT 1 FROM entries WHERE keyword=?', (keyword,)).fetchone():
                keyword += ' copy'
            self.save(keyword, row['rich'], tags=row.get('tags', ''))
            count += 1
        return count

    def expand(self, rich, seen=()):
        now = datetime.now()
        formats = {'YYYY':'%Y','YY':'%y','MMMM':'%B','MMM':'%b','MM':'%m','DDDD':'%A','DDD':'%a','DD':'%d','hh':'%H','h':'%I','mm':'%M','ss':'%S','a':'%p','wwww':'%A','www':'%a'}
        def date(match):
            fmt = re.sub('|'.join(sorted(formats, key=len, reverse=True)), lambda m: formats[m[0]], match[1])
            return now.strftime(fmt)
        rich = re.sub(r'@dt:([^@]+)@', date, rich)
        for key, fmt in [('@dt@','%d-%b-%Y %H:%M'),('@d@','%d-%b-%Y'),('@t@','%H:%M')]:
            rich = rich.replace(key, now.strftime(fmt))
        def nested(match):
            keyword = html.unescape(match[1])
            if keyword in seen or len(seen) >= 10:
                return match[0]
            row = self.db.execute('SELECT * FROM entries WHERE keyword=? AND deleted=0 AND kind!=?', (keyword,'login')).fetchone()
            return self.expand(row['rich'], seen + (keyword,)) if row else match[0]
        return re.sub(r'@([\w.\-]+)@', nested, rich)
