# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Инструмент выпуска: ключ подписи обновлений и подписанный файл обновления для сайта. Ничего никуда не отправляет.

    python -X utf8 release/publish.py keygen
        Создаёт закрытый ключ автора (ECDSA P-256) вне проекта — %USERPROFILE%\\.poe2runbook\\release-key.pem;
        существующий не перезаписывает. Вписывает открытый ключ в программу (planner/updatekey.py) и называет его
        отпечаток. Ключ уже есть — только вписывает его открытый ключ заново. Программа уже знает ДРУГОЙ ключ —
        отказ (--replace — заменить: копии, установленные со старым ключом, тогда не примут ни одного обновления).
        СОХРАНИТЕ КОПИЮ КЛЮЧА ВНЕ КОМПЬЮТЕРА: потеряете — установленные копии перестанут принимать обновления.

    python -X utf8 release/publish.py manifest dist\\PoE2Runbook-Setup-0.5.5.18.exe
            --notes-ru "что изменилось" --notes-en "what changed" [--notice-ru "…" --notice-en "…"] [--url https://…]
        Пишет site/update/latest.json и latest.json.sig. Адрес установщика по умолчанию — выпуск GitHub с меткой
        v<версия>: https://github.com/LABUTIN-OU/poe2-runbook/releases/download/v<версия>/PoE2Runbook-Setup-<версия>.exe
        (RELEASE_URL; другой — --url). В самой программе этого адреса нет: она берёт его только из подписанного файла,
        поэтому место установщиков можно сменить, не трогая установленные копии. Версия — из имени установщика (сверена с его свойствами),
        размер и SHA-256 — по самому файлу, подпись — закрытым ключом. Отказывается, если версия не новее уже
        записанной, если адрес не https:// или не кончается именем установщика, если объявление длиннее 140 знаков или
        не в одну строку. Перед записью проверяет пару тем же кодом, каким проверяет программа (planner/update.py), с
        ключом, вписанным в программу: программа такой файл не примет — он не пишется.

    python -X utf8 release/publish.py verify
        Проверяет site/update/latest.json и подпись тем же кодом и ключом, что программа, и называет, что в файле.
        Установщик этой версии лежит в dist — сверяет и его размер и SHA-256.

Подписывает openssl из Git для Windows (или из PATH): «openssl dgst -sha256 -sign ключ», подпись DER переводится в r‖s
(по 32 байта, с нулями слева) и пишется base64 — так, как её ждёт программа. Для проверок: --key, --site, --planner
(папка с updatekey.py), --dist — другие места.
"""
import argparse
import base64
import ctypes
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent          # release/
ROOT = HERE.parent                               # папка проекта
sys.path.insert(0, str(ROOT / 'planner'))
import update  # noqa: E402 — тот же код проверки, что у программы

KEY = Path(os.environ.get('USERPROFILE') or Path.home()) / '.poe2runbook' / 'release-key.pem'
SITE = ROOT / 'site' / 'update'
PLANNER = ROOT / 'planner'
DIST = ROOT / 'dist'
KEY_MODULE = 'updatekey.py'
# Где лежат установщики: выпуски репозитория на GitHub, метка выпуска — v<версия>. Адрес по умолчанию для manifest.
RELEASE_URL = 'https://github.com/LABUTIN-OU/poe2-runbook/releases/download/v%(version)s/%(name)s'
RE_KEY_LINE = re.compile(r"^PUBLIC_KEY = '([A-Za-z0-9+/=]+)'", re.M)


class Stop(Exception):
    """Отказ инструмента: текст — почему, для автора."""


# --- openssl ------------------------------------------------------------------------------------------------------

def openssl():
    """openssl: из PATH, иначе из Git для Windows (рядом с git.exe или в Program Files)."""
    found = shutil.which('openssl')
    if found:
        return found
    roots = []
    git = shutil.which('git')
    if git:
        roots += list(Path(git).resolve().parents)[:3]
    for env in ('ProgramFiles', 'ProgramW6432', 'LOCALAPPDATA'):
        if os.environ.get(env):
            roots += [Path(os.environ[env]) / 'Git', Path(os.environ[env]) / 'Programs' / 'Git']
    for root in roots:
        for rel in ('mingw64/bin/openssl.exe', 'usr/bin/openssl.exe'):
            if (root / rel).is_file():
                return str(root / rel)
    raise Stop('openssl не найден: нужен Git для Windows (в нём есть openssl) или openssl в PATH')


def run_openssl(*args):
    """openssl с аргументами; ответ — его вывод (байты). Ошибка — Stop с его словами."""
    done = subprocess.run([openssl()] + [str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode != 0:
        raise Stop('openssl %s: %s' % (args[0], done.stderr.decode('utf-8', 'replace').strip()[:400]))
    return done.stdout


def der_to_rs(der):
    """Подпись ECDSA из DER (SEQUENCE двух INTEGER) -> r‖s по 32 байта, с нулями слева."""
    if len(der) < 8 or der[0] != 0x30 or der[1] != len(der) - 2:
        raise Stop('подпись openssl не в виде DER')
    i, out = 2, b''
    for _ in range(2):
        if der[i] != 0x02:
            raise Stop('подпись openssl не в виде DER')
        n = der[i + 1]
        value = der[i + 2:i + 2 + n].lstrip(b'\0')
        if len(value) > 32:
            raise Stop('подпись openssl не P-256')
        out += value.rjust(32, b'\0')
        i += 2 + n
    return out


def public_der(key):
    """Открытый ключ закрытого ключа key (файл PEM) — DER SubjectPublicKeyInfo."""
    der = run_openssl('pkey', '-in', key, '-pubout', '-outform', 'DER')
    if update.public_point(der) is None:
        raise Stop('ключ %s — не ECDSA P-256' % key)
    return der


def sign(data, key):
    """Подпись байтов data закрытым ключом key: base64 от r‖s — содержимое latest.json.sig."""
    with tempfile.TemporaryDirectory(prefix='poe2runbook-sign-') as tmp:
        src = Path(tmp) / 'latest.json'
        src.write_bytes(data)
        der = run_openssl('dgst', '-sha256', '-sign', key, src)
    return base64.b64encode(der_to_rs(der))


# --- ключ в программе ---------------------------------------------------------------------------------------------

def fingerprint(der):
    return hashlib.sha256(der).hexdigest()


def program_key(planner=PLANNER):
    """Открытый ключ, вписанный в программу (planner/updatekey.py): DER или None."""
    try:
        text = (Path(planner) / KEY_MODULE).read_text(encoding='utf-8')
    except OSError:
        return None
    m = RE_KEY_LINE.search(text)
    return base64.b64decode(m.group(1)) if m else None


def write_key_module(der, planner=PLANNER):
    """planner/updatekey.py с открытым ключом der (переводы строк — LF, как у новых модулей программы)."""
    text = ('# -*- coding: utf-8 -*-\n'
            '# SPDX-License-Identifier: GPL-3.0-only\n'
            '# Copyright © 2026 Sergei Labutin\n'
            '# Additional terms under GPL-3.0 section 7: see NOTICE.md\n'
            '"""Открытый ключ подписи обновлений программы (update.py проверяет им latest.json).\n\n'
            'Этот файл пишет инструмент выпуска: python release/publish.py keygen — он создаёт закрытый ключ автора вне проекта\n'
            '(%USERPROFILE%\\\\.poe2runbook\\\\release-key.pem) и вписывает сюда открытый. Руками не правится.\n'
            'Ключа нет (None) — программа не принимает ни одного файла обновления: проверять подпись нечем.\n'
            '"""\n'
            '# DER SubjectPublicKeyInfo ключа ECDSA P-256, base64; отпечаток — SHA-256 этого DER (сверить ключ глазами)\n'
            "PUBLIC_KEY = '" + base64.b64encode(der).decode('ascii') + "'\n"
            "FINGERPRINT = '" + fingerprint(der) + "'\n")
    path = Path(planner) / KEY_MODULE
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(text.encode('utf-8'))
    os.replace(tmp, path)
    return path


def keygen(key=KEY, planner=PLANNER, replace=False):
    """Ключ автора: создать (если его нет) и вписать открытый ключ в программу. Ответ — (DER, создан ли ключ)."""
    key = Path(key)
    made = False
    if not key.exists():
        key.parent.mkdir(parents=True, exist_ok=True)
        tmp = key.with_name(key.name + '.new')
        if tmp.exists():
            tmp.unlink()
        run_openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', tmp)
        os.rename(tmp, key)          # на Windows не перезапишет ключ, появившийся за это время
        made = True
    der = public_der(key)
    had = program_key(planner)
    if had is not None and had != der and not replace:
        raise Stop('в программе уже вписан ДРУГОЙ ключ (отпечаток %s). Копии, установленные с ним, не примут файлы, '
                   'подписанные этим ключом (%s). Ключ потерян и нужен новый — --replace' % (fingerprint(had), fingerprint(der)))
    write_key_module(der, planner)
    return der, made


# --- файл обновления ----------------------------------------------------------------------------------------------

def file_version(path):
    """Версия файла из его свойств (у установщика Inno Setup — версия программы); не прочесть — None."""
    if sys.platform != 'win32':
        return None
    from ctypes import wintypes as w
    v = ctypes.WinDLL('version')
    v.GetFileVersionInfoSizeW.argtypes, v.GetFileVersionInfoSizeW.restype = [w.LPCWSTR, ctypes.POINTER(w.DWORD)], w.DWORD
    v.GetFileVersionInfoW.argtypes, v.GetFileVersionInfoW.restype = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p], w.BOOL
    v.VerQueryValueW.argtypes = [ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.UINT)]
    v.VerQueryValueW.restype = w.BOOL
    size = v.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not v.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    p, n = ctypes.c_void_p(), w.UINT()
    if not v.VerQueryValueW(buf, '\\', ctypes.byref(p), ctypes.byref(n)) or n.value < 16:
        return None
    ffi = ctypes.cast(p, ctypes.POINTER(ctypes.c_uint32 * 4)).contents      # подпись, версия структуры, MS, LS
    return '%d.%d.%d.%d' % (ffi[2] >> 16, ffi[2] & 0xFFFF, ffi[3] >> 16, ffi[3] & 0xFFFF)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for piece in iter(lambda: f.read(1 << 20), b''):
            h.update(piece)
    return h.hexdigest()


def one_line(text, name):
    """Объявление: одна строка простого текста до 140 знаков — иначе отказ (программа обрезала бы его сама)."""
    if text is None:
        return None
    if update.RE_CONTROL.search(text) or '\n' in text or '\r' in text or '\t' in text:
        raise Stop('%s: объявление — одна строка простого текста, без переводов строк и управляющих знаков' % name)
    text = ' '.join(text.split())
    if not text:
        raise Stop('%s: пустое объявление' % name)
    if len(text) > update.NOTICE_MAX:
        raise Stop('%s: объявление длиннее %d знаков (%d)' % (name, update.NOTICE_MAX, len(text)))
    return text


def site_version(site):
    """Версия, уже записанная в site/update/latest.json; файла нет — None."""
    path = Path(site) / 'latest.json'
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_bytes().decode('utf-8'))
        version = doc['version']
    except (OSError, ValueError, KeyError, TypeError):
        raise Stop('%s не читается — разберитесь с ним руками, прежде чем писать новый' % path) from None
    if update.version_key(version) is None:
        raise Stop('%s: в нём не версия программы (%r)' % (path, version))
    return version


def manifest(installer, url, notes_ru, notes_en, notice_ru=None, notice_en=None, key=KEY, site=SITE, planner=PLANNER,
             day=None):
    """Подписанный файл обновления для установщика installer — в site. url None — выпуск GitHub (RELEASE_URL). Ответ —
    (байты latest.json, поля файла)."""
    installer = Path(installer)
    m = update.RE_SETUP.fullmatch(installer.name)
    if not m or m.group(2) or not installer.is_file():
        raise Stop('установщик — файл вида PoE2Runbook-Setup-<версия>.exe: %s' % installer)
    version = m.group(1)
    if url is None:
        url = RELEASE_URL % {'version': version, 'name': installer.name}
    inside = file_version(installer)
    if inside is not None and inside != version:
        raise Stop('в имени установщика версия %s, а в его свойствах — %s' % (version, inside))
    if update._https(url) is None:
        raise Stop('адрес установщика — только https:// (без пробелов, имени и пароля): %s' % url)
    if urllib_name(url) != installer.name:
        raise Stop('адрес должен кончаться именем установщика %s: %s' % (installer.name, url))
    for name, text in (('--notes-ru', notes_ru), ('--notes-en', notes_en)):
        if not isinstance(text, str) or not text.strip():
            raise Stop('%s: что изменилось — пусто' % name)
        if len(text) > update.NOTES_MAX:
            raise Stop('%s: длиннее %d знаков' % (name, update.NOTES_MAX))
    if (notice_ru is None) != (notice_en is None):
        raise Stop('объявление — на обоих языках сразу: --notice-ru и --notice-en')
    notice_ru, notice_en = one_line(notice_ru, '--notice-ru'), one_line(notice_en, '--notice-en')
    had = site_version(site)
    if had is not None and update.compare(version, had) <= 0:
        raise Stop('версия %s не новее уже записанной %s — программа такую не примет' % (version, had))
    size = installer.stat().st_size
    if not 0 < size <= update.MAX_INSTALLER:
        raise Stop('размер установщика %d — не тот' % size)
    point_der = program_key(planner)
    if point_der is None:
        raise Stop('в программе нет открытого ключа (planner/updatekey.py): сначала keygen')
    signer = public_der(key)
    if signer != point_der:
        raise Stop('ключ %s — не тот, что вписан в программу (отпечатки %s и %s): программа файл не примет'
                   % (key, fingerprint(signer), fingerprint(point_der)))
    doc = {'format': update.FORMAT, 'v': 1, 'version': version, 'game': '%d.%d.%d' % update.version_key(version)[:3],
           'published': day or datetime.date.today().isoformat(),
           'installer': {'url': url, 'size': size, 'sha256': digest(installer)},
           'notes': {'ru': notes_ru.strip(), 'en': notes_en.strip()}}
    if notice_ru is not None:
        doc['notice'] = {'ru': notice_ru, 'en': notice_en}
    data = (json.dumps(doc, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
    sig = sign(data, key)
    try:
        info = update.read_manifest(data, sig, update.public_point(point_der))      # как прочтёт программа
    except update.Refused as e:
        raise Stop('программа этот файл не примет (%s %s) — не записан' % (e.code, e.detail)) from None
    site = Path(site)
    site.mkdir(parents=True, exist_ok=True)
    for name, body in (('latest.json', data), ('latest.json.sig', sig + b'\n')):
        tmp = site / (name + '.tmp')
        tmp.write_bytes(body)
    os.replace(site / 'latest.json.tmp', site / 'latest.json')
    os.replace(site / 'latest.json.sig.tmp', site / 'latest.json.sig')
    return data, info


def urllib_name(url):
    """Имя файла в конце адреса (без параметров)."""
    import urllib.parse
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/', 1)[-1])


def verify_site(site=SITE, planner=PLANNER, dist=DIST):
    """Пара в site — как её проверит программа. Ответ — (поля файла, сверка установщика из dist или None)."""
    site = Path(site)
    try:
        data, sig = (site / 'latest.json').read_bytes(), (site / 'latest.json.sig').read_bytes()
    except OSError as e:
        raise Stop('нет файла: %s' % e) from None
    der = program_key(planner)
    try:
        info = update.read_manifest(data, sig, update.public_point(der) if der else None)
    except update.Refused as e:
        raise Stop('программа этот файл НЕ примет: %s %s' % (e.code, e.detail)) from None
    local = Path(dist) / (update.SETUP_NAME % info['version'])
    same = None
    if local.is_file():
        same = local.stat().st_size == info['size'] and digest(local) == info['sha256']
    return info, same


# --- запуск -------------------------------------------------------------------------------------------------------

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description='Ключ подписи и файл обновления PoE2 Runbook (ничего не отправляет)')
    ap.add_argument('--key', default=str(KEY), help='закрытый ключ автора (PEM)')
    ap.add_argument('--planner', default=str(PLANNER), help='папка программы с updatekey.py')
    ap.add_argument('--site', default=str(SITE), help='куда писать latest.json и latest.json.sig')
    ap.add_argument('--dist', default=str(DIST), help='где лежат установщики (для verify)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    kg = sub.add_parser('keygen', help='создать ключ автора и вписать открытый ключ в программу')
    kg.add_argument('--replace', action='store_true', help='в программе другой ключ — заменить его этим')
    mf = sub.add_parser('manifest', help='подписанный файл обновления для установщика')
    mf.add_argument('installer')
    mf.add_argument('--url', help='https-адрес, по которому установщик будет лежать (по умолчанию — выпуск GitHub '
                                  'v<версия>: %s)' % (RELEASE_URL % {'version': '<версия>', 'name': update.SETUP_NAME % '<версия>'}))
    mf.add_argument('--notes-ru', required=True)
    mf.add_argument('--notes-en', required=True)
    mf.add_argument('--notice-ru')
    mf.add_argument('--notice-en')
    mf.add_argument('--date', help='день выпуска ГГГГ-ММ-ДД (по умолчанию — сегодня)')
    sub.add_parser('verify', help='проверить site/update тем же кодом, что программа')
    args = ap.parse_args(argv)
    try:
        if args.cmd == 'keygen':
            der, made = keygen(args.key, args.planner, args.replace)
            print(('Создан ключ: %s' if made else 'Ключ уже есть, не тронут: %s') % args.key)
            print('Открытый ключ вписан в программу: %s' % (Path(args.planner) / KEY_MODULE))
            print('Отпечаток ключа (SHA-256): %s' % fingerprint(der))
            if made:
                print('СОХРАНИТЕ КОПИЮ ключа вне компьютера (флешка, менеджер паролей): потеряете его — установленные '
                      'копии программы перестанут принимать обновления. Никому его не давайте и в проект не кладите.')
        elif args.cmd == 'manifest':
            if args.date and not update.RE_DAY.fullmatch(args.date):
                raise Stop('--date: ГГГГ-ММ-ДД')
            data, info = manifest(args.installer, args.url, args.notes_ru, args.notes_en, args.notice_ru,
                                  args.notice_en, args.key, args.site, args.planner, args.date)
            print('Записано: %s и latest.json.sig' % (Path(args.site) / 'latest.json'))
            print('Версия %s (игра %s), %s; установщик %d байт, SHA-256 %s'
                  % (info['version'], info['game'], info['published'], info['size'], info['sha256']))
            print('Проверено кодом программы: подпись сходится, файл программа примет')
        else:
            info, same = verify_site(args.site, args.planner, args.dist)
            print('Подпись сходится, программа файл примет: версия %s (игра %s), %s'
                  % (info['version'], info['game'], info['published']))
            print('Установщик: %s — %d байт, SHA-256 %s' % (info['url'], info['size'], info['sha256']))
            for lang in sorted(info['notes']):
                print('Что изменилось [%s]: %s' % (lang, info['notes'][lang]))
            for lang in sorted(info['notice']):
                print('Объявление [%s]: %s' % (lang, info['notice'][lang]))
            if same is not None:
                print('Установщик в %s: %s' % (args.dist, 'размер и SHA-256 сходятся' if same else 'НЕ СХОДИТСЯ с файлом'))
                if not same:
                    return 1
    except Stop as e:
        print('Отказ: %s' % e)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
