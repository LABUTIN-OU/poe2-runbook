# -*- coding: utf-8 -*-
"""A static server for trying the site locally, close to how GitHub Pages serves it:
a folder's index.html for the folder, 404.html with status 404 for what is missing, nothing cached.

    python -X utf8 -u serve.py <site folder> <port> [overlay folder]

A file found in the overlay folder is served in place of the site's (and where the site has none), a folder's
index.html included: that is how update/latest.json is tried without ever creating it inside site/, and how a trial
build of all languages (build_site.py --trial) is looked at."""
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root, port = Path(sys.argv[1]).resolve(), int(sys.argv[2])
overlay = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
         '.json': 'application/json; charset=utf-8', '.webp': 'image/webp', '.png': 'image/png', '.ico': 'image/x-icon',
         '': 'text/plain; charset=utf-8'}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(root), **kw)

    def translate_path(self, path):
        here = Path(super().translate_path(path))
        if overlay is not None:
            try:
                over = overlay / here.relative_to(root)
            except ValueError:
                return str(here)
            if over.is_file():
                return str(over)
            # a folder's own page: the overlay's stands in for the site's, and for a folder the site does not have
            if path.split('?')[0].split('#')[0].endswith('/') and (over / 'index.html').is_file():
                return str(over / 'index.html')
        return str(here)

    def guess_type(self, path):
        return TYPES.get(Path(path).suffix.lower(), 'application/octet-stream')

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        page = root / '404.html'
        if code == 404 and page.is_file():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header('Content-Type', TYPES['.html'])
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    def list_directory(self, path):          # no folder listings, as on the hosting
        self.send_error(404)
        return None


print('site %s on http://127.0.0.1:%d/%s' % (root, port, ' (overlay %s)' % overlay if overlay else ''), flush=True)
ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
