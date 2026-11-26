# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Сборка программы для игроков: папка программы (PyInstaller) -> проверка -> установщик (Inno Setup).

Запуск (из папки проекта):
    packaging\\.venv\\Scripts\\python.exe packaging\\build.py [--root <папка исходников>] [--no-installer]

Что получается:
    packaging\\dist\\PoE2Runbook\\       — папка программы (PoE2Runbook.exe + _internal); рядом с exe — LICENSE, NOTICE.md
                                         (из папки исходников) и THIRD-PARTY.md (сторонние компоненты, notices.py)
    dist\\PoE2Runbook-Setup-<версия>.exe — установщик для игроков

Чья программа, видно в свойствах exe и установщика: «Sergei Labutin», «© 2026 Sergei Labutin» (AUTHOR, COPYRIGHT ниже;
в установщике — PoE2Runbook.iss), а в самой программе — окно «О программе» (planner/about.py).

Версия — «версия игры.номер сборки», например 0.5.5.4 (planner/appversion.py): версия игры берётся из каталога данных
(catalog/data/current.txt), номер сборки — BUILD; перед каждой новой сборкой его увеличивают на 1, с новой версией
игры — начинают с 1. Планы, которые идут с программой, — PLANS ниже.
Сторонние компоненты: после PyInstaller notices.py перечисляет, что из чужого кода попало в папку программы, и пишет
THIRD-PARTY.md (название, версия, лицензия, полный текст лицензии) и список для окна «О программе»; компонент без записи
о лицензии — сборка стоит.
Проверка перед установщиком: собранная программа открывает окно (скрыто) на пробном логе в пустой папке данных,
и страница должна показать строку состояния, а окну «О программе» — есть что показать (тексты лицензий рядом с exe,
список компонентов). Настоящие лог, настройки и фильтры игры при этом не читаются.

Нужно один раз: python -m venv packaging\\.venv && packaging\\.venv\\Scripts\\python -m pip install pyinstaller pywebview;
Inno Setup 6 (jrsoftware.org).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PLANS = ['hc-ssf-dov']
AUTHOR = 'Sergei Labutin'
COPYRIGHT = '© 2026 Sergei Labutin'
LEGAL = ['LICENSE', 'NOTICE.md']        # из папки исходников — в папку программы, рядом с exe
ISCC = [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Inno Setup 6' / 'ISCC.exe',
        Path(os.environ.get('ProgramFiles(x86)', '')) / 'Inno Setup 6' / 'ISCC.exe',
        Path(os.environ.get('ProgramFiles', '')) / 'Inno Setup 6' / 'ISCC.exe']

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{author}'),
      StringStruct('FileDescription', 'PoE2 Runbook'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'PoE2Runbook'),
      StringStruct('LegalCopyright', '{copyright}'),
      StringStruct('OriginalFilename', 'PoE2Runbook.exe'),
      StringStruct('ProductName', 'PoE2 Runbook'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def version(root):
    """Версия программы — «версия игры.номер сборки» (planner/appversion.py). Версия игры — из каталога данных, который
    кладётся в программу; счётчик сборок там считается для версии игры GAME: каталог ушёл на новую версию игры —
    сборка останавливается, пока в appversion.py не поправят GAME и не начнут BUILD с 1."""
    sys.path.insert(0, str(root / 'planner'))
    import appversion
    current = (root / 'catalog' / 'data' / 'current.txt').read_text(encoding='utf-8').strip()
    game = appversion.stem(current)
    if not game:
        sys.exit('catalogue version %r is not a game version' % current)
    if game != appversion.GAME:
        sys.exit('the catalogue is for game %s, but planner/appversion.py counts builds for %s: '
                 'set GAME = %r and BUILD = 1 there' % (game, appversion.GAME, game))
    return appversion.program(current)


def catalog_check(root, plan):
    """План в комплекте и каталог одобренных планов (site/plans, его пишет release/plans.py). У игрока план из комплекта
    получает новые версии из каталога, а узнаёт себя в каталоге по байтам своего файла плана: совпал с последней версией
    каталога — «поставлен», не совпал — «есть новая версия» и «Обновить» до версии каталога. Ответ — строка для сборки
    (None — плана в каталоге нет: и сказать нечего)."""
    import hashlib
    import json
    sys.path.insert(0, str(root / 'planner'))
    import planlib
    site = root / 'site' / 'plans'
    try:
        index = json.loads((site / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    try:
        data = planlib.bundle(root / 'plans', plan)
    except (OSError, ValueError) as e:
        return '== WARNING: plan %s cannot be read: %s' % (plan, e)
    sha = hashlib.sha256(planlib.bundle_bytes(data)).hexdigest()
    entry = next((p for p in index.get('plans') or [] if isinstance(p, dict) and p.get('uid') == data['uid']), None)
    if entry is None:
        return None
    latest = entry.get('version')
    if sha == ((entry.get('file') or {}).get('sha256') or '').lower():
        return '== plan %s = catalogue version %s' % (plan, latest)
    for f in sorted((site / data['uid']).glob('*.plan')):
        if hashlib.sha256(f.read_bytes()).hexdigest() == sha:
            return ('== plan %s = catalogue version %s (the catalogue has %s: players get it as an update)'
                    % (plan, f.stem, latest))
    return ('== WARNING: plan %s matches no approved version of the catalogue (it has version %s): players of this build '
            'will be offered version %s as an update. Approve this plan first: '
            'python -X utf8 release/plans.py add <its plan file> --author ... --changed-ru ... --changed-en ...'
            % (plan, latest, latest))


def selftest(app):
    """Собранная программа: окно (скрыто) на пробном логе, пустая папка данных — страница сказала статус."""
    tmp = Path(tempfile.mkdtemp(prefix='runbook-selftest-'))
    try:
        log = tmp / 'game' / 'logs' / 'Client.txt'
        log.parent.mkdir(parents=True)
        log.write_text('2026/01/01 10:00:00 1 a [DEBUG Client 1] Generating level 1 area "G1_1" with seed 1\n',
                       encoding='utf-8')
        (tmp / 'filters').mkdir()
        (tmp / 'config.ini').write_text('language=en\n', encoding='utf-8')
        cmd = [str(app / 'PoE2Runbook.exe'), '--selftest', '--data', str(tmp / 'data'), '--log', str(log), '--no-clip',
               '--config', str(tmp / 'config.ini'), '--filters', str(tmp / 'filters')]
        code = subprocess.run(cmd, timeout=240).returncode
        print((tmp / 'data' / 'program.log').read_text(encoding='utf-8', errors='replace'))
        if code != 0:
            sys.exit('selftest failed: exit code %d' % code)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=str(PROJECT), help='папка исходников (planner, catalog, knowledge, plans)')
    ap.add_argument('--no-installer', action='store_true')
    args = ap.parse_args()
    root = Path(args.root).resolve()
    ver = version(root)
    t = ', '.join((ver.split('.') + ['0', '0', '0', '0'])[:4])
    (HERE / 'build').mkdir(exist_ok=True)
    (HERE / 'build' / 'version_info.txt').write_text(VERSION_INFO.format(v=ver, t=t, author=AUTHOR, copyright=COPYRIGHT),
                                                     encoding='utf-8')
    for p in PLANS:
        if not (root / 'plans' / p / 'plan.json').is_file():
            sys.exit('no plan %s in %s' % (p, root / 'plans'))
        said = catalog_check(root, p)
        if said:
            print(said, flush=True)
    for name in LEGAL:
        if not (root / name).is_file():
            sys.exit('no %s in %s' % (name, root))
    # ключ подписи обновлений (planner/updatekey.py, его вписывает release/publish.py keygen): без него собранная программа
    # не примет ни одного файла обновления — установленные копии придётся обновлять руками
    if "PUBLIC_KEY = '" not in (root / 'planner' / 'updatekey.py').read_text(encoding='utf-8'):
        print('== WARNING: no update signing key in planner/updatekey.py — this build will accept no updates '
              '(run: python -X utf8 release/publish.py keygen)', flush=True)
    iscc = None
    if not args.no_installer:
        iscc = next((p for p in ISCC if p.is_file()), None)
        if not iscc:
            sys.exit('Inno Setup 6 (ISCC.exe) not found')
    print('== PyInstaller: %s, version %s' % (root, ver), flush=True)
    env = dict(os.environ, RUNBOOK_ROOT=str(root), RUNBOOK_PLANS=','.join(PLANS))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
                    '--distpath', str(HERE / 'dist'), '--workpath', str(HERE / 'build' / 'work'),
                    str(HERE / 'PoE2Runbook.spec')], env=env, check=True)
    app = HERE / 'dist' / 'PoE2Runbook'
    # лицензия программы и условия автора — рядом с exe; сторонние компоненты — THIRD-PARTY.md и список для окна
    # «О программе» (notices.py: компонент без записи о лицензии — сборка стоит)
    for name in LEGAL:
        shutil.copyfile(root / name, app / name)
    subprocess.run([sys.executable, str(HERE / 'notices.py'), '--app', str(app), '--root', str(root), '--program', ver]
                   + (['--inno', str(iscc)] if iscc else []), check=True)
    size = sum(f.stat().st_size for f in app.rglob('*') if f.is_file())
    print('== app folder: %s (%.1f MB)' % (app, size / 1e6), flush=True)
    print('== selftest', flush=True)
    selftest(app)
    if args.no_installer:
        return
    out = PROJECT / 'dist'
    print('== Inno Setup', flush=True)
    subprocess.run([str(iscc), '/Q', '/DAppVersion=' + ver, '/DSourceDir=' + str(app), '/DOutDir=' + str(out),
                    str(HERE / 'PoE2Runbook.iss')], check=True)
    setup = out / ('PoE2Runbook-Setup-%s.exe' % ver)
    print('== installer: %s (%.1f MB)' % (setup, setup.stat().st_size / 1e6))


if __name__ == '__main__':
    main()
