# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка обновления программы (planner/update.py) и его части в установщике (packaging/update.iss) — без
настоящей сети: запросы подменяются, а WinHTTP проверяется на сервере на этом же компьютере (127.0.0.1).

Что проверяется:
  * подпись: верная принимается; изменённый файл, подпись чужим ключом, испорченная подпись, нет ключа — нет;
  * файл не того формата не принимается; незнакомые поля пропускаются; объявление — одна строка простого текста;
  * принимается только версия новее своей (сначала версия игры, потом номер сборки), равная и старая — нет;
  * адрес установщика только https://; размер или SHA-256 скачанного не сходятся, загрузка оборвалась — ничего
    не запускается, недокачанное убрано; «скачал → сверил → запустил» — на подставном установщике, который только
    пишет файл-отметку со своими параметрами;
  * сеть: в запросе только Host, User-Agent: PoE2Runbook/<версия> и Connection — без cookies; не https — отказ; сервер
    с самодельным сертификатом — отказ (проверка сертификата включена);
  * пробный установщик Inno Setup с packaging/update.iss ждёт, пока программа завершится (мьютекс), и после тихой
    установки с /RESTARTAPPLICATIONS открывает программу; без этого ключа — не открывает.
Подписывает openssl (из PATH или Git для Windows); подставной установщик собирает csc.exe из .NET Framework, пробный —
Inno Setup 6. Чего нет на компьютере — те проверки пропускаются со словами почему.

Запуск: python -X utf8 -m unittest planner.test_update
"""
import base64
import ctypes
import http.server
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import appsettings  # noqa: E402
import i18n  # noqa: E402
import update  # noqa: E402

ROOT = HERE.parent
OWN = '0.5.5.18'


# --- подпись для проверок: openssl ---------------------------------------------------------------------------------

def find_openssl():
    found = shutil.which('openssl')
    if found:
        return found
    roots = []
    git = shutil.which('git')
    if git:
        roots += list(Path(git).resolve().parents)[:3]
    for env in ('ProgramFiles', 'ProgramW6432'):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]) / 'Git')
    for root in roots:
        for rel in ('mingw64/bin/openssl.exe', 'usr/bin/openssl.exe'):
            if (root / rel).is_file():
                return str(root / rel)
    return None


OPENSSL = find_openssl()


def der_to_rs(der):
    i, out = 2, b''
    for _ in range(2):
        n = der[i + 1]
        out += der[i + 2:i + 2 + n].lstrip(b'\0').rjust(32, b'\0')
        i += 2 + n
    return out


class Key:
    """Пробный ключ ECDSA P-256 во временной папке: подписывает, как инструмент выпуска."""

    def __init__(self, folder):
        self.pem = Path(folder) / 'key.pem'
        subprocess.run([OPENSSL, 'genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out',
                        str(self.pem)], check=True, capture_output=True)
        self.der = subprocess.run([OPENSSL, 'pkey', '-in', str(self.pem), '-pubout', '-outform', 'DER'], check=True,
                                  capture_output=True).stdout
        self.point = update.public_point(self.der)

    def sign(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'data'
            src.write_bytes(data)
            der = subprocess.run([OPENSSL, 'dgst', '-sha256', '-sign', str(self.pem), str(src)], check=True,
                                 capture_output=True).stdout
        return base64.b64encode(der_to_rs(der)) + b'\n'


def doc(version='0.5.5.19', **over):
    d = {'format': 'poe2-runbook-update', 'v': 1, 'version': version, 'game': '.'.join(version.split('.')[:3]),
         'published': '2026-11-26',
         'installer': {'url': 'https://example.org/dl/PoE2Runbook-Setup-%s.exe' % version, 'size': 3,
                       'sha256': 'a' * 64},
         'notes': {'ru': 'Что нового', 'en': 'What is new'}}
    d.update(over)
    return d


def raw(d):
    return (json.dumps(d, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


@unittest.skipUnless(sys.platform == 'win32' and OPENSSL, 'нужны Windows (bcrypt.dll) и openssl')
class SignedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        (base / 'a').mkdir()
        (base / 'b').mkdir()
        cls.key, cls.other = Key(base / 'a'), Key(base / 'b')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def read(self, d, key=None):
        data = raw(d) if isinstance(d, dict) else d
        return update.read_manifest(data, (key or self.key).sign(data), self.key.point)


class ManifestTest(SignedTest):
    def test_good_file_is_read(self):
        """Верная подпись — файл принят, поля приведены: SHA-256 строчными, тексты — по языкам."""
        d = doc(installer={'url': 'https://example.org/PoE2Runbook-Setup-0.5.5.19.exe', 'size': 40897806,
                           'sha256': 'AB' * 32})
        info = self.read(d)
        self.assertEqual((info['version'], info['game'], info['published']), ('0.5.5.19', '0.5.5', '2026-11-26'))
        self.assertEqual((info['url'], info['size'], info['sha256']),
                         ('https://example.org/PoE2Runbook-Setup-0.5.5.19.exe', 40897806, 'ab' * 32))
        self.assertEqual(info['notes'], {'ru': 'Что нового', 'en': 'What is new'})
        self.assertEqual(info['notice'], {})

    def test_changed_file_is_refused(self):
        """Файл изменили после подписи (одна цифра размера) — подпись не сходится."""
        data = raw(doc())
        sig = self.key.sign(data)
        changed = data.replace(b'"size": 3', b'"size": 4')
        self.assertNotEqual(changed, data)
        with self.assertRaises(update.Refused) as e:
            update.read_manifest(changed, sig, self.key.point)
        self.assertEqual(e.exception.code, 'sig')
        # и даже лишний перевод строки в конце: подписаны точные байты
        with self.assertRaises(update.Refused):
            update.read_manifest(data + b'\n', sig, self.key.point)

    def test_foreign_key_is_refused(self):
        """Подпись чужим ключом — не принята."""
        with self.assertRaises(update.Refused) as e:
            self.read(doc(), key=self.other)
        self.assertEqual(e.exception.code, 'sig')

    def test_broken_signature_is_refused(self):
        data = raw(doc())
        good = base64.b64decode(self.key.sign(data))
        for sig in (b'', b'not base64!', base64.b64encode(good[:63]), base64.b64encode(good + b'\0'),
                    base64.b64encode(bytes([good[0] ^ 1]) + good[1:]), base64.b64encode(b'\0' * 64)):
            with self.subTest(sig=sig[:20]):
                with self.assertRaises(update.Refused) as e:
                    update.read_manifest(data, sig, self.key.point)
                self.assertEqual(e.exception.code, 'sig')

    def test_no_key_accepts_nothing(self):
        data = raw(doc())
        with self.assertRaises(update.Refused) as e:
            update.read_manifest(data, self.key.sign(data), None)
        self.assertEqual(e.exception.code, 'nokey')

    def test_wrong_format_is_refused(self):
        """Подписано верно, но не файл обновления этого формата — не принят."""
        bad = {
            'format': doc(format='poe2-runbook-plan'),
            'v2': doc(v=2), 'v-bool': doc(v=True), 'v-str': doc(v='1'),
            'version': doc(version='0.5.5'), 'version-letters': doc(version='0.5.5.18b'),
            'game': dict(doc(), game='0.5.6'),
            'published': dict(doc(), published='26.11.2026'),
            'no-installer': {k: v for k, v in doc().items() if k != 'installer'},
            'http': doc(installer={'url': 'http://example.org/x.exe', 'size': 3, 'sha256': 'a' * 64}),
            'ftp': doc(installer={'url': 'ftp://example.org/x.exe', 'size': 3, 'sha256': 'a' * 64}),
            'user': doc(installer={'url': 'https://u:p@example.org/x.exe', 'size': 3, 'sha256': 'a' * 64}),
            'space': doc(installer={'url': 'https://example.org/a b.exe', 'size': 3, 'sha256': 'a' * 64}),
            'size-str': doc(installer={'url': 'https://example.org/x.exe', 'size': '3', 'sha256': 'a' * 64}),
            'size-bool': doc(installer={'url': 'https://example.org/x.exe', 'size': True, 'sha256': 'a' * 64}),
            'size-0': doc(installer={'url': 'https://example.org/x.exe', 'size': 0, 'sha256': 'a' * 64}),
            'size-big': doc(installer={'url': 'https://example.org/x.exe', 'size': 2 ** 40, 'sha256': 'a' * 64}),
            'sha': doc(installer={'url': 'https://example.org/x.exe', 'size': 3, 'sha256': 'a' * 63}),
        }
        for name, d in bad.items():
            with self.subTest(name):
                with self.assertRaises(update.Refused) as e:
                    self.read(d)
                self.assertEqual(e.exception.code, 'format')
        for name, data in (('not json', b'{"format": '), ('array', b'[1, 2]'), ('bom', b'\xef\xbb\xbf' + raw(doc())),
                           ('latin-1', raw(doc()).replace('Что нового'.encode('utf-8'), 'Что'.encode('cp1251')))):
            with self.subTest(name):
                with self.assertRaises(update.Refused) as e:
                    self.read(data)
                self.assertEqual(e.exception.code, 'format')

    def test_unknown_fields_are_skipped(self):
        d = doc(extra={'any': 1}, notes={'ru': 'да', 'en': 'yes', 'de': 'ja', 'xx-YY': 'нет', 'fr': 5})
        d['installer']['mirror'] = 'whatever'
        info = self.read(d)
        self.assertEqual(info['notes'], {'ru': 'да', 'en': 'yes', 'de': 'ja'})
        self.assertNotIn('extra', info)

    def test_notice_is_one_line_of_plain_text(self):
        """Объявление — одна строка простого текста до 140 знаков: переводы строк схлопнуты, управляющие знаки и знаки
        смены направления письма убраны, длинное обрезано с «…»; разметка остаётся текстом (страница выводит текст)."""
        long = 'Длинное объявление ' * 12
        info = self.read(doc(notice={'ru': 'Строка\nвторая\t\x07 <b>жирно</b>\u202e', 'en': long, 'de': ''}))
        self.assertEqual(info['notice']['ru'], 'Строка вторая <b>жирно</b>')
        self.assertEqual(len(info['notice']['en']), 140)
        self.assertTrue(info['notice']['en'].endswith('…'))
        self.assertNotIn('de', info['notice'])

    def test_key_name(self):
        """Журнал программы называет ключ сборки: в исходниках до keygen его нет — none."""
        import updatekey
        self.assertEqual(update.key_name(), (updatekey.FINGERPRINT or 'none') if updatekey.PUBLIC_KEY else 'none')

    def test_versions(self):
        """Сначала версия игры, потом номер сборки; числа — числами, не строками."""
        self.assertEqual(update.compare('0.5.5.19', '0.5.5.18'), 1)
        self.assertEqual(update.compare('0.5.5.10', '0.5.5.9'), 1)
        self.assertEqual(update.compare('0.6.0.1', '0.5.5.99'), 1)
        self.assertEqual(update.compare('1.0.0.1', '0.5.5.18'), 1)
        self.assertEqual(update.compare('0.5.5.18', '0.5.5.18'), 0)
        self.assertEqual(update.compare('0.5.4.30', '0.5.5.1'), -1)
        self.assertIsNone(update.version_key('0.5.5'))
        self.assertIsNone(update.version_key('v0.5.5.1'))


# --- проверка по расписанию и «Обновить» ---------------------------------------------------------------------------

class Site:
    """Подменённая сеть: адрес -> байты (или исключение); куски установщика — в sink, как у настоящего запроса."""

    def __init__(self):
        self.files, self.asked = {}, []

    def fetch(self, url, limit, timeout, sink=None, progress=None):
        self.asked.append(url)
        got = self.files.get(url)
        if isinstance(got, Exception):
            raise got
        if callable(got):
            return got(url, limit, sink, progress)
        if got is None:
            raise update.NetError('http', 404)
        if len(got) > limit:
            raise update.NetError('big', len(got))
        if sink is None:
            return got
        for i in range(0, len(got), 4):
            sink(got[i:i + 4])
            if progress:
                progress(min(i + 4, len(got)), len(got))
        return len(got)


class UpdaterBase(SignedTest):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data = Path(self.dir.name)
        self.site = Site()
        self.launched, self.quits, self.lines = [], [], []
        self.up = update.Updater(OWN, self.data / 'update', self.data / 'settings.json', self.key.point,
                                 fetch=self.site.fetch, launch=lambda path, log: self.launched.append((path, log)),
                                 quit=lambda: self.quits.append(1), clock=lambda: 1764150000.0,
                                 say=self.lines.append)

    def tearDown(self):
        self.dir.cleanup()

    def publish(self, d, key=None, body=None):
        data = raw(d)
        self.site.files[update.URL] = data
        self.site.files[update.SIG_URL] = (key or self.key).sign(data)
        if body is not None:
            self.site.files[d['installer']['url']] = body

    def view(self, lang='ru'):
        return i18n.render(self.up.view(lang), lang)

    def wait_job(self, *states):
        for _ in range(200):
            if (self.up.job or {}).get('state') in states:
                return
            time.sleep(0.02)
        self.fail('job state %r, waited %r' % (self.up.job, states))


class CheckTest(UpdaterBase):
    def test_newer_version_is_offered(self):
        self.publish(doc('0.5.5.19', notice={'ru': 'Объявление', 'en': 'Notice'}))
        self.assertTrue(self.up.check())
        self.assertEqual(self.site.asked, [update.URL, update.SIG_URL])       # только эти два файла, ничего больше
        v = self.view('ru')
        self.assertEqual((v['state'], v['version'], v['notes'], v['notice']), ('offer', '0.5.5.19', 'Что нового', 'Объявление'))
        self.assertEqual(v['last']['text'], 'есть версия 0.5.5.19')
        # язык страницы без своего текста автора — английский текст автора
        self.assertEqual((self.view('de')['notes'], self.view('de')['notice']), ('What is new', 'Notice'))
        self.assertEqual(self.view('en')['last']['text'], 'version 0.5.5.19 is available')
        self.assertIn('update check: version 0.5.5.19 is available', self.lines)

    def test_same_version_shows_only_the_notice(self):
        """Равная версия не предлагается (её не ставят заново), но объявление видят все."""
        self.publish(doc(OWN, notice={'ru': 'Для всех', 'en': 'For all'}))
        self.assertTrue(self.up.check())
        v = self.view()
        self.assertEqual((v['state'], v['version'], v['notice']), ('none', None, 'Для всех'))
        self.assertEqual(v['last']['text'], 'у вас последняя версия')
        self.assertFalse(self.up.install())

    def test_older_version_is_refused(self):
        """Старая версия (подпись верна) не принимается, её объявление тоже; прежнее предложение снято."""
        self.publish(doc('0.5.5.19'))
        self.up.check()
        self.publish(doc('0.5.5.17', notice={'ru': 'старое', 'en': 'old'}))
        self.assertTrue(self.up.check())
        v = self.view()
        self.assertEqual((v['state'], v['notice']), ('none', None))
        self.assertEqual(v['last']['text'], 'на сайте версия 0.5.5.17 — старее этой, не принята')
        self.publish(doc('0.5.4.30'))                    # старая версия игры с большим номером сборки — тоже старая
        self.up.check()
        self.assertEqual(self.view()['state'], 'none')

    def test_no_answer_keeps_what_was_known(self):
        """Не дозвались — молча: предложение остаётся, в журнале строка; check() говорит «повторить скоро»."""
        self.publish(doc('0.5.5.19'))
        self.up.check()
        self.site.files[update.URL] = update.NetError('net', 'send 12007')
        self.assertFalse(self.up.check())
        v = self.view()
        self.assertEqual((v['state'], v['last']['text']), ('offer', 'нет связи с сайтом программы'))
        self.assertIn('update check: no answer (net send 12007)', self.lines)
        self.site.files[update.URL] = None              # 404
        self.assertFalse(self.up.check())
        self.assertEqual(self.view()['last']['text'], 'сайт программы ответил ошибкой 404')

    def test_bad_signature_offers_nothing(self):
        self.publish(doc('0.5.5.19'), key=self.other)
        self.assertTrue(self.up.check())
        v = self.view()
        self.assertEqual((v['state'], v['last']['text']), ('none', 'подпись не сошлась — файл не принят'))
        self.publish(doc('0.5.5.19'))
        self.site.files[update.SIG_URL] = b'@@@'
        self.up.check()
        self.assertEqual(self.view()['state'], 'none')

    def test_setting_off_asks_nothing(self):
        """«Проверять обновления» выключено: запомнено в settings.json, на страницах ничего, запросов нет."""
        self.publish(doc('0.5.5.19', notice={'ru': 'Для всех', 'en': 'For all'}))
        self.up.check()
        self.assertTrue(self.up.set_on(False))
        self.assertIs(appsettings.load(self.data / 'settings.json')[update.SETTING], False)
        v = self.view()
        self.assertEqual((v['on'], v['state'], v['notice'], v['last']['text']), (False, 'none', None, 'выключена в настройках'))
        self.assertFalse(self.up.install())
        self.assertFalse(self.up.set_on('yes'))
        again = update.Updater(OWN, self.data / 'update', self.data / 'settings.json', self.key.point, fetch=self.site.fetch)
        self.assertFalse(again.on)                      # после перезапуска — так же выключено
        self.assertTrue(again.set_on(True))
        self.assertTrue(again.wake.is_set())            # включили — проверка сразу
        self.assertTrue(update.Updater(OWN, self.data / 'x').on)      # по умолчанию включено

    def test_schedule(self):
        """Расписание: сразу, потом раз в 6 часов; не дозвались — через полчаса; выключено — не спрашивает."""
        waits = []

        class Wake:
            def wait(inner, seconds):
                waits.append(seconds)
                if len(waits) >= 3:
                    self.up.stopped = True

            def clear(inner):
                pass
        self.up.wake = Wake()
        self.publish(doc(OWN))
        self.up.run()
        self.assertEqual(waits, [update.EVERY] * 3)
        self.assertEqual(self.site.asked.count(update.URL), 3)
        waits.clear()
        self.up.stopped, self.site.files[update.URL] = False, update.NetError('net', 'x')
        self.up.run()
        self.assertEqual(waits, [update.SOON] * 3)
        waits.clear()
        self.up.stopped, self.up.urgent = False, lambda: True        # игра новее программы, новой программы нет
        self.publish(doc(OWN))
        self.up.run()
        self.assertEqual(waits, [update.SOON] * 3)
        waits.clear()
        self.site.asked.clear()
        self.up.stopped, self.up.on = False, False
        self.up.run()
        self.assertEqual((waits, self.site.asked), ([update.EVERY] * 3, []))

    def test_agent_is_the_only_thing_said(self):
        self.assertEqual(self.up.agent, 'PoE2Runbook/' + OWN)
        self.assertEqual(update.URL, 'https://poe2.labutin.gg/update/latest.json')
        self.assertEqual(update.SIG_URL, 'https://poe2.labutin.gg/update/latest.json.sig')

    def test_one_address_in_the_program(self):
        """В коде обновления записан ОДИН адрес — poe2.labutin.gg; адрес установщика (выпуски GitHub) — только в
        подписанном файле: место установщиков меняется, не трогая установленные копии."""
        import ast
        tree = ast.parse((HERE / 'update.py').read_text(encoding='utf-8'))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        found = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in docs and n.value.partition('://')[2]}       # адрес, а не только приставка 'https://'
        self.assertEqual(found, {update.URL})
        for path in HERE.glob('*.py'):
            if not path.name.startswith('test_'):
                self.assertNotIn('releases/download', path.read_text(encoding='utf-8'), path.name)


class InstallTest(UpdaterBase):
    BODY = b'fake installer bytes'

    def offer(self, body=None, **inst):
        import hashlib
        body = self.BODY if body is None else body
        d = doc('0.5.5.19', installer=dict({'url': 'https://example.org/dl/PoE2Runbook-Setup-0.5.5.19.exe',
                                            'size': len(self.BODY), 'sha256': hashlib.sha256(self.BODY).hexdigest()},
                                           **inst))
        self.publish(d, body=body)
        self.up.check()
        return d

    def test_download_check_launch(self):
        """«Обновить»: скачан в папку update, сверен, запущен с журналом установщика; программа закрывается."""
        self.offer()
        self.assertTrue(self.up.install())
        self.wait_job('run', 'fail')
        self.assertEqual(self.up.job['state'], 'run')
        final = self.data / 'update' / 'PoE2Runbook-Setup-0.5.5.19.exe'
        self.assertEqual(final.read_bytes(), self.BODY)
        self.assertEqual(self.launched, [(final, self.data / 'update' / 'install.log')])
        for _ in range(100):
            if self.quits:
                break
            time.sleep(0.02)
        self.assertEqual(self.quits, [1])
        self.assertFalse(list((self.data / 'update').glob('*.part')))
        self.assertEqual(self.view()['state'], 'run')

    def test_nothing_without_the_click(self):
        """Без нажатия ничего не качается: проверка спрашивает только два маленьких файла."""
        self.offer()
        self.up.check()
        self.assertEqual(set(self.site.asked), {update.URL, update.SIG_URL})
        self.assertFalse((self.data / 'update').exists())

    def failed(self, code):
        self.assertTrue(self.up.install())
        self.wait_job('fail', 'run')
        self.assertEqual((self.up.job['state'], self.up.job['code']), ('fail', code))
        self.assertEqual(self.launched, [])
        self.assertEqual(self.quits, [])
        self.assertEqual([p.name for p in (self.data / 'update').glob('*')], [])
        v = self.view()
        self.assertEqual(v['state'], 'fail')
        return v

    def test_wrong_size_is_not_launched(self):
        self.offer(body=self.BODY + b'!')               # пришло больше, чем подписано
        self.assertEqual(self.failed('damaged')['error'], 'скачанный файл не сошёлся с подписью и удалён')
        self.offer(body=self.BODY[:-1])                 # меньше
        self.up.job = None
        self.failed('damaged')

    def test_wrong_sha256_is_not_launched(self):
        self.offer(body=b'X' * len(self.BODY))
        self.failed('damaged')

    def test_broken_download_is_removed(self):
        def broken(url, limit, sink, progress):
            sink(self.BODY[:5])
            raise update.NetError('net', 'read 12002')
        self.offer()
        self.site.files[self.up.offer['url']] = broken
        v = self.failed('net')
        self.assertEqual(v['error'], 'загрузка не удалась: нет связи')
        self.assertEqual(i18n.render(self.up.view('en'), 'en')['error'], 'download failed: no connection')
        # адреса нет на сайте (404) — так и сказано
        self.site.files[self.up.offer['url']] = None
        self.assertEqual(self.failed('http')['error'], 'загрузка не удалась: сайт не отдал файл')
        # снова «Обновить» — можно
        self.site.files[self.up.offer['url']] = self.BODY
        self.assertTrue(self.up.install())
        self.wait_job('run')

    def test_launch_failure_is_told(self):
        def refuse(path, log):
            raise OSError('blocked')
        self.offer()
        self.up.launch = refuse
        self.assertTrue(self.up.install())
        self.wait_job('fail')
        self.assertEqual(self.up.job['code'], 'launch')
        self.assertEqual(self.quits, [])

    def test_downloaded_installer_is_reused(self):
        self.offer()
        folder = self.data / 'update'
        folder.mkdir()
        (folder / 'PoE2Runbook-Setup-0.5.5.19.exe').write_bytes(self.BODY)
        self.assertTrue(self.up.install())
        self.wait_job('run')
        self.assertNotIn(self.up.offer['url'], self.site.asked)

    def test_one_install_at_a_time(self):
        gate = threading.Event()

        def slow(url, limit, sink, progress):
            gate.wait(5)
            sink(self.BODY)
            return len(self.BODY)
        self.offer()
        self.site.files[self.up.offer['url']] = slow
        self.assertTrue(self.up.install())
        self.assertFalse(self.up.install())
        self.assertEqual(self.view()['state'], 'load')
        gate.set()
        self.wait_job('run')

    def test_no_offer_no_install(self):
        self.assertFalse(self.up.install())

    def test_tidy(self):
        """При запуске: недокачанное и установщики не новее своей версии убраны, новее — остаются."""
        folder = self.data / 'update'
        folder.mkdir()
        names = ['PoE2Runbook-Setup-0.5.5.17.exe', 'PoE2Runbook-Setup-0.5.5.18.exe', 'PoE2Runbook-Setup-0.5.5.19.exe',
                 'PoE2Runbook-Setup-0.5.5.19.exe.part', 'install.log', 'other.txt']
        for n in names:
            (folder / n).write_bytes(b'x')
        self.up.tidy()
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ['PoE2Runbook-Setup-0.5.5.19.exe', 'install.log', 'other.txt'])


# --- сеть: WinHTTP на этом компьютере -------------------------------------------------------------------------------

class Local(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Local.seen.append({k.lower(): v for k, v in self.headers.items()})
        if self.path == '/moved':
            self.send_response(302)
            self.send_header('Location', '/file')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path != '/file':
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        body = b'0123456789' * 1000
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Set-Cookie', 'id=1')
        self.end_headers()
        self.wfile.write(body)


class Quiet(http.server.ThreadingHTTPServer):
    """Сервер проверок: обрыв соединения клиентом (WinHTTP закрывает своё соединение) — не ошибка для вывода."""

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (ConnectionError, ssl.SSLError)):
            super().handle_error(request, client_address)


@unittest.skipUnless(sys.platform == 'win32', 'WinHTTP — только в Windows')
class NetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Quiet(('127.0.0.1', 0), Local)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:%d' % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_request_says_only_the_version(self):
        """В запросе — только Host, User-Agent: PoE2Runbook/<версия> и Connection; cookies не возвращаются."""
        Local.seen.clear()
        for _ in range(2):
            body = update._request(self.base + '/file', 'PoE2Runbook/' + OWN, 1 << 20, 5, secure=False)
            self.assertEqual(len(body), 10000)
        self.assertEqual(len(Local.seen), 2)
        for headers in Local.seen:
            self.assertEqual(set(headers), {'host', 'user-agent', 'connection'})
            self.assertEqual(headers['user-agent'], 'PoE2Runbook/' + OWN)

    def test_pieces_progress_and_limit(self):
        pieces, steps = [], []
        got = update._request(self.base + '/moved', 'x', 10000, 5, sink=pieces.append,
                              progress=lambda done, total: steps.append((done, total)), secure=False)
        self.assertEqual((got, len(b''.join(pieces)), steps[-1]), (10000, 10000, (10000, 10000)))
        with self.assertRaises(update.NetError) as e:
            update._request(self.base + '/file', 'x', 9999, 5, secure=False)
        self.assertEqual(e.exception.code, 'big')
        with self.assertRaises(update.NetError) as e:
            update._request(self.base + '/nothing', 'x', 9999, 5, secure=False)
        self.assertEqual((e.exception.code, e.exception.detail), ('http', 404))

    def test_only_https(self):
        for url in (self.base + '/file', 'ftp://example.org/x', 'file:///c:/x', None):
            with self.subTest(url=url):
                with self.assertRaises(update.NetError) as e:
                    update.get(url, 'x', 100)
                self.assertEqual(e.exception.code, 'url')

    def test_no_server(self):
        with self.assertRaises(update.NetError) as e:
            update.get('https://127.0.0.1:1/latest.json', 'x', 100, 3)
        self.assertEqual(e.exception.code, 'net')

    @unittest.skipUnless(OPENSSL, 'нужен openssl для сертификата')
    def test_untrusted_certificate_is_refused(self):
        """Сервер с самодельным сертификатом: WinHTTP проверяет сертификат и отказывается."""
        with tempfile.TemporaryDirectory() as tmp:
            cert, key = Path(tmp) / 'c.pem', Path(tmp) / 'k.pem'
            subprocess.run([OPENSSL, 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
                            '-keyout', str(key), '-out', str(cert), '-days', '1', '-subj', '/CN=127.0.0.1'],
                           check=True, capture_output=True)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert), str(key))
            srv = Quiet(('127.0.0.1', 0), Local)
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                with self.assertRaises(update.NetError) as e:
                    update.get('https://127.0.0.1:%d/file' % srv.server_address[1], 'x', 1 << 20, 5)
                self.assertEqual(e.exception.code, 'tls')
            finally:
                srv.shutdown()
                srv.server_close()


# --- подставной установщик: только пишет файл-отметку -------------------------------------------------------------

FAKE = r'''
using System;
using System.IO;
using System.Reflection;
class Fake {
    static void Main(string[] args) {
        string me = Assembly.GetExecutingAssembly().Location;
        File.WriteAllText(me + ".ran", string.Join("\n", args));
    }
}
'''
CSC = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'


def build_fake(folder):
    """Подставной «установщик» (и подставная «программа»): пишет рядом с собой <имя>.ran со своими параметрами."""
    src, exe = Path(folder) / 'fake.cs', Path(folder) / 'fake.exe'
    src.write_text(FAKE, encoding='utf-8')
    subprocess.run([str(CSC), '/nologo', '/target:winexe', '/out:' + str(exe), str(src)], check=True, capture_output=True)
    return exe


def wait_file(path, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if path.exists():
            time.sleep(0.2)
            return True
        time.sleep(0.1)
    return False


@unittest.skipUnless(sys.platform == 'win32' and CSC.is_file() and OPENSSL, 'нужны Windows, csc.exe и openssl')
class LaunchTest(UpdaterBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fake = build_fake(cls.tmp.name).read_bytes()

    def test_download_check_launch_for_real(self):
        """Скачал → сверил → запустил: подставной установщик запускается отдельным процессом с ключами тихой установки
        и журналом, пишет отметку; программа закрывается (quit)."""
        import hashlib
        d = doc('0.5.5.19', installer={'url': 'https://example.org/dl/PoE2Runbook-Setup-0.5.5.19.exe',
                                       'size': len(self.fake), 'sha256': hashlib.sha256(self.fake).hexdigest()})
        self.publish(d, body=self.fake)
        self.up.launch = update.start_installer
        self.up.check()
        self.assertTrue(self.up.install())
        final = self.data / 'update' / 'PoE2Runbook-Setup-0.5.5.19.exe'
        mark = final.with_name(final.name + '.ran')
        self.assertTrue(wait_file(mark), 'подставной установщик не запустился')
        args = mark.read_text(encoding='utf-8').split('\n')
        self.assertEqual(args, list(update.SWITCHES) + ['/LOG=%s' % (self.data / 'update' / 'install.log')])
        for _ in range(100):
            if self.quits:
                break
            time.sleep(0.02)
        self.assertEqual(self.quits, [1])
        self.assertEqual(self.up.process.wait(10), 0)     # подставной установщик закончил сам


# --- packaging/update.iss: пробный установщик Inno Setup -----------------------------------------------------------

ISCC = next((p for p in (Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Inno Setup 6' / 'ISCC.exe',
                         Path(os.environ.get('ProgramFiles(x86)', '')) / 'Inno Setup 6' / 'ISCC.exe',
                         Path(os.environ.get('ProgramFiles', '')) / 'Inno Setup 6' / 'ISCC.exe') if p.is_file()), None)
ISS = ROOT / 'packaging' / 'update.iss'
PROBE_ISS = r'''
[Setup]
AppId={{0D7F4E8A-2B1C-4E5D-9A3F-6C8B1E2D4F70}
AppName=PoE2 Runbook update probe
AppVersion=0.0.0.1
DefaultDirName={#AppDir}
CreateAppDir=yes
Uninstallable=no
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
OutputDir={#OutDir}
OutputBaseFilename=probe-setup
CloseApplications=yes
RestartApplications=no
#include Include
'''


@unittest.skipUnless(sys.platform == 'win32' and ISCC and CSC.is_file() and ISS.is_file(), 'нужны Windows, Inno Setup 6, csc.exe')
class InnoTest(unittest.TestCase):
    """Пробный установщик с packaging/update.iss (свой AppId, ничего не ставит, не регистрируется в Windows;
    «программа» — подставная, во временной папке)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.app = root / 'app'
        cls.app.mkdir()
        cls.mutex = 'Local\\PoE2RunbookProbe-%d' % os.getpid()
        shutil.copy2(build_fake(root), cls.app / 'PoE2Runbook.exe')
        (root / 'probe.iss').write_text(PROBE_ISS, encoding='utf-8')
        subprocess.run([str(ISCC), '/Q', '/DAppDir=' + str(cls.app), '/DOutDir=' + str(root), '/DInclude=' + str(ISS),
                        '/DAppMutex=' + cls.mutex, str(root / 'probe.iss')], check=True, capture_output=True)
        cls.setup = root / 'probe-setup.exe'

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.mark = self.app / 'PoE2Runbook.exe.ran'
        if self.mark.exists():
            self.mark.unlink()

    def test_waits_for_the_program_then_opens_it(self):
        """Тихая установка из программы: ждёт, пока мьютекс программы исчезнет, потом ставит и открывает программу."""
        from ctypes import wintypes as w
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateMutexW.argtypes, k.CreateMutexW.restype = [ctypes.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        held = k.CreateMutexW(None, False, self.mutex)
        self.assertTrue(held)
        run = subprocess.Popen([str(self.setup)] + list(update.SWITCHES))
        try:
            time.sleep(2.5)
            self.assertIsNone(run.poll(), 'установщик не ждал программу')
            self.assertFalse(self.mark.exists(), 'программа открыта раньше, чем закрылась прежняя')
            released = time.time()
            k.CloseHandle(held)
            held = None
            self.assertEqual(run.wait(30), 0)
            self.assertTrue(wait_file(self.mark), 'после установки программа не открылась')
            self.assertGreaterEqual(self.mark.stat().st_mtime, released - 1)
        finally:
            if held:
                k.CloseHandle(held)
            if run.poll() is None:
                run.kill()

    def test_plain_silent_install_does_not_open_the_program(self):
        """Тихая установка без /RESTARTAPPLICATIONS (не из программы) программу не открывает и ничего не ждёт."""
        done = subprocess.run([str(self.setup), '/VERYSILENT', '/SUPPRESSMSGBOXES'], timeout=60)
        self.assertEqual(done.returncode, 0)
        time.sleep(1.5)
        self.assertFalse(self.mark.exists())


if __name__ == '__main__':
    unittest.main()
