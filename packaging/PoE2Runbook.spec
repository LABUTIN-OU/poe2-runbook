# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
# Папка программы PoE2Runbook (PyInstaller): окно (planner/desktop.py), сервер страниц и его модули, страницы, языки,
# данные игры текущей версии, справочник и планы, которые идут с программой. Ничего от этого компьютера: ни героев
# (runs), ни архива фильтров, ни резервных копий.
# Собирать через packaging/build.py: он передаёт RUNBOOK_ROOT (папка исходников) и RUNBOOK_PLANS (планы в комплекте).
# После PyInstaller build.py кладёт рядом с exe LICENSE, NOTICE.md и THIRD-PARTY.md, а в _internal — third-party.json
# (notices.py); свойства exe (издатель, копирайт) — build/version_info.txt, его пишет build.py.
import os
from pathlib import Path

HERE = Path(SPECPATH)
ROOT = Path(os.environ.get('RUNBOOK_ROOT') or HERE.parent)
PLANS = [p for p in (os.environ.get('RUNBOOK_PLANS') or '').split(',') if p]
CURRENT = (ROOT / 'catalog' / 'data' / 'current.txt').read_text(encoding='utf-8').strip()

datas = [
    (str(ROOT / 'planner' / 'static'), 'static'),
    (str(ROOT / 'planner' / 'lang'), 'lang'),
    (str(ROOT / 'catalog' / 'data' / CURRENT), 'catalog/data/' + CURRENT),
    (str(ROOT / 'catalog' / 'data' / 'current.txt'), 'catalog/data'),
    (str(ROOT / 'knowledge'), 'knowledge'),
] + [(str(ROOT / 'plans' / p), 'plans/' + p) for p in PLANS]

a = Analysis(
    [str(ROOT / 'planner' / 'desktop.py')],
    pathex=[str(ROOT / 'planner')],
    datas=datas,
    hiddenimports=['server', 'overlay'],
    excludes=['tkinter', '_tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PoE2Runbook',
    console=False,
    upx=False,
    icon=str(HERE / 'app.ico'),
    version=str(HERE / 'build' / 'version_info.txt'),
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name='PoE2Runbook')
