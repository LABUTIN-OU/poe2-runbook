# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка окна «О программе»: чья программа, тексты лицензий из папки программы, сторонние компоненты, адреса сервера.

Запуск: python -m unittest planner.test_about
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import about  # noqa: E402
import server  # noqa: E402
import test_server  # noqa: E402

LIST = {'format': 'poe2-runbook-third-party', 'v': 1, 'program': '0.5.5.18', 'components': [
    {'name': 'Python', 'version': '3.12.10', 'licence': 'PSF-2.0',
     'parts': [{'name': 'OpenSSL', 'version': '3.0.16', 'licence': 'Apache-2.0'}]},
    {'name': 'pywebview', 'version': '6.2.1', 'licence': 'BSD-3-Clause', 'parts': []}]}


class AboutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_identity_is_the_author_and_the_official_site(self):
        """Имя автора, официальный адрес и строка об авторе — те, что в NOTICE.md; имя автора не переводится."""
        self.assertEqual(about.AUTHOR, 'Sergei Labutin')
        self.assertEqual(about.SITE, 'https://poe2.labutin.gg')
        notice = (Path(about.__file__).resolve().parent.parent / 'NOTICE.md').read_text(encoding='utf-8')
        self.assertIn(about.ATTRIBUTION, notice)
        self.assertIn('Copyright © %d %s' % (about.YEAR, about.AUTHOR), notice)
        self.assertIn(about.SITE, notice)

    def test_legal_texts_only_by_their_names(self):
        """Отдаются только LICENSE, NOTICE.md и THIRD-PARTY.md из папки программы; другое имя или путь — ничего."""
        (self.root / 'LICENSE').write_text('GNU GENERAL PUBLIC LICENSE', encoding='utf-8')
        (self.root / 'NOTICE.md').write_text('# PoE2 Runbook «О программе»', encoding='utf-8')
        (self.root / 'secret.txt').write_text('no', encoding='utf-8')
        self.assertEqual(about.legal_text('LICENSE', self.root), 'GNU GENERAL PUBLIC LICENSE')
        self.assertEqual(about.legal_text('NOTICE.md', self.root), '# PoE2 Runbook «О программе»')
        self.assertIsNone(about.legal_text('THIRD-PARTY.md', self.root))          # файла нет
        for bad in ('secret.txt', '../LICENSE', 'license', '', None, 'LICENSE/'):
            self.assertIsNone(about.legal_text(bad, self.root))

    def test_program_folder_holds_licence_and_terms(self):
        """У программы из исходников папка программы — папка проекта: LICENSE и NOTICE.md в ней есть."""
        files = about.view('0.5.5.18', '0.5.5')['files']
        self.assertIn('LICENSE', files)
        self.assertIn('NOTICE.md', files)

    def test_components_list_from_the_build(self):
        """Список сторонних компонентов — как его записал packaging/notices.py; испорченный или чужой — не показывается."""
        self.assertIsNone(about.components(self.root))                               # программа из исходников: списка нет
        f = self.root / about.COMPONENTS
        f.write_text(json.dumps(LIST), encoding='utf-8')
        got = about.components(self.root)
        self.assertEqual([c['name'] for c in got], ['Python', 'pywebview'])
        self.assertEqual(got[0]['parts'], [{'name': 'OpenSSL', 'version': '3.0.16', 'licence': 'Apache-2.0'}])
        for bad in (dict(LIST, format='other'), dict(LIST, components='x'), dict(LIST, components=[{'name': 'x'}]),
                    dict(LIST, components=[dict(LIST['components'][0], parts=[{'name': 1}])]), dict(LIST, components=[])):
            f.write_text(json.dumps(bad), encoding='utf-8')
            self.assertIsNone(about.components(self.root))
        f.write_text('{', encoding='utf-8')
        self.assertIsNone(about.components(self.root))

    def test_view(self):
        (self.root / 'LICENSE').write_text('x', encoding='utf-8')
        (self.root / 'THIRD-PARTY.md').write_text('x', encoding='utf-8')
        (self.root / about.COMPONENTS).write_text(json.dumps(LIST), encoding='utf-8')
        v = about.view('0.5.5.18', '0.5.5', root=self.root, here=self.root)
        self.assertEqual((v['name'], v['version'], v['game'], v['author'], v['year'], v['site']),
                         ('PoE2 Runbook', '0.5.5.18', '0.5.5', 'Sergei Labutin', 2026, 'https://poe2.labutin.gg'))
        self.assertEqual(v['files'], ['LICENSE', 'THIRD-PARTY.md'])
        self.assertEqual(len(v['components']), 2)


class AboutServerTest(unittest.TestCase):
    """Адреса сервера: /api/about, /api/legal, открыть официальный сайт, первая строка окна «Настройки»."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.log, self.plan, self.runs = root / 'Client.txt', root / 'plan.json', root / 'runs'
        self.log.write_text(test_server.LOG, encoding='utf-8')
        self.plan.write_text(json.dumps(test_server.PLAN, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def start(self):
        app = server.App(self.log, self.plan, self.runs)
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        return app

    def test_site_is_opened_in_the_system_browser_on_request(self):
        app = self.start()
        opened = []
        app.opener = lambda url: opened.append(url) or True
        self.assertTrue(app.open_site())
        self.assertEqual(opened, ['https://poe2.labutin.gg'])

        def broken(url):
            raise OSError('браузер не запустился')
        app.opener = broken
        self.assertFalse(app.open_site())

    def test_settings_name_the_author(self):
        app = self.start()
        self.assertEqual(app.settings_view()['about'], {'name': 'PoE2 Runbook', 'author': 'Sergei Labutin', 'year': 2026})

    def test_http(self):
        app = self.start()
        opened = []
        app.opener = lambda url: opened.append(url) or True
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
        port = httpd.server_port
        httpd.RequestHandlerClass = server.make_handler(app, port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

        def call(method, path, body=None):
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            c.request(method, path, body=json.dumps(body) if body is not None else None,
                      headers={'Host': '127.0.0.1:%d' % port, 'Content-Type': 'application/json'})
            r = c.getresponse()
            out = (r.status, r.getheader('Content-Type'), r.read().decode('utf-8'))
            c.close()
            return out

        code, kind, body = call('GET', '/api/about')
        self.assertEqual(code, 200)
        v = json.loads(body)
        self.assertEqual((v['name'], v['author'], v['site']), ('PoE2 Runbook', 'Sergei Labutin', 'https://poe2.labutin.gg'))
        self.assertIn('LICENSE', v['files'])
        code, kind, body = call('GET', '/api/legal?file=LICENSE')
        self.assertEqual((code, kind), (200, 'text/plain; charset=utf-8'))
        self.assertIn('GNU GENERAL PUBLIC LICENSE', body)
        code, kind, body = call('GET', '/api/legal?file=NOTICE.md')
        self.assertIn('Sergei Labutin', body)
        for bad in ('/api/legal?file=..%2FLICENSE', '/api/legal?file=server.py', '/api/legal'):
            self.assertEqual(call('GET', bad)[0], 404)
        self.assertEqual(call('POST', '/api/open', {'page': 'site'})[0], 200)
        self.assertEqual(opened, ['https://poe2.labutin.gg'])
        self.assertEqual(call('POST', '/api/open', {'page': 'site', 'url': 'https://evil.example'})[0], 200)
        self.assertEqual(opened, ['https://poe2.labutin.gg'] * 2)                   # адрес от страницы не берётся
        self.assertEqual(call('POST', '/api/open', {'page': 'other'})[0], 400)


if __name__ == '__main__':
    unittest.main()
