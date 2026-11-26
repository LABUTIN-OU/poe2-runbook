# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Таблицы игры на всех языках клиента — из выгрузки pathofexile-dat в источники каталога.

Реплики NPC и боссов, системные строки лога («… достигает N уровня», «… был повержен»), названия зон и
монстров лежат в таблицах самой игры, у каждой строки — один код на всех языках. Открытые выгрузки
(repoe-fork) дают только английский, поэтому таблицы берутся программой pathofexile-dat (npm, SnosMe/
poe-dat-viewer, MIT) прямо с сервера обновлений GGG (patch-poe2.poecdn.com) — установленная игра не
читается. Один раз на версию игры:

  1. Во временную папку: Node.js (nodejs.org) и `npm install pathofexile-dat --ignore-scripts`.
  2. В пустой папке config.json: {"patch": "<версия>", "tables": <tables>, "files": <files>} — оба списка из
     catalog/extra/dat-export.json.
  3. Там же: node <…>/pathofexile-dat/dist/cli/run.js — появятся tables/<Language>/<Table>.json и files/.
  4. python -I -X utf8 catalog/dat_pack.py <папка выгрузки> catalog/sources/<версия> <версия> <откуда>
  5. python -I -X utf8 catalog/build.py --sources catalog/sources --out catalog/data

Файлы игры (files — описания свойств: из них игра пишет строки наград в логе и строки «что даёт узел» дерева,
planner/treegeo.py) кладутся как есть, сжатыми:
<источники>/dat/<имя>.gz. Таблицы — <источники>/dat/<Table>.json.gz:
  {"table", "patch", "rows", "columns": {столбец: [значения по строкам] — если на всех языках одинаков,
                                          или {язык: [значения]} — если различается}}
и дописывает их в SOURCE.txt (размер, SHA-256, откуда). Языки — коды en, ru, de, fr, es, pt, ja, ko, th,
zh-Hant. Таблицы нет на языке — программа выгрузки молча подставляет английскую: такой язык здесь
отбрасывается (у него все тексты совпали бы с английскими).
"""
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

LANGS = {'English': 'en', 'Russian': 'ru', 'German': 'de', 'French': 'fr', 'Spanish': 'es',
         'Portuguese': 'pt', 'Japanese': 'ja', 'Korean': 'ko', 'Thai': 'th', 'Traditional Chinese': 'zh-Hant'}


def pack_table(name, by_lang, columns):
    """by_lang: {код языка: [строки выгрузки]} -> словарь файла. Столбец, одинаковый на всех языках, — один раз."""
    en = by_lang['en']
    n = len(en)
    for code, rows in by_lang.items():
        if len(rows) != n:
            raise ValueError('%s: на языке %s строк %d, на английском %d' % (name, code, len(rows), n))
    out = {}
    for col in columns:
        vals = {code: [r.get(col) for r in rows] for code, rows in by_lang.items()}
        same = all(v == vals['en'] for v in vals.values())
        out[col] = vals['en'] if same else vals
    return {'table': name, 'rows': n, 'columns': out}


def text_columns(packed):
    return [c for c, v in packed['columns'].items() if isinstance(v, dict)]


def main(argv):
    if len(argv) != 5:
        print(__doc__)
        return 2
    src, dst, patch, origin = Path(argv[1]), Path(argv[2]), argv[3], argv[4]
    spec = json.loads((Path(__file__).resolve().parent / 'extra' / 'dat-export.json').read_text(encoding='utf-8'))
    (dst / 'dat').mkdir(parents=True, exist_ok=True)
    # папка выгрузки: в ней tables/<Language>/ и files/ (как их кладёт pathofexile-dat); прежний вызов — сама папка tables
    tables = src / 'tables' if (src / 'tables').is_dir() else src
    notes = []
    for name in spec.get('files') or []:
        # файл игры как есть (описания свойств — текст UTF-16 со всеми языками), сжатым
        f = src / 'files' / Path(name).name
        if not f.is_file():
            print('%-20s нет в выгрузке — пропущен' % Path(name).name)
            continue
        body = gzip.compress(f.read_bytes(), mtime=0)
        out = 'dat/%s.gz' % Path(name).name
        (dst / out).write_bytes(body)
        notes.append('%s\n    %s, файл %s, %d байт без сжатия\n    %d байт, SHA-256 %s' % (
            out, origin, name, f.stat().st_size, len(body), hashlib.sha256(body).hexdigest()))
        print('%-20s %9d байт -> %7d байт' % (Path(name).name, f.stat().st_size, len(body)))
    for t in spec['tables']:
        by_lang = {}
        for folder, code in LANGS.items():
            f = tables / folder / (t['name'] + '.json')
            if f.is_file():
                by_lang[code] = json.loads(f.read_text(encoding='utf-8'))
        if 'en' not in by_lang:
            print('%-20s нет в выгрузке — пропущена' % t['name'])
            continue
        packed = pack_table(t['name'], by_lang, t['columns'])
        # язык, где все тексты совпали с английскими, — подстановка программы выгрузки, а не перевод
        for col in text_columns(packed):
            for code in list(packed['columns'][col]):
                if code != 'en' and packed['columns'][col][code] == packed['columns'][col]['en']:
                    del packed['columns'][col][code]
                    notes.append('%s.%s: на языке %s таблицы нет' % (t['name'], col, code))
        packed['patch'] = patch
        body = gzip.compress(json.dumps(packed, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), mtime=0)
        name = 'dat/%s.json.gz' % t['name']
        (dst / name).write_bytes(body)
        notes.append('%s\n    %s, таблица %s (%s), %d строк\n    %d байт, SHA-256 %s' % (
            name, origin, t['name'], ', '.join(t['columns']), packed['rows'], len(body), hashlib.sha256(body).hexdigest()))
        print('%-20s строк %6d  %7d байт  языки: %s' % (t['name'], packed['rows'], len(body), ', '.join(
            sorted({c for v in packed['columns'].values() if isinstance(v, dict) for c in v}) or ['—'])))
    with (dst / 'SOURCE.txt').open('a', encoding='utf-8') as fh:
        fh.write('\nТаблицы игры на языках клиента (catalog/dat_pack.py), %s:\n\n' % time.strftime('%Y-%m-%d %H:%M'))
        fh.write('\n'.join(notes) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
