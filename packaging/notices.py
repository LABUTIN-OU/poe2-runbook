# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Сторонние компоненты сборки: что из чужого кода РЕАЛЬНО попало в папку программы, под какой лицензией — и полные
тексты этих лицензий.

Запуск (packaging/build.py зовёт его сам — после PyInstaller, до проверки и установщика):
    packaging\\.venv\\Scripts\\python.exe packaging\\notices.py [--app <папка программы>] [--inno <ISCC.exe>]
Нужен Python того окружения, из которого собиралась программа (packaging\\.venv): метаданные пакетов берутся из него.

Что получается в папке программы:
    THIRD-PARTY.md              — рядом с exe: компоненты (название, версия, лицензия) и полные тексты их лицензий;
    _internal/third-party.json  — тот же список для окна «О программе» (planner/about.py).

Как узнаётся, что попало в сборку:
  * модули Python — по оглавлению архива внутри exe (PYZ) и скриптам запуска рядом с ним;
  * файлы — по папке программы: библиотеки (.dll, .pyd), данные пакетов;
  * чей модуль или файл — по списку файлов (RECORD) пакетов окружения сборки, у setuptools — и его вложенных пакетов
    (setuptools/_vendor); файлы самого Python — по его папке (sys.base_prefix); свои модули — по planner/*.py;
  * установщик Inno Setup — когда сборка его делает (--inno): его программа удаления ставится в папку программы.

Сборка останавливается, если
  * модуль или файл не удалось приписать ни программе, ни Python, ни пакету окружения;
  * у компонента нет записи в LICENSES (лицензию проверил человек) или не нашёлся полный текст его лицензии;
  * лицензия в метаданных пакета не та, что в записи, или версия компонента с отдельно сохранённым текстом лицензии
    не та, для которой текст сохранён (компонент обновили — запись пересматривают).
"""
import argparse
import ctypes
import importlib.metadata as md
import json
import os
import platform
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
TEXTS = HERE / 'licenses'           # тексты лицензий, которых нет в самих пакетах
OUT_MD = 'THIRD-PARTY.md'
OUT_JSON = 'third-party.json'
OWN_DATA = ('static', 'lang', 'catalog', 'knowledge', 'plans', OUT_JSON)      # своё в _internal (и данные игры)
OWN_ROOT = ('LICENSE', 'NOTICE.md', OUT_MD, 'PoE2Runbook.exe')

# Запись о каждом компоненте, который может попасть в сборку: лицензия (SPDX), страница проекта; meta — как лицензию
# называют метаданные пакета (License-Expression, иначе License, иначе классификаторы «License ::»): назовут иначе —
# сборка стоит. text — файлы из packaging/licenses, когда в самом пакете текста нет; version — для какой версии они взяты.
LICENSES = {
    # пакеты окружения сборки (ключ — имя пакета по PEP 503)
    'pywebview': dict(name='pywebview', licence='BSD-3-Clause', meta='BSD 3-Clause License',
                      url='https://github.com/r0x0r/pywebview'),
    'pythonnet': dict(name='pythonnet', licence='MIT', meta='MIT', url='https://github.com/pythonnet/pythonnet'),
    'clr-loader': dict(name='clr_loader', licence='MIT', meta='', url='https://github.com/pythonnet/clr-loader'),
    'bottle': dict(name='bottle', licence='MIT', meta='MIT', url='https://bottlepy.org'),
    'proxy-tools': dict(name='proxy_tools', licence='MIT', meta='MIT', url='https://github.com/jtushman/proxy_tools',
                        text=['proxy_tools.txt'], version='0.1.0'),
    'cffi': dict(name='cffi', licence='MIT-0', meta='MIT-0', url='https://github.com/python-cffi/cffi'),
    'pycparser': dict(name='pycparser', licence='BSD-3-Clause', meta='BSD-3-Clause', url='https://github.com/eliben/pycparser'),
    'packaging': dict(name='packaging', licence='Apache-2.0 OR BSD-2-Clause', meta='Apache-2.0 OR BSD-2-Clause',
                      url='https://github.com/pypa/packaging'),
    'setuptools': dict(name='setuptools', licence='MIT', meta='MIT', url='https://github.com/pypa/setuptools'),
    'typing-extensions': dict(name='typing_extensions', licence='PSF-2.0', meta='PSF-2.0',
                              url='https://github.com/python/typing_extensions'),
    # пакеты внутри setuptools (setuptools/_vendor)
    'backports-tarfile': dict(name='backports.tarfile', licence='MIT', meta='License :: OSI Approved :: MIT License',
                              url='https://github.com/jaraco/backports.tarfile'),
    'jaraco-context': dict(name='jaraco.context', licence='MIT', meta='MIT', url='https://github.com/jaraco/jaraco.context'),
    'jaraco-functools': dict(name='jaraco.functools', licence='MIT', meta='MIT',
                             url='https://github.com/jaraco/jaraco.functools'),
    'jaraco-text': dict(name='jaraco.text', licence='MIT', meta='License :: OSI Approved :: MIT License',
                        url='https://github.com/jaraco/jaraco.text'),
    'more-itertools': dict(name='more-itertools', licence='MIT', meta='MIT', url='https://github.com/more-itertools/more-itertools'),
    'tomli': dict(name='tomli', licence='MIT', meta='MIT', url='https://github.com/hukkin/tomli'),
    'wheel': dict(name='wheel', licence='MIT', meta='MIT', url='https://github.com/pypa/wheel'),
    # не из пакетов окружения
    'python': dict(name='Python', licence='PSF-2.0', url='https://www.python.org'),
    'pyinstaller': dict(name='PyInstaller', licence='GPL-2.0-or-later WITH Bootloader-exception',
                        meta='GPLv2-or-later with a special exception which allows to use PyInstaller to build and '
                             'distribute non-free programs (including commercial ones)',
                        url='https://pyinstaller.org'),
    'webview2-sdk': dict(name='Microsoft Edge WebView2 SDK', licence='BSD-3-Clause',
                         url='https://www.nuget.org/packages/Microsoft.Web.WebView2', text=['Microsoft.Web.WebView2.txt'],
                         version='1.0.3856.49'),
    'inno-setup': dict(name='Inno Setup', licence='Inno Setup License', url='https://jrsoftware.org/isinfo.php'),
}

# Части Python, у которых своя лицензия: по каким файлам их видно в сборке. Тексты их лицензий — в лицензии Python
# (LICENSE.txt его папки) и в его документации («Licenses and Acknowledgements for Incorporated Software»).
PYTHON_PARTS = [
    ('OpenSSL', 'Apache-2.0', ('libcrypto-3.dll', 'libssl-3.dll')),
    ('libffi', 'MIT', ('libffi-8.dll',)),
    ('Expat', 'MIT', ('pyexpat.pyd',)),
    ('bzip2', 'bzip2-1.0.6', ('_bz2.pyd',)),
    ('libmpdec', 'BSD-2-Clause', ('_decimal.pyd',)),
    ('zlib', 'Zlib', ('python312.dll', 'python313.dll', 'python314.dll')),
    ('Microsoft Visual C++ Runtime', 'Microsoft Distributable Code', ('vcruntime140.dll', 'vcruntime140_1.dll')),
]
PYINSTALLER_HOOKS = ('PyInstaller run-time hooks', 'Apache-2.0')        # pyi_rth_* в exe (COPYING.txt PyInstaller)
WEBVIEW2_FILES = re.compile(r'(?i)(microsoft\.web\.webview2\.[\w.]+\.dll|webview2loader\.dll)')


class Stop(Exception):
    """Сборку дальше вести нельзя: что-то попало в сборку без записи о лицензии."""


def canon(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def meta_licence(dist):
    m = dist.metadata
    if m.get('License-Expression'):
        return m['License-Expression'].strip()
    lic = (m.get('License') or '').strip().splitlines()
    if lic and lic[0].strip():
        return lic[0].strip()
    return '; '.join(c for c in (m.get_all('Classifier') or []) if c.startswith('License ::'))


def file_version(path):
    """Версия файла из его ресурса версии (как в «Свойства → Подробно»); нет ресурса — ''."""
    if sys.platform != 'win32':
        return ''
    from ctypes import wintypes as w
    ver = ctypes.WinDLL('version')
    ver.GetFileVersionInfoSizeW.argtypes, ver.GetFileVersionInfoSizeW.restype = [w.LPCWSTR, ctypes.POINTER(w.DWORD)], w.DWORD
    ver.GetFileVersionInfoW.argtypes, ver.GetFileVersionInfoW.restype = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p], w.BOOL
    ver.VerQueryValueW.argtypes = [ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    ver.VerQueryValueW.restype = w.BOOL
    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ''
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return ''
    ptr, n = ctypes.c_void_p(), ctypes.c_uint()
    if not ver.VerQueryValueW(buf, '\\', ctypes.byref(ptr), ctypes.byref(n)) or not ptr.value:
        return ''
    fixed = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 4)).contents     # подпись, версия структуры, MS, LS
    ms, ls = fixed[2], fixed[3]
    return '%d.%d.%d.%d' % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def inno_version(iscc):
    """Версия Inno Setup, которым собирается установщик: так её записал его собственный установщик (DisplayVersion)."""
    try:
        import winreg
    except ImportError:
        return ''
    home = os.path.normcase(str(Path(iscc).resolve().parent))
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1', 0,
                                    winreg.KEY_READ | view) as k:
                    where = os.path.normcase(str(Path(winreg.QueryValueEx(k, 'InstallLocation')[0]).resolve()))
                    if where == home:
                        return str(winreg.QueryValueEx(k, 'DisplayVersion')[0])
            except OSError:
                continue
    return ''


# --- что попало в сборку ------------------------------------------------------------------------------------------

def built_modules(exe):
    """Модули Python внутри exe: (скрипты и модули запуска PyInstaller, модули архива PYZ)."""
    from PyInstaller.archive.readers import CArchiveReader
    car = CArchiveReader(str(exe))
    pyz_name = next((n for n in car.toc if n.endswith('.pyz')), None)
    if pyz_name is None:
        raise Stop('%s: no PYZ archive inside' % exe)
    boot = [n for n in car.toc if n != pyz_name]
    return boot, sorted(car.open_embedded_archive(pyz_name).toc)


class Index:
    """Чей файл: путь относительно site-packages окружения сборки -> пакет (у setuptools/_vendor — вложенный пакет)."""

    def __init__(self, site):
        self.site, self.files, self.dists = Path(site), {}, {}
        vendored = self.site / 'setuptools' / '_vendor'
        for d in md.distributions(path=[str(self.site)]):
            self._add(d, '')
        if vendored.is_dir():
            for d in md.distributions(path=[str(vendored)]):
                self._add(d, 'setuptools/_vendor/', parent='setuptools')

    def _add(self, dist, prefix, parent=None):
        key = canon(dist.metadata['Name'])
        self.dists[(key, prefix)] = (dist, parent)
        for f in dist.files or []:
            rel = (prefix + str(f).replace('\\', '/')).lower()
            if rel.startswith('../') or '__pycache__' in rel or '.dist-info/' in rel:
                continue
            # вложенный пакет setuptools сильнее самого setuptools (тот тоже перечисляет эти файлы в RECORD)
            if prefix or rel not in self.files:
                self.files[rel] = (key, prefix)

    def module(self, name):
        """Чей модуль (по имени из PYZ): (ключ, приставка) или 'ns' — пакет без файлов (пространство имён), None — ничей."""
        base = name.replace('.', '/').lower()
        for rel in (base + '.py', base + '/__init__.py', base + '.pyd'):
            if rel in self.files:
                return self.files[rel]
        for rel in self.files:
            if rel.startswith(base + '.') and rel.endswith('.pyd'):        # _cffi_backend.cp312-win_amd64.pyd
                return self.files[rel]
        if any(rel.startswith(base + '/') for rel in self.files):
            return 'ns'
        return None

    def file(self, rel):
        return self.files.get(rel.replace('\\', '/').lower())


def scan(app, own_modules, inno=None):
    """Что в папке программы и чьё оно. Ответ: {ключ компонента: {'dist': …, 'parts': {…}}}; ничьё — Stop."""
    app = Path(app)
    exe = app / 'PoE2Runbook.exe'
    internal = app / '_internal'
    if not exe.is_file() or not internal.is_dir():
        raise Stop('%s is not a built program folder (no PoE2Runbook.exe / _internal)' % app)
    site = Path(sys.prefix) / 'Lib' / 'site-packages'
    index = Index(site)
    base = Path(sys.base_prefix)            # папка самого Python: python3xx.dll, vcruntime, DLLs\*.pyd, OpenSSL, libffi
    base_files = {p.name.lower() for d in (base, base / 'DLLs') if d.is_dir() for p in d.iterdir() if p.is_file()}
    stdlib = set(sys.stdlib_module_names)
    found, unknown = {}, []

    def take(key, prefix='', part=None):
        c = found.setdefault((key, prefix), {'parts': set()})
        if part:
            c['parts'].add(part)

    # exe: загрузчик PyInstaller, его модули запуска, хуки запуска, свой скрипт
    take('pyinstaller')
    boot, modules = built_modules(exe)
    for n in boot:
        if n.startswith(('pyimod', 'pyiboot')):
            take('pyinstaller')
        elif n.startswith('pyi_rth_'):
            take('pyinstaller', part=PYINSTALLER_HOOKS[0])
        elif n in own_modules:
            continue
        elif n.split('.')[0] in stdlib:
            take('python')
        else:
            unknown.append('exe script ' + n)
    for n in modules:
        top = n.split('.')[0]
        if top in own_modules:
            continue
        if top in stdlib:
            take('python')
            continue
        owner = index.module(n)
        if owner == 'ns':
            continue
        if owner is None:
            unknown.append('module ' + n)
            continue
        take(*owner)
    # файлы папки программы
    for p in sorted(app.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(app).as_posix()
        if rel in OWN_ROOT:
            continue
        if not rel.startswith('_internal/'):
            if inno and re.fullmatch(r'unins\d+\.(exe|dat|msg)', rel, re.I):
                continue
            unknown.append('file ' + rel)
            continue
        rel = rel[len('_internal/'):]
        top = rel.split('/')[0]
        if top in OWN_DATA:
            continue
        name = p.name.lower()
        if WEBVIEW2_FILES.fullmatch(name):
            take('webview2-sdk')
            continue
        if '/' not in rel and (name in base_files or rel == 'base_library.zip'):
            take('python')
            for part, _lic, names in PYTHON_PARTS:
                if name in names:
                    take('python', part=part)
            continue
        owner = index.file(rel)
        if owner is None:
            unknown.append('file _internal/' + rel)
            continue
        take(*owner)
    if inno:
        take('inno-setup')
    if unknown:
        raise Stop('not attributed to any component (add a record to packaging/notices.py):\n  ' + '\n  '.join(unknown))
    return found, index


# --- тексты лицензий ---------------------------------------------------------------------------------------------

class _Text(HTMLParser):
    """Текст раздела «Licenses and Acknowledgements for Incorporated Software» страницы license.html документации Python."""

    ID = 'licenses-and-acknowledgements-for-incorporated-software'

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.depth, self.skip, self.pre = [], 0, 0, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('section', 'div') and (self.depth or a.get('id') == self.ID):
            self.depth += 1             # раздел (и вложенные в него) — пока глубина не вернётся к нулю
        if not self.depth:
            return
        if tag in ('a', 'script', 'style') and (tag != 'a' or 'headerlink' in (a.get('class') or '')):
            self.skip += 1
        if tag == 'pre':
            self.pre += 1
        if tag in ('p', 'div', 'pre', 'h2', 'h3', 'h4', 'li', 'br', 'section'):
            self.out.append('\n')

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag in ('section', 'div'):
            self.depth -= 1
        if tag in ('a', 'script', 'style') and self.skip:
            self.skip -= 1
        if tag == 'pre':
            self.pre -= 1
        if tag in ('h2', 'h3', 'h4', 'p', 'pre'):
            self.out.append('\n')

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.out.append(data if self.pre else re.sub(r'\s+', ' ', data))


def python_texts():
    base = Path(sys.base_prefix)
    lic = base / 'LICENSE.txt'
    if not lic.is_file():
        raise Stop('no %s: the licence text of Python is required' % lic)
    texts = [('LICENSE.txt', lic.read_text(encoding='utf-8', errors='replace'))]
    doc = base / 'Doc' / 'html' / 'license.html'
    if doc.is_file():
        p = _Text()
        p.feed(doc.read_text(encoding='utf-8', errors='replace'))
        body = '\n'.join(line.rstrip() for line in ''.join(p.out).replace('\xa0', ' ').split('\n'))
        body = re.sub(r'\n{3,}', '\n\n', body).strip()
        if body:
            texts.append(('Doc/html/license.html — Licenses and Acknowledgements for Incorporated Software', body))
    return texts


def dist_texts(dist):
    """Полные тексты лицензии из самого пакета: файлы License-File (licenses/… или рядом с METADATA)."""
    names = dist.metadata.get_all('License-File') or []
    out = []
    for n in names:
        for rel in ('licenses/' + n, n):
            t = dist.read_text(rel)
            if t:
                out.append((n, t))
                break
    return out


def own_texts(rec):
    out = []
    for n in rec.get('text') or []:
        f = TEXTS / n
        if not f.is_file():
            raise Stop('no licence text %s' % f)
        out.append((n, f.read_text(encoding='utf-8')))
    return out


def python_versions():
    """Версии частей Python, которые он сам о себе сообщает."""
    import decimal
    import pyexpat
    import ssl
    import zlib
    m = re.search(r'\d+\.\d+\.\d+\w*', ssl.OPENSSL_VERSION)
    lic = (Path(sys.base_prefix) / 'LICENSE.txt').read_text(encoding='utf-8', errors='replace')
    bz = re.search(r'bzip2/libbzip2 version (\d+\.\d+\.\d+)', lic)
    return {'OpenSSL': m.group() if m else '', 'Expat': pyexpat.EXPAT_VERSION.replace('expat_', ''),
            'zlib': zlib.ZLIB_RUNTIME_VERSION, 'libmpdec': decimal.__libmpdec_version__, 'bzip2': bz.group(1) if bz else ''}


def collect(app, own_modules, inno=None):
    """Компоненты сборки с лицензиями и текстами. Ответ: список {name, version, licence, url, parts, texts}."""
    found, index = scan(app, own_modules, inno)
    internal = Path(app) / '_internal'
    pyver = python_versions()
    comps, problems = [], []
    for (key, prefix), c in found.items():
        rec = LICENSES.get(key)
        if rec is None:
            problems.append('%s: no licence record in LICENSES' % key)
            continue
        item = {'key': key, 'name': rec['name'], 'licence': rec['licence'], 'url': rec['url'], 'parts': [], 'in': None}
        if key == 'python':
            item['version'] = platform.python_version()
            texts = python_texts()
            vc = internal / 'VCRUNTIME140.dll'
            pyver['Microsoft Visual C++ Runtime'] = file_version(vc) if vc.is_file() else ''
            for part, lic, _names in PYTHON_PARTS:
                if part in c['parts']:
                    item['parts'].append({'name': part, 'version': pyver.get(part, ''), 'licence': lic})
        elif key == 'webview2-sdk':
            core = next(iter(sorted(internal.rglob('Microsoft.Web.WebView2.Core.dll'))), None)
            item['version'] = file_version(core) if core else ''
            texts = own_texts(rec)
        elif key == 'inno-setup':
            item['version'] = inno_version(inno)
            lic = Path(inno).resolve().parent / 'license.txt'
            if not lic.is_file():
                problems.append('inno-setup: no %s' % lic)
                continue
            texts = [('license.txt', lic.read_text(encoding='utf-8', errors='replace'))]
        else:
            dist, parent = index.dists[(key, prefix)]
            item['version'] = dist.metadata['Version']
            item['in'] = parent
            meta = meta_licence(dist)
            if 'meta' in rec and meta != rec['meta']:
                problems.append('%s %s: package metadata says licence %r, the record says %r — review the record'
                                % (rec['name'], item['version'], meta, rec['meta']))
            texts = dist_texts(dist) or own_texts(rec)
            if key == 'pyinstaller' and PYINSTALLER_HOOKS[0] in c['parts']:
                item['parts'].append({'name': PYINSTALLER_HOOKS[0], 'version': item['version'], 'licence': PYINSTALLER_HOOKS[1]})
        if rec.get('version') and item['version'] != rec['version']:
            problems.append('%s: the saved licence text is for version %s, the build has %s — check the licence of the new '
                            'version and update packaging/licenses' % (rec['name'], rec['version'], item['version']))
        if not texts:
            problems.append('%s: no licence text (neither in the package nor in packaging/licenses)' % rec['name'])
        item['texts'] = texts
        comps.append(item)
    if problems:
        raise Stop('\n  '.join(['third-party notices:'] + problems))
    order = {k: i for i, k in enumerate(['python', 'pywebview', 'webview2-sdk', 'pythonnet', 'clr-loader', 'bottle',
                                         'proxy-tools', 'cffi', 'pycparser', 'packaging', 'setuptools', 'typing-extensions',
                                         'pyinstaller', 'inno-setup'])}
    top = sorted((c for c in comps if not c['in']), key=lambda c: (order.get(c['key'], 99), c['name'].lower()))
    for c in sorted((c for c in comps if c['in']), key=lambda c: c['name'].lower()):
        host = next(t for t in top if t['key'] == c['in'])
        host['parts'].append({'name': c['name'], 'version': c['version'], 'licence': c['licence'], 'url': c['url'],
                              'texts': c['texts']})
    return top


# --- запись -------------------------------------------------------------------------------------------------------

def fence(text):
    run = max([len(m.group()) for m in re.finditer(r'`+', text)] + [2])
    return '`' * (run + 1)


def write(app, comps, program=None):
    app = Path(app)
    rows, body = [], []

    def row(c, sub=False):
        rows.append('| %s%s | %s | %s |' % ('↳ ' if sub else '', c['name'], c.get('version') or '—', c['licence']))

    def block(c, level):
        body.append('%s %s %s — %s' % ('#' * level, c['name'], c.get('version') or '', c['licence']))
        body.append('')
        if c.get('url'):
            body.append('<%s>' % c['url'])
            body.append('')
        for name, text in c.get('texts') or []:
            f = fence(text)
            body.extend(['%s: %s' % ('Licence file' if level == 2 else 'File', name), '', f + 'text', text.rstrip('\n'), f, ''])

    for c in comps:
        row(c)
        for p in c['parts']:
            row(p, sub=True)
    for c in comps:
        block(c, 2)
        own = [p for p in c['parts'] if p.get('texts')]
        rest = [p for p in c['parts'] if not p.get('texts')]
        if rest:
            body.append('Parts of %s in this program, each under its own licence — the texts are in the licence of %s '
                        'above: %s.' % (c['name'], c['name'], ', '.join('%s %s (%s)' % (p['name'], p['version'], p['licence'])
                                                                          if p['version'] else '%s (%s)' % (p['name'], p['licence'])
                                                                          for p in rest)))
            body.append('')
        for p in own:
            block(p, 3)
    head = ['# Third-party components of PoE2 Runbook%s' % (' ' + program if program else ''), '',
            'PoE2 Runbook includes the third-party components listed below. Each of them stays under its own licence; '
            'the full texts of these licences follow the list. The program itself is licensed under the GNU General '
            'Public License, version 3, with additional terms — see the files `LICENSE` and `NOTICE.md`.', '',
            'This file is generated by `packaging/notices.py` from what the build really contains.', '',
            '| Component | Version | Licence |', '|---|---|---|'] + rows + ['']
    tail = ['## Path of Exile 2 game data', '',
            "This product isn't affiliated with or endorsed by Grinding Gear Games in any way.", '',
            'Path of Exile 2 game data and images that come with the program — the catalogue of game data, pictures of '
            'items and skills, the passive tree and atlas data, names in the game\'s languages — belong to Grinding Gear '
            'Games. The licences above do not cover them.', '']
    (app / OUT_MD).write_text('\n'.join(head + body + tail), encoding='utf-8', newline='\n')
    plain = [{'name': c['name'], 'version': c.get('version') or '', 'licence': c['licence'],
              'parts': [{'name': p['name'], 'version': p.get('version') or '', 'licence': p['licence']} for p in c['parts']]}
             for c in comps]
    data = {'format': 'poe2-runbook-third-party', 'v': 1, 'program': program or '', 'components': plain}
    (app / '_internal' / OUT_JSON).write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8',
                                              newline='\n')
    return data


def own_modules(root):
    """Свои модули программы: planner/*.py (без проверок) — по ним видно, что в exe наше."""
    return {p.stem for p in (Path(root) / 'planner').glob('*.py') if not p.stem.startswith('test_')}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--app', default=str(HERE / 'dist' / 'PoE2Runbook'), help='папка собранной программы')
    ap.add_argument('--root', default=str(PROJECT), help='папка исходников (planner/*.py — свои модули)')
    ap.add_argument('--inno', help='ISCC.exe, если сборка делает установщик')
    ap.add_argument('--program', help='версия программы — в заголовок THIRD-PARTY.md')
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        # build.py зовёт этот скрипт без -X utf8: консоль Windows может не знать какого-то знака из названий
        sys.stdout.reconfigure(errors='replace')
    try:
        comps = collect(args.app, own_modules(args.root), args.inno)
    except Stop as e:
        sys.exit(str(e))
    data = write(args.app, comps, args.program)
    n = sum(1 + len(c['parts']) for c in data['components'])
    print('== third-party notices: %d components (%d with parts) -> %s, _internal/%s'
          % (len(data['components']), n, OUT_MD, OUT_JSON), flush=True)
    for c in data['components']:
        print('   %-30s %-12s %s' % (c['name'], c['version'], c['licence']))
        for p in c['parts']:
            print('     + %-26s %-12s %s' % (p['name'], p['version'], p['licence']))


if __name__ == '__main__':
    main()
