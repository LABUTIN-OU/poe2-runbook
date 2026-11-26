# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Картинки из данных игры для страниц: скачивает недостающие в planner/static/icons.

Что скачивается — говорит каталог (catalog/build.py), а не план: автор может выбрать любую базу и любой камень,
поэтому картинки берутся все сразу, один раз на версию игры.
  * базы снаряжения — плитки слотов: у базы в каталоге её рисунок (art — путь в данных игры) и имя файла
    картинки (icon: art-…);
  * камни умений и камни поддержки — плитки умений: у камня так же art и icon (skill-… / sup-…; у рангов одного
    камня поддержки картинка общая);
  * уникальные предметы — у каждого свой рисунок, не рисунок базы (uniq-…): карточка скопированного предмета и
    плитка слота, где он надет.
Картинки отдаёт CDN сайта poe2db: https://cdn.poe2db.tw/image/<art>.webp (рисунки умений лежат там под путём
строчными буквами). Скачивается только то, чего в папке ещё нет, готовый файл не перезаписывается; файл
принимается, только если это действительно WebP разумного размера. Запрос несёт общее имя клиента и ничего
о пользователе.

Скачивать — только с согласия владельца проекта: на все классы снаряжения он дал его 2026-11-15, на все камни
умений и поддержки — 2026-11-18 («один раз выкачать все что нужно и обновлять по мере выхода новых версий игры»),
на все уникальные предметы — 2026-11-23.

Запуск: python -I catalog/fetch_icons.py [--kinds bases,gems,uniques] [--classes "Ring,Boots"] [--dry]
После патча игры: сначала пересобрать каталог (catalog/build.py), затем этот скрипт — он докачает новое.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CDN = 'https://cdn.poe2db.tw/image/'
MAX_BYTES = 400_000
KINDS = ('bases', 'gems', 'uniques')
KIND_WORDS = {'bases': 'снаряжение', 'gems': 'камни', 'uniques': 'уникальные'}


def wanted(bases, classes=None):
    """Что нужно: имя файла картинки -> рисунок, по базам каталога (классы — все или названные)."""
    out = {}
    for b in bases.values():
        if b.get('icon') and b.get('art') and (not classes or b['class'] in classes):
            out.setdefault(b['icon'], b['art'])
    return out


def wanted_gems(gems):
    """То же по камням умений и поддержки. Одно имя картинки у нескольких камней (ранги камня поддержки, удар
    оружием в одной и в двух руках) — берётся рисунок первого."""
    out = {}
    for g in gems.values():
        if g.get('icon') and g.get('art'):
            out.setdefault(g['icon'], g['art'])
    return out


def wanted_uniques(uniques, classes=None):
    """То же по уникальным предметам каталога (классы — все или названные). Один рисунок у двух имён — одна картинка."""
    out = {}
    for u in (uniques or {}).values():
        if u.get('icon') and u.get('art') and (not classes or u.get('class') in classes):
            out.setdefault(u['icon'], u['art'])
    return out


def addresses(art, lower=False):
    """Адреса картинки по порядку попыток. Рисунки умений CDN хранит под путём строчными буквами (lower),
    рисунки баз — как в данных игры; второй вариант — запасной."""
    paths = [art.lower(), art] if lower else [art, art.lower()]
    # в пути рисунка бывает пробел («Uniques/The Auspex») — в адресе он экранируется
    return [CDN + urllib.parse.quote(p, safe='/') + '.webp' for p in dict.fromkeys(paths)]


def fetch(art, lower=False):
    """Байты картинки или причина отказа: (bytes | None, текст)."""
    why = 'нет адреса'
    for url in addresses(art, lower):
        req = urllib.request.Request(url, headers={'User-Agent': 'generic-reader/1.0', 'Accept': 'image/webp'})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            why = '%s' % e
            if e.code == 404:
                continue            # под этим написанием пути картинки нет — пробуем другое
            return None, why
        except (urllib.error.URLError, OSError) as e:
            return None, '%s' % e
        if len(raw) > MAX_BYTES:
            return None, 'слишком большой файл'
        if not (raw[:4] == b'RIFF' and raw[8:12] == b'WEBP'):
            return None, 'это не WebP'
        return raw, 'ok'
    return None, why


def main():
    ap = argparse.ArgumentParser(description='Картинки баз снаряжения и камней')
    ap.add_argument('--catalog', default=str(HERE / 'data'))
    ap.add_argument('--out', default=str(HERE.parent / 'planner' / 'static' / 'icons'))
    ap.add_argument('--kinds', default=','.join(KINDS),
                    help='что скачивать: bases (снаряжение), gems (камни), uniques (уникальные); через запятую')
    ap.add_argument('--classes', help='только эти классы вещей, через запятую (как в каталоге: Ring, Boots)')
    ap.add_argument('--dry', action='store_true', help='ничего не скачивать, только сказать, чего не хватает')
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    kinds = [k.strip() for k in args.kinds.split(',') if k.strip()]
    if any(k not in KINDS for k in kinds):
        ap.error('--kinds: только %s' % ', '.join(KINDS))
    root = Path(args.catalog)
    version = (root / 'current.txt').read_text(encoding='utf-8').strip()
    load = lambda name: json.loads((root / version / name).read_text(encoding='utf-8'))      # noqa: E731
    classes = {c.strip() for c in args.classes.split(',')} if args.classes else None
    out = Path(args.out)
    todo = []            # (имя файла, рисунок, путь строчными?)
    for kind in kinds:
        if kind == 'bases':
            need = wanted(load('bases.json'), classes)
        elif kind == 'uniques':
            # часть каталога появилась позже остальных: в папке постарше её нет
            need = wanted_uniques(load('uniques.json') if (root / version / 'uniques.json').is_file() else {}, classes)
        else:
            need = wanted_gems(load('gems.json'))
        missing = {name: art for name, art in sorted(need.items()) if not (out / (name + '.webp')).is_file()}
        print('%s — картинок по каталогу: %d, уже есть: %d, не хватает: %d' % (
            KIND_WORDS[kind], len(need), len(need) - len(missing), len(missing)))
        todo += [(name, art, kind == 'gems') for name, art in missing.items()]
    if args.dry or not todo:
        return 0
    out.mkdir(parents=True, exist_ok=True)
    got = size = 0
    failed = []
    for n, (name, art, lower) in enumerate(todo, 1):
        raw, why = fetch(art, lower)
        if raw is None:
            failed.append('%s (%s): %s' % (name, art, why))
        elif (out / (name + '.webp')).exists():
            failed.append('%s: файл появился, пока шла загрузка, — не перезаписан' % name)
        else:
            (out / (name + '.webp')).write_bytes(raw)
            got += 1
            size += len(raw)
        if n % 50 == 0:
            print('  %d из %d' % (n, len(todo)), flush=True)
        time.sleep(0.15)       # не торопимся: сервер чужой
    print('скачано: %d (%.1f МБ), не получено: %d' % (got, size / 1e6, len(failed)))
    for line in failed:
        print('  нет:', line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
