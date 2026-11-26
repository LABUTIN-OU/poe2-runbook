# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка инструмента выпуска release/publish.py — только во временных папках: боевой ключ, site/ и программа
проекта не трогаются. Нужен openssl (из PATH или Git для Windows) и Windows (проверка подписи — bcrypt.dll).

Запуск (из папки проекта): python -X utf8 -m unittest release.test_publish
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import publish  # noqa: E402

update = publish.update
try:
    publish.openssl()
    HAVE = sys.platform == 'win32'
except publish.Stop:
    HAVE = False


@unittest.skipUnless(HAVE, 'нужны Windows и openssl')
class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.key, self.planner, self.site, self.dist = root / 'k' / 'key.pem', root / 'planner', root / 'site', root / 'dist'
        for d in (self.planner, self.site, self.dist):
            d.mkdir()
        (self.planner / 'updatekey.py').write_text('PUBLIC_KEY = None\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def setup_file(self, version, body=b'installer bytes'):
        path = self.dist / ('PoE2Runbook-Setup-%s.exe' % version)
        path.write_bytes(body)
        return path

    def make(self, version='0.5.5.19', **kw):
        args = dict(url='https://example.org/rel/PoE2Runbook-Setup-%s.exe' % version, notes_ru='Новое', notes_en='New',
                    key=self.key, site=self.site, planner=self.planner, day='2026-11-26')
        args.update(kw)
        return publish.manifest(self.setup_file(version), **args)

    def test_keygen_makes_key_once_and_writes_public_key(self):
        der, made = publish.keygen(self.key, self.planner)
        self.assertTrue(made)
        pem = self.key.read_bytes()
        self.assertIn(b'PRIVATE KEY', pem)
        self.assertEqual(publish.program_key(self.planner), der)
        text = (self.planner / 'updatekey.py').read_text(encoding='utf-8')
        self.assertIn('SPDX-License-Identifier: GPL-3.0-only', text)
        self.assertIn("FINGERPRINT = '%s'" % publish.fingerprint(der), text)
        self.assertNotIn('PRIVATE', text)
        # модуль ключа — настоящий модуль Python, его прочтёт программа
        space = {}
        exec(compile(text, 'updatekey.py', 'exec'), space)
        self.assertEqual(update.public_point(space['PUBLIC_KEY']), update.public_point(der))
        # второй раз — ключ не перезаписан, открытый ключ тот же
        der2, made2 = publish.keygen(self.key, self.planner)
        self.assertEqual((der2, made2, self.key.read_bytes()), (der, False, pem))

    def test_keygen_refuses_to_replace_another_key(self):
        publish.keygen(self.key, self.planner)
        other = Path(self.tmp.name) / 'k2' / 'key.pem'
        with self.assertRaises(publish.Stop):
            publish.keygen(other, self.planner)
        der, _ = publish.keygen(other, self.planner, replace=True)
        self.assertEqual(publish.program_key(self.planner), der)

    def test_manifest_is_signed_and_read_by_the_program(self):
        publish.keygen(self.key, self.planner)
        data, info = self.make(notice_ru='Объявление', notice_en='Notice')
        self.assertEqual((self.site / 'latest.json').read_bytes(), data)
        doc = json.loads(data.decode('utf-8'))
        self.assertEqual(doc['format'], 'poe2-runbook-update')
        self.assertEqual((doc['v'], doc['version'], doc['game'], doc['published']), (1, '0.5.5.19', '0.5.5', '2026-11-26'))
        self.assertEqual(doc['installer']['size'], len(b'installer bytes'))
        self.assertEqual(doc['notice'], {'ru': 'Объявление', 'en': 'Notice'})
        sig = (self.site / 'latest.json.sig').read_bytes()
        point = update.public_point(publish.program_key(self.planner))
        self.assertEqual(update.read_manifest(data, sig, point)['version'], '0.5.5.19')
        info2, same = publish.verify_site(self.site, self.planner, self.dist)
        self.assertEqual((info2['sha256'], same), (info['sha256'], True))
        self.assertNotIn('notice', json.loads(self.make('0.5.5.20')[0].decode('utf-8')))     # без объявления — поля нет

    def test_default_url_is_the_github_release(self):
        """Без --url адрес установщика — выпуск GitHub с меткой v<версия>."""
        publish.keygen(self.key, self.planner)
        data, info = publish.manifest(self.setup_file('0.5.5.19'), None, 'Новое', 'New', key=self.key, site=self.site,
                                      planner=self.planner)
        self.assertEqual(info['url'], 'https://github.com/LABUTIN-OU/poe2-runbook/releases/download/v0.5.5.19/'
                                      'PoE2Runbook-Setup-0.5.5.19.exe')
        self.assertEqual(json.loads(data.decode('utf-8'))['installer']['url'], info['url'])

    def test_version_must_be_newer(self):
        publish.keygen(self.key, self.planner)
        self.make('0.5.5.19')
        for old in ('0.5.5.19', '0.5.5.18', '0.5.4.99'):
            with self.subTest(old):
                with self.assertRaises(publish.Stop):
                    self.make(old)
        self.make('0.5.6.1')
        self.assertEqual(publish.site_version(self.site), '0.5.6.1')

    def test_refusals(self):
        publish.keygen(self.key, self.planner)
        bad = {'http': dict(url='http://example.org/PoE2Runbook-Setup-0.5.5.19.exe'),
               'other name': dict(url='https://example.org/PoE2Runbook-Setup-0.5.5.18.exe'),
               'notice one language': dict(notice_ru='Только по-русски'),
               'notice long': dict(notice_ru='а' * 141, notice_en='b'),
               'notice two lines': dict(notice_ru='раз\nдва', notice_en='one'),
               'notes empty': dict(notes_en='  ')}
        for name, kw in bad.items():
            with self.subTest(name):
                with self.assertRaises(publish.Stop):
                    self.make(**kw)
        self.assertFalse((self.site / 'latest.json').exists())
        with self.assertRaises(publish.Stop):        # не установщик
            publish.manifest(self.dist / 'other.exe', 'https://example.org/other.exe', 'a', 'b', key=self.key,
                             site=self.site, planner=self.planner)

    def test_key_must_be_the_programs(self):
        """Ключ подписи — не тот, что вписан в программу: файл не пишется (программа его не приняла бы)."""
        publish.keygen(self.key, self.planner)
        other = Path(self.tmp.name) / 'k2' / 'key.pem'
        other.parent.mkdir()
        publish.run_openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', other)
        with self.assertRaises(publish.Stop):
            self.make(key=other)
        self.assertFalse((self.site / 'latest.json').exists())

    def test_verify_finds_a_changed_file_and_installer(self):
        publish.keygen(self.key, self.planner)
        self.make()
        path = self.site / 'latest.json'
        path.write_bytes(path.read_bytes().replace(b'"New"', b'"Nev"'))
        with self.assertRaises(publish.Stop):
            publish.verify_site(self.site, self.planner, self.dist)
        self.make('0.5.5.20')
        self.setup_file('0.5.5.20', b'other bytes!!!!')
        self.assertIs(publish.verify_site(self.site, self.planner, self.dist)[1], False)

    def test_command_line(self):
        out = io.StringIO()
        base = ['--key', str(self.key), '--planner', str(self.planner), '--site', str(self.site), '--dist', str(self.dist)]
        with redirect_stdout(out):
            self.assertEqual(publish.main(base + ['keygen']), 0)
            self.assertEqual(publish.main(base + ['manifest', str(self.setup_file('0.5.5.19')), '--url',
                                                  'https://example.org/PoE2Runbook-Setup-0.5.5.19.exe',
                                                  '--notes-ru', 'Новое', '--notes-en', 'New', '--date', '2026-11-26']), 0)
            self.assertEqual(publish.main(base + ['verify']), 0)
            self.assertEqual(publish.main(base + ['manifest', str(self.setup_file('0.5.5.19')), '--url',
                                                  'https://example.org/PoE2Runbook-Setup-0.5.5.19.exe',
                                                  '--notes-ru', 'Новое', '--notes-en', 'New']), 1)
        text = out.getvalue()
        self.assertIn('СОХРАНИТЕ КОПИЮ', text)
        self.assertIn('Подпись сходится', text)
        self.assertIn('не новее', text)

    def test_der_to_rs(self):
        r, s = b'\x00\x81' + b'\x01' * 31, b'\x7f' * 20      # r с нулём впереди (старший бит), s короче 32 байт
        der = bytes([0x30, 4 + len(r) + len(s), 2, len(r)]) + r + bytes([2, len(s)]) + s
        self.assertEqual(publish.der_to_rs(der), b'\x81' + b'\x01' * 31 + b'\0' * 12 + b'\x7f' * 20)
        with self.assertRaises(publish.Stop):
            publish.der_to_rs(b'\x31\x02\x00\x00' + b'\0' * 8)


if __name__ == '__main__':
    unittest.main()
