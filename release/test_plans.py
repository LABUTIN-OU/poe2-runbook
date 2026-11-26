# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка инструмента одобрения планов release/plans.py — только во временных папках: боевой ключ, site/ и программа
проекта не трогаются (данные игры и справочник проекта только читаются). Нужен openssl (из PATH или Git для Windows) и
Windows (проверка подписи — bcrypt.dll).

Запуск (из папки проекта): python -X utf8 -m unittest release.test_plans
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plans  # noqa: E402
import publish  # noqa: E402

plancat, planlib, signed = plans.plancat, plans.planlib, plans.signed
try:
    publish.openssl()
    HAVE = sys.platform == 'win32'
except publish.Stop:
    HAVE = False

ROUTE = {'version': 2, 'id': 'campaign',
         'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки', 'notes': []},
                   {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл', 'notes': []}],
         'goals': [{'id': 'hero-3', 'group': 'Уровень', 'title': '3 уровень героя', 'reach': 3, 'need': 'clearfell'}]}


def part(data):
    dump = lambda x: json.dumps(x, ensure_ascii=False)     # noqa: E731
    rows = []
    for k, v in data.items():
        if isinstance(v, list) and v:
            rows.append('  %s: [\n%s\n  ]' % (dump(k), ',\n'.join('    ' + dump(x) for x in v)))
        else:
            rows.append('  %s: %s' % (dump(k), dump(v)))
    return '{\n' + ',\n'.join(rows) + '\n}\n'


def plan_data(uid='witch01', title='Ведьма', note=None, step_name='Клирфелл'):
    build = {'version': 2, 'title': title, 'routeId': 'campaign', 'hero': {'class': 'Witch', 'ascendancy': 'Infernalist'},
             'slots': [], 'goals': [{'id': 'bomb', 'kind': 'skill', 'group': 'Навыки', 'title': 'Бомба', 'need': 'clearfell'}]}
    if note is not None:
        build['goals'][0]['note'] = note
    route = json.loads(json.dumps(ROUTE))
    route['steps'][1]['name'] = step_name
    return {'format': planlib.FORMAT, 'version': 1, 'uid': uid, 'title': title, 'groups': [],
            'route': part(route), 'build': part(build)}


@unittest.skipUnless(HAVE, 'нужны Windows и openssl')
class PlansToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.key, self.planner, self.site = root / 'k' / 'key.pem', root / 'planner', root / 'site' / 'plans'
        self.planner.mkdir()
        (self.planner / 'updatekey.py').write_text('PUBLIC_KEY = None\n', encoding='utf-8')
        publish.keygen(self.key, self.planner)
        self.files = root / 'in'
        self.files.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, name='witch.plan.json', **kw):
        path = self.files / name
        path.write_text(json.dumps(plan_data(**kw), ensure_ascii=False, indent=1), encoding='utf-8')
        return path

    def add(self, path, author='Автор плана', **kw):
        out = []
        args = dict(key=self.key, site=self.site, planner=self.planner, day='2026-11-26', out=out.append)
        args.update(kw)
        entry = plans.add(path, author, **args)
        return entry, '\n'.join(out)

    def program_reads(self):
        """Каталог в site — как его прочтёт программа (её код, её ключ)."""
        data, sig = (self.site / 'index.json').read_bytes(), (self.site / 'index.json.sig').read_bytes()
        return plancat.read_index(data, sig, signed.public_point(publish.program_key(self.planner)))

    def test_add_new_versions_remove_verify(self):
        e, out = self.add(self.file(), author_url='https://example.org/me',
                          summary={'ru': 'Ведьма на хаосе', 'en': 'Chaos witch'}, tags=['hc'])
        self.assertIn('План: «Ведьма» (метка witch01), версия 1 — новый в каталоге', out)
        self.assertIn('Шагов: 2 · целей: 2 (маршрута 1, билда 1)', out)
        self.assertIn('Ведьма (Witch) · Инферналист (Infernalist)', out)
        got = self.program_reads()['plans']
        self.assertEqual([(x['uid'], x['version'], x['author'], x['cls'], x['asc'], x['game']) for x in got],
                         [('witch01', 1, {'name': 'Автор плана', 'url': 'https://example.org/me'}, 'Witch', 'Infernalist', '0.5.5')])
        self.assertEqual((got[0]['changed'], got[0]['langs'], got[0]['tags'], got[0]['published']),
                         ({'ru': 'Первая версия.', 'en': 'The first version.'}, ['ru'], ['hc'], '2026-11-26'))
        body = (self.site / 'witch01' / '1.plan').read_bytes()
        self.assertEqual(got[0]['url'], 'https://poe2.labutin.gg/plans/witch01/1.plan')
        self.assertEqual(planlib.parse_bundle(plancat.read_plan(body, got[0]))[2]['uid'], 'witch01')
        # файл плана — в том виде, в каком его пишет программа: план, поставленный из него, даёт те же байты
        self.assertEqual(body, planlib.bundle_bytes(plans.read_plan_file(self.file())[0]))
        # новая версия того же плана: «что изменилось» обязательно; описание и метки остаются от прежней
        with self.assertRaises(publish.Stop):
            self.add(self.file(step_name='Клирфелл, лагерь'))
        e2, out = self.add(self.file(step_name='Клирфелл, лагерь'), changed={'ru': 'Лагерь', 'en': 'Camp'})
        self.assertEqual((e2['version'], e2['summary'], e2['tags']), (2, {'ru': 'Ведьма на хаосе', 'en': 'Chaos witch'}, ['hc']))
        self.assertIn('версия 2 — новая версия', out)
        self.assertTrue((self.site / 'witch01' / '1.plan').is_file())
        self.assertEqual([x['version'] for x in self.program_reads()['plans']], [2])
        # у этой метки в каталоге другой автор — это другой план
        with self.assertRaises(publish.Stop) as cm:
            self.add(self.file(), author='Самозванец', changed={'ru': 'x', 'en': 'x'})
        self.assertIn('автор «Автор плана»', str(cm.exception))
        # второй план; список; проверка тем же кодом, что программа
        self.add(self.file('dov.plan.json', uid='dov0001', title='DoV'))
        buf = io.StringIO()
        with redirect_stdout(buf):
            plans.show(self.site, self.planner)
            bad = plans.verify(self.site, self.planner)
        self.assertEqual(bad, 0)
        self.assertIn('witch01 · «Ведьма» · версия 2', buf.getvalue())
        # файл версии изменён после одобрения — проверка это видит
        (self.site / 'dov0001' / '1.plan').write_bytes(b'{}')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(plans.verify(self.site, self.planner), 1)
        # убрать: записи нет, файлы остаются, следующая версия той же метки продолжает счёт
        with redirect_stdout(io.StringIO()):
            plans.remove('witch01', self.key, self.site, self.planner)
        self.assertEqual([x['uid'] for x in self.program_reads()['plans']], ['dov0001'])
        self.assertTrue((self.site / 'witch01' / '2.plan').is_file())
        e3, _ = self.add(self.file(step_name='Снова'), changed={'ru': 'Снова', 'en': 'Again'})
        self.assertEqual(e3['version'], 3)

    def test_markup_and_foreign_links_are_refused(self):
        for kw in ({'note': '<b>жирно</b>'}, {'note': 'смотри javascript:alert(1)'}, {'title': '<img src=x onerror=alert(1)>'},
                   {'step_name': 'ftp://example.org/x'}, {'note': 'data:text/html,<p>'}, {'note': '&lt;b&gt;'}):
            with self.assertRaises(publish.Stop, msg=kw) as cm:
                self.add(self.file(**kw))
            self.assertIn('разметка или ссылка не http(s)', str(cm.exception))
        # ссылки http(s) и обычные двоеточия в тексте — можно
        self.add(self.file(note='Подробнее: https://example.org/guide · Note: x'))
        self.assertFalse((self.site / 'witch01' / '2.plan').exists())
        for kw in ({'author_url': 'javascript:alert(1)'}, {'author_url': 'ftp://x.org'}):
            with self.assertRaises(publish.Stop):
                self.add(self.file(), changed={'ru': 'x', 'en': 'x'}, **kw)
        with self.assertRaises(publish.Stop):
            plans.pair('<b>x</b>', 'y', '--summary', 300)
        with self.assertRaises(publish.Stop):
            plans.pair('x', None, '--summary', 300)
        with self.assertRaises(publish.Stop):
            plans.one_line('две\nстроки', '--author', 80)

    def test_plan_the_program_would_refuse(self):
        path = self.files / 'bad.plan.json'
        for body in ('not json', json.dumps({'format': 'x'}), json.dumps(dict(plan_data(), uid='')),
                     json.dumps(dict(plan_data(), build=part({'version': 2, 'title': '', 'routeId': 'campaign', 'goals': []})))):
            path.write_text(body, encoding='utf-8')
            with self.assertRaises(publish.Stop):
                self.add(path)
        self.assertFalse((self.site / 'index.json').exists())

    def test_key_must_be_the_programs(self):
        other = Path(self.tmp.name) / 'other.pem'
        publish.run_openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', other)
        with self.assertRaises(publish.Stop) as cm:
            self.add(self.file(), key=other)
        self.assertIn('не тот, что вписан в программу', str(cm.exception))
        self.assertFalse((self.site / 'index.json').exists())
        self.assertFalse((self.site / 'witch01' / '1.plan').exists())       # файл версии без каталога не остаётся

    def test_command_line(self):
        path = self.file()
        common = ['--key', str(self.key), '--planner', str(self.planner), '--site', str(self.site)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = plans.main(common + ['add', str(path), '--author', 'Автор', '--summary-ru', 'О', '--summary-en', 'About',
                                        '--tags', 'hc,ssf', '--date', '2026-11-26'])
        self.assertEqual(code, 0, buf.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(plans.main(common + ['verify']), 0)
            self.assertEqual(plans.main(common + ['list']), 0)
            self.assertEqual(plans.main(common + ['add', str(path), '--author', 'Автор', '--summary-ru', 'только один']), 1)
            self.assertEqual(plans.main(common + ['remove', 'nope']), 1)


if __name__ == '__main__':
    unittest.main()
