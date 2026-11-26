# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""О программе: чья она, под какой лицензией и где настоящая — для окна «О программе» (обе страницы, окно «Настройки»).

Зачем. Программа с интерфейсом по GPL (раздел 5(d)) показывает «Appropriate Legal Notices»: копирайт; что гарантий нет;
что программу можно распространять на условиях лицензии; где прочитать лицензию. Изменённая версия обязана показывать их
там же, где их показывает оригинал, и сохранять там строку об авторе (условия автора по разделу 7(b) — NOTICE.md). Имя
на экземпляре — ещё и законная презумпция авторства (Директива ЕС 2004/48/EC, ст. 5).

Что здесь:
  * NAME, AUTHOR, YEAR, SITE, ATTRIBUTION — кто и где; имя автора и строка об авторе не переводятся;
  * тексты LICENSE, NOTICE.md, THIRD-PARTY.md — из папки программы: у собранной программы — рядом с PoE2Runbook.exe
    (их кладёт туда packaging/build.py), у программы из исходников — папка проекта; другие имена не отдаются;
  * сторонние компоненты — список, который при сборке составил packaging/notices.py (third-party.json рядом с модулями,
    у собранной программы — в _internal). У программы из исходников списка нет: чужие пакеты ставил себе сам
    запустивший, и окно этот раздел не показывает.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

NAME = 'PoE2 Runbook'
AUTHOR = 'Sergei Labutin'
YEAR = 2026
SITE = 'https://poe2.labutin.gg'          # единственный официальный адрес: сайт и официальные сборки
ATTRIBUTION = 'Based on PoE2 Runbook by Sergei Labutin — https://poe2.labutin.gg'   # NOTICE.md, условие 1
LEGAL = ('LICENSE', 'NOTICE.md', 'THIRD-PARTY.md')
COMPONENTS = 'third-party.json'
FORMAT = 'poe2-runbook-third-party'
MAX_TEXT = 4 * 1024 * 1024


def program_dir():
    """Папка программы: у собранной — где PoE2Runbook.exe (модули лежат в её _internal), у исходников — папка проекта."""
    return HERE.parent


def legal_text(name, root=None):
    """Текст файла LICENSE / NOTICE.md / THIRD-PARTY.md из папки программы; другое имя или файла нет — None."""
    if name not in LEGAL:
        return None
    try:
        with open(Path(root or program_dir()) / name, 'rb') as f:
            data = f.read(MAX_TEXT)
    except OSError:
        return None
    return data.decode('utf-8', errors='replace')


def _row(x):
    """Строка списка компонентов, как её записал notices.py; не такая — None."""
    if not isinstance(x, dict) or not all(isinstance(x.get(k), str) for k in ('name', 'version', 'licence')):
        return None
    return {'name': x['name'][:80], 'version': x['version'][:40], 'licence': x['licence'][:80]}


def components(here=None):
    """Сторонние компоненты сборки: [{name, version, licence, parts: [...]}]; списка нет или он испорчен — None."""
    try:
        data = json.loads((Path(here or HERE) / COMPONENTS).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('format') != FORMAT or not isinstance(data.get('components'), list):
        return None
    out = []
    for c in data['components']:
        row = _row(c)
        if row is None:
            return None
        parts = [_row(p) for p in c.get('parts') or []]
        if any(p is None for p in parts):
            return None
        row['parts'] = parts
        out.append(row)
    return out or None


def view(program, game, root=None, here=None):
    """Что показывает окно «О программе». program — версия программы, game — версия игры, под которую она сделана;
    files — какие из LICENSE / NOTICE.md / THIRD-PARTY.md лежат в папке программы."""
    root = Path(root or program_dir())
    return {'name': NAME, 'version': program or '', 'game': game or '', 'author': AUTHOR, 'year': YEAR, 'site': SITE,
            'attribution': ATTRIBUTION, 'files': [n for n in LEGAL if (root / n).is_file()],
            'components': components(here)}
