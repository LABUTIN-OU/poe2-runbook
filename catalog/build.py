# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Каталог данных игры: из открытых выгрузок — в компактные файлы на идентификаторах игры.

Зачем. План, редактор, сравнение вещей и будущие помощники (крафт) должны брать факты игры из одного
места, а не из строк, записанных руками. Ключи в каталоге — идентификаторы самой игры (код зоны
`G1_4`, семейство аффикса `IncreasedLife`, свойство `base_maximum_life`), слова на языке игрока лежат
отдельным слоем. После патча каталог пересобирается этим же скриптом.

Откуда данные:
  * repoe-fork/poe2 — выгрузка таблиц игры (английская): зоны, базы предметов, аффиксы, уникальные предметы;
  * Exiled Exchange 2 — названия баз и тексты свойств на языках игры (ru, en, …), имена уникальных предметов;
  * таблицы самой игры на всех 10 языках клиента (папка dat/ в источниках; как их получить — catalog/dat_pack.py):
    реплики NPC и боссов, системные строки лога, названия зон.

Что получается (каждая часть — обычный словарь, сохраняется как JSON):
  areas   — зоны: код -> название, акт, уровень, город, точка перехода, соседние зоны, боссы;
  bases   — базы снаряжения: id -> название, класс, метки, уровень, требования;
  uniques — уникальные предметы: английское имя -> класс, свой рисунок, базы (имя на языке клиента — в слое языка);
  mods    — аффиксы по семействам: префикс или суффикс, свойства, ступени (уровень предмета, числа,
            на каких метках баз бывает);
  waystones — путевые камни: тир -> уровень зоны и сила аффиксов; аффиксы камней по семействам, с тем,
            чем игра платит за каждый;
  craft   — крафт: веса свойств по классам предметов (их в файлах игры нет — выжимка страниц poe2db,
            которую в папку источников кладут отдельно и с разрешения пользователя) и правила валюты;
  lang    — слой языка: название базы и текст свойства с # вместо чисел, названия зон (areas);
  log     — что игра пишет в лог, по языкам клиента (log-<язык>.json.gz): реплики по кодам строк, имена NPC,
            системные строки (уровень героя, смерть, награда, очки умений) и тексты свойств (stat: коды свойств ->
            шаблоны) — по ним строка награды находит, какое свойство дала игра;
  names   — названия из игры на её языках по английскому названию (names-<язык>.json.gz): предметы, монстры,
            NPC, задания, зоны, узлы дерева — так страница на этом языке показывает пары «Русское (English)» плана,
            а русская страница — узлы деревьев и названия, которые план записал не по-русски.

Запуск: python -I catalog/build.py [--fetch] [--sources ПАПКА] [--out ПАПКА] [--lang ru en]
  --fetch    скачать исходные файлы в ПАПКА/<версия данных игры>/ (рядом ложится SOURCE.txt: откуда,
             размер, контрольная сумма) и запомнить эту версию в ПАПКА/current.txt;
  --sources  откуда читать исходные файлы; без неё они читаются из сети в память и на диск не кладутся;
  --out      куда записать каталог: ПАПКА/<версия>/ и ПАПКА/current.txt; без неё печатается только сводка.
После патча игры: python -I catalog/build.py --fetch --sources catalog/sources --out catalog/data
В папке источников лежат только скачанные файлы: скрипты туда не кладутся и оттуда не запускаются.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# вопросы к готовому каталогу (бывает ли аффикс на базе, его ступени) — те же, что у плеера
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'planner'))
from gamedata import fits, tiers  # noqa: E402,F401

REPOE ='https://raw.githubusercontent.com/repoe-fork/poe2/master/'
REPOE_SITE = 'https://repoe-fork.github.io/poe2/'     # та же выгрузка, как она выложена сайтом
EE2 = 'https://raw.githubusercontent.com/Kvan7/Exiled-Exchange-2/master/renderer/public/data/'
# имя файла в папке источников -> откуда он берётся
SOURCES = {
    'version.txt': REPOE + 'version.txt',
    'world_areas.json': REPOE + 'data/world_areas.json',
    'base_items.json': REPOE + 'data/base_items.json',
    'mods.json': REPOE + 'data/mods.json',
    'stat_descriptions.json': REPOE + 'data/stat_translations/stat_descriptions.json',
    'skill_gems.json': REPOE + 'data/skill_gems.json',
    # умения камней: резерв духа по уровням камня (у камня — spirit; на странице забега — «нужно N духа»)
    'skills.json': REPOE + 'data/skills.json',
    'augments.json': REPOE + 'data/augments.json',
    # таблица классов предметов: как игра называет класс («Shield» -> «Shields») — так его пишут фильтры
    'item_classes.json': REPOE + 'data/item_classes.json',
    # дерево атласа (основное и по механикам): из него planner/atlasgeo.py собирает карту для страницы.
    # Сжатый файл лежит только на сайте выгрузки, в самом хранилище его нет.
    'Atlas.min.json': REPOE_SITE + 'passive_skill_trees/Atlas.min.json',
    # уникальные предметы игры: английское имя, класс и рисунок (у каждого свой, не рисунок базы)
    'uniques.json': REPOE + 'data/uniques.json',
}
LANG_FILES = ('items.ndjson', 'stats.ndjson')
# Имена уникальных предметов на языках клиента — таблицы предметов Exiled Exchange 2 (у ru и en они и так берутся
# с LANG_FILES): язык каталога -> папка этого языка у Exiled Exchange 2. Тайского там нет — тайский клиент пишет
# имена уникальных по-английски (сверено по poe2db th).
UNIQUE_LANGS = {'de': 'de', 'fr': 'fr', 'es': 'es', 'pt': 'pt', 'ja': 'ja', 'ko': 'ko', 'zh-Hant': 'cmn-Hant'}
# Снаряжение в данных игры — всё из раздела item; служебные заготовки в каталог не идут.
# (По меткам его не отобрать: у скипетров, жезлов и посохов нет общей метки «оружие».)
SKIP_CLASSES = {'HiddenItem'}


def download(url):
    """Содержимое файла из сети. Запрос несёт только общее имя программы."""
    req = urllib.request.Request(url, headers={'User-Agent': 'generic-reader/1.0'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def read_source(name, url, folder=None):
    """Текст исходного файла: из папки, если он там есть, иначе из сети (в память)."""
    if folder:
        path = Path(folder) / name
        if path.is_file():
            return path.read_text(encoding='utf-8')
    return download(url).decode('utf-8')


def source_files(langs):
    """Все исходные файлы: имя в папке источников -> адрес."""
    files = dict(SOURCES)
    for lang in langs:
        for name in LANG_FILES:
            files['%s-%s' % (lang, name)] = EE2 + lang + '/' + name
    for lang, folder in UNIQUE_LANGS.items():
        files.setdefault('%s-items.ndjson' % lang, EE2 + folder + '/items.ndjson')
    return files


def current(root):
    """Папка текущей версии внутри общей папки (её имя записано в current.txt); если такой записи нет —
    сама папка: значит, файлы лежат прямо в ней."""
    root = Path(root)
    try:
        name = (root / 'current.txt').read_text(encoding='utf-8').strip()
    except OSError:
        return root
    return root / name if name and (root / name).is_dir() else root


def fetch(root, langs):
    """Скачивает исходные файлы в root/<версия данных игры>/ и записывает рядом, что откуда взято."""
    files = source_files(langs)
    version = download(files['version.txt']).decode('utf-8').strip()
    if not re.fullmatch(r'[0-9A-Za-z._-]{1,40}', version):
        raise ValueError('странная версия данных: %r' % version[:60])
    dest = Path(root) / version
    dest.mkdir(parents=True, exist_ok=True)
    rows = ['Исходные данные игры для каталога (catalog/build.py). Версия %s, скачано %s.' % (
        version, time.strftime('%Y-%m-%d %H:%M')), '']
    for name, url in files.items():
        data = download(url)
        (dest / name).write_bytes(data)
        rows.append('%s\n    %s\n    %d байт, SHA-256 %s' % (name, url, len(data), hashlib.sha256(data).hexdigest()))
        print('скачано: %-26s %9d байт' % (name, len(data)), flush=True)
    (dest / 'SOURCE.txt').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    (Path(root) / 'current.txt').write_text(version + '\n', encoding='utf-8')
    return dest


def fetch_missing(root, langs):
    """Докачивает в папку текущей версии исходные файлы, которых в ней ещё нет: так добавляют новый
    источник, не скачивая заново остальные. Версия данных в сети должна совпадать с версией папки —
    иначе новый файл оказался бы от другого патча; тогда нужна полная загрузка (--fetch)."""
    folder = current(root)
    files = source_files(langs)
    have = (folder / 'version.txt').read_text(encoding='utf-8').strip()
    remote = download(files['version.txt']).decode('utf-8').strip()
    if remote != have:
        raise ValueError('в сети данные версии %s, в папке — %s: докачивать по одному файлу нельзя' % (remote[:40], have))
    rows = []
    for name, url in files.items():
        if (folder / name).is_file():
            continue
        data = download(url)
        (folder / name).write_bytes(data)
        rows.append('%s\n    %s\n    %d байт, SHA-256 %s' % (name, url, len(data), hashlib.sha256(data).hexdigest()))
        print('скачано: %-26s %9d байт' % (name, len(data)), flush=True)
    if rows:
        with open(folder / 'SOURCE.txt', 'a', encoding='utf-8') as f:
            f.write('\nДокачано %s (та же версия %s):\n\n%s\n' % (time.strftime('%Y-%m-%d %H:%M'), have, '\n'.join(rows)))
    else:
        print('докачивать нечего: все исходные файлы на месте', flush=True)
    return folder


def build_areas(world):
    """Зоны по коду — тому же, что в логе игры («Generating level 4 area "G1_4"»)."""
    out = {}
    for code, a in world.items():
        if not a.get('name') or a.get('name') == 'NULL':
            continue
        out[code] = {
            'name': a['name'], 'act': a.get('act'), 'level': a.get('area_level'),
            'town': bool(a.get('is_town')), 'waypoint': bool(a.get('has_waypoint')),
            'parent': a.get('parent_town'),
            'links': [c for c in a.get('connections') or [] if c in world],
            # босс — последним словом пути его описания в данных игры
            'bosses': [b.rsplit('/', 1)[-1] for b in a.get('bosses') or []],
        }
    return out


# свойства базы, которые печатаются на вещи числом: имя в данных игры -> имя в каталоге
BASE_PROPS = (('armour', 'armour'), ('evasion', 'evasion'), ('energy_shield', 'energy_shield'), ('block', 'block'))


def gear_base(b):
    """База снаряжения, которая идёт в каталог (из раздела item, выпущена, не служебная заготовка)."""
    return b.get('domain') == 'item' and b.get('release_state') != 'unreleased' and b.get('item_class') not in SKIP_CLASSES


RE_SLUG = re.compile(r'[^a-z0-9]+')


def art_names(items):
    """Рисунок базы (путь в данных игры без расширения) -> имя файла её картинки: «art-» и последнее
    слово пути строчными (Art/2DItems/Armours/Helmets/Basetypes/HelmetInt08 -> art-helmetint08).
    Одинаковое последнее слово у разных рисунков — тогда вместе с папкой."""
    slug = lambda s: RE_SLUG.sub('-', s.lower()).strip('-')
    stems = sorted({((b.get('visual_identity') or {}).get('dds_file') or '').rsplit('.', 1)[0]
                    for b in items.values() if gear_base(b)} - {''})
    short = {}
    for stem in stems:
        short.setdefault(slug(stem.rsplit('/', 1)[-1]), []).append(stem)
    out = {}
    for name, same in short.items():
        for stem in same:
            out[stem] = 'art-' + (name if len(same) == 1 else slug('-'.join(stem.split('/')[-2:])))
    return out


def build_bases(items):
    """Базы снаряжения. id — путь базы в данных игры без общего начала.

    Кроме названия, класса, меток и требований: props — свойства базы числом (броня, уклонение,
    энергощит, блок; у базы с разбросом берётся нижнее значение), speed — штраф скорости передвижения
    в процентах (тяжёлый доспех), implicits — id собственных свойств (сами свойства — часть implicits),
    art — рисунок базы (путь в данных игры) и icon — имя файла её картинки (см. catalog/fetch_icons.py),
    grants — ключи камней умений, которые база даёт сама.
    Этих полей нет у базы, у которой нет самих свойств.
    """
    out = {}
    icons = art_names(items)
    for path, b in items.items():
        tags = b.get('tags') or []
        if not gear_base(b):
            continue
        req = b.get('requirements') or {}
        base = {
            'name': b.get('name'), 'class': b.get('item_class'), 'tags': tags, 'level': b.get('drop_level'),
            'req': {k: v for k, v in (('level', req.get('level')), ('str', req.get('strength')),
                                      ('dex', req.get('dexterity')), ('int', req.get('intelligence'))) if v},
        }
        raw = b.get('properties') or {}
        props = {name: raw[key]['min'] for key, name in BASE_PROPS
                 if isinstance(raw.get(key), dict) and raw[key].get('min')}
        if props:
            base['props'] = props
        if raw.get('movement_speed'):
            # Штраф скорости базы, в процентах базовой скорости героя: в данных −500 = −5% (poe2db пишет
            # то же числом «Base Movement Speed: -0.05»). Есть у нательных доспехов (сила −5, гибрид
            # с силой −4, прочие −3) и щитов (сила −3, гибрид −1,5; у баклеров и фокусов нет). На самой
            # вещи не написан. Умножается на прибавки скорости, а не складывается с ними.
            base['speed'] = raw['movement_speed'] / 100
        if b.get('implicits'):
            base['implicits'] = list(b['implicits'])
        if b.get('skills_granted'):
            # умения, которые база даёт сама (скипетр — приспешника, щит — «Поднять щит»): ключи камней —
            # последнее слово пути, как камень назван в gems
            base['grants'] = [str(s).rsplit('/', 1)[-1] for s in b['skills_granted']]
        art = ((b.get('visual_identity') or {}).get('dds_file') or '').rsplit('.', 1)[0]
        if art:
            base['art'], base['icon'] = art, icons[art]
        out[path.replace('Metadata/Items/', '', 1)] = base
    return out


RE_ICON_ART = re.compile(r'/gen/image/([A-Za-z0-9_=-]+)/')


def ee2_art(icon):
    """Рисунок предмета из адреса картинки Exiled Exchange 2: в адресе — base64 с путём рисунка
    («2DItems/Belts/Uniques/MeginordsGirdle») -> путь, как в данных игры («Art/2DItems/…»). Нет — None."""
    m = RE_ICON_ART.search(icon or '')
    if not m:
        return None
    raw = m.group(1) + '=' * (-len(m.group(1)) % 4)
    try:
        import base64
        spec = json.loads(base64.urlsafe_b64decode(raw).decode('utf-8'))
        f = spec[2]['f'] if isinstance(spec, list) and len(spec) > 2 and isinstance(spec[2], dict) else None
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    return ('Art/' + f) if isinstance(f, str) and f else None


def build_uniques(table, items_by_lang):
    """Уникальные предметы и их имена на языках клиента: (uniques, {язык: {имя на языке: английское имя или список
    английских имён, когда на этом языке их у двух уникальных одно}}).

    uniques — по английскому имени (как его пишет игра сейчас — таблица repoe-fork): class — класс предмета,
    art — рисунок (путь в данных игры), icon — имя файла картинки (uniq-… — catalog/fetch_icons.py), bases —
    английские названия баз, на которых он бывает (Exiled Exchange 2). У нескольких вариантов одного имени
    (самоцвет на трёх камнях, скипетр трёх стихий) рисунок берётся первого: какой вариант в руках, по копии не узнать.
    Имена на языках — из таблиц предметов Exiled Exchange 2; их английское имя бывает старым (уникальный переименован
    в игре) — тогда запись находится по одному рисунку с таблицей игры."""
    slug = lambda s: RE_SLUG.sub('-', s.lower()).strip('-')
    out, by_art = {}, {}
    for key in sorted(table, key=lambda k: int(k) if str(k).isdigit() else 0):
        u = table[key]
        name = u.get('name')
        art = ((u.get('visual_identity') or {}).get('dds_file') or '').rsplit('.', 1)[0]
        if not name or not art or name in out or u.get('is_alternate_art'):
            continue
        out[name] = {'class': u.get('item_class'), 'art': art, 'bases': []}
        by_art.setdefault(art.lower(), name)
    # имя файла картинки: «uniq-» и последнее слово пути рисунка; одинаковое слово у разных рисунков — весь путь после
    # Art/2DItems (папка рисунка уникального всегда «Uniques» — по ней не различить); один и тот же рисунок у двух имён —
    # одна картинка
    short = {}
    for name, u in out.items():
        short.setdefault(slug(u['art'].rsplit('/', 1)[-1]), set()).add(u['art'])
    for name, u in out.items():
        word = slug(u['art'].rsplit('/', 1)[-1])
        u['icon'] = 'uniq-' + (word if len(short[word]) == 1 else slug('-'.join(u['art'].split('/')[2:])))
    langs = {}
    for lang, text in items_by_lang.items():
        names = {}
        for line in (text or '').split('\n'):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get('namespace') != 'UNIQUE' or not row.get('refName') or not row.get('name'):
                continue
            en = row['refName'] if row['refName'] in out else by_art.get((ee2_art(row.get('icon')) or '').lower())
            if not en:
                continue                     # предмета нет в данных игры этой версии (убран или не выпущен)
            base = (row.get('unique') or {}).get('base')
            if lang == 'en' and base and base not in out[en]['bases']:
                out[en]['bases'].append(base)
            local = plain_name(row['name'])
            have = names.get(local)
            if have is None:
                names[local] = en
            elif en not in ([have] if isinstance(have, str) else have):
                # одно имя у двух уникальных на этом языке (по-немецки «Atziris Verachtung» — и Atziri's Disdain,
                # и Atziri's Contempt): список, различает их база из копии
                names[local] = ([have] if isinstance(have, str) else have) + [en]
        if lang != 'en':
            langs[lang] = names
    return out, langs


def stat_index(texts):
    """Свойство игры -> ключи строк текста, в которые оно входит."""
    by_stat = {}
    for key in texts:
        for s in key.split():
            by_stat.setdefault(s, []).append(key)
    return by_stat


def build_implicits(items, mods, texts):
    """Собственные свойства баз снаряжения: id свойства -> stats, vals (по паре «от — до» на свойство)
    и lines — ключи строк слоя языка (None — у свойства нет текста)."""
    by_stat = stat_index(texts)
    out = {}
    for b in items.values():
        if not gear_base(b):
            continue
        for mid in b.get('implicits') or []:
            m = mods.get(mid)
            if m and mid not in out:
                ids = [s['id'] for s in m.get('stats') or []]
                out[mid] = {'stats': ids, 'vals': [[s.get('min'), s.get('max')] for s in m.get('stats') or []],
                            'lines': text_lines(ids, texts, by_stat)}
    return out


RE_NUMBER = re.compile(r'\d+(?:\.\d+)?')


def build_augments(augments, items, texts):
    """Руны, ядра душ и прочее, что вставляют в гнёзда. id — последнее слово пути в данных игры.

    name — английское имя, type — род (Rune, SoulCore, Idol …), level — с какого уровня героя можно
    вставить, on — что вставка даёт на вещи каждой категории (категории — как в игре: Armour, Martial
    Weapon, Wand or Staff, Sceptre, Helmet …; какая вещь к какой относится — gamedata.augment_fits):
    stats — свойства, vals — их числа из текста (None, если чисел в тексте не столько же, сколько
    свойств), lines — ключи строк слоя языка. Категория, где вставка ничего не даёт, не записывается.
    """
    by_stat = stat_index(texts)
    out = {}
    for path, a in augments.items():
        on = {}
        for cat_name, body in (a.get('categories') or {}).items():
            ids = [s['id'] for s in body.get('stats') or []]
            if not ids:
                continue
            nums = [float(n) for n in RE_NUMBER.findall(RE_MARKUP.sub(r'\1', ' '.join(body.get('stat_text') or [])))]
            on[cat_name] = {'stats': ids, 'vals': [int(n) if n == int(n) else n for n in nums] if len(nums) == len(ids) else None,
                            'lines': text_lines(ids, texts, by_stat)}
        if on:
            out[path.rsplit('/', 1)[-1]] = {'name': (items.get(path) or {}).get('name'), 'type': a.get('type_id'),
                                           'level': a.get('required_level') or 0, 'on': on}
    return out


def build_stats(table, texts):
    """Статы героя, из которых складывается билд (здоровье, сопротивления, дух …): своя таблица
    catalog/extra/stats.json, сверенная с данными игры.

    У стата: ids — свойства игры, которые в него складываются со всего снаряжения; local — свойства,
    которые меняют саму вещь (броня доспеха, дух скипетра): на вещи они уже учтены в её свойстве prop
    («Броня: 358»), поэтому в сумму идёт prop, а не они; cap — предел, выше которого стат бесполезен.
    Свойство, которого в данных игры нет (переименовано патчем), из стата убирается и попадает
    в список missing — сборка о нём сообщает.
    """
    known = set(stat_index(texts))
    stats, missing = {}, []
    for sid, s in (table.get('stats') or {}).items():
        clean = dict(s)
        for field in ('ids', 'local'):
            good = [i for i in s.get(field) or [] if i in known]
            missing += ['%s: %s' % (sid, i) for i in s.get(field) or [] if i not in known]
            clean[field] = good
        stats[sid] = clean
    return {'stats': stats, 'order': [s for s in table.get('order') or [] if s in stats], 'missing': missing}


ATTRS = (('str', 'strength'), ('dex', 'dexterity'), ('int', 'intelligence'))
RE_RANK = re.compile(r'\s+[IVX]+$')      # ранг камня поддержки в конце имени: «Heft II»


def gem_icon(name, kind):
    """Имя файла картинки камня: у умения — «skill-» и английское имя строчными через дефисы (skill-frost-bomb),
    у камня поддержки — «sup-» и имя без ранга (sup-heft): у рангов одного камня картинка общая. По этому же
    правилу страница забега ищет картинку по названию умения или камня поддержки в плане."""
    stem = RE_SLUG.sub('-', (RE_RANK.sub('', name) if kind == 'support' else name).lower()).strip('-')
    return ('sup-' if kind == 'support' else 'skill-') + stem if stem else None


SERVICE_GEMS = ('Removed Skill', 'Coming Soon')      # заготовки без настоящего камня (и всё, что начинается с «[»)


def gem_spirit(names, skills):
    """Резерв духа камня по уровням: [на 1-м уровне, на 2-м, …] — у первого из его умений (names), которое
    резервирует дух (skills — skills.json). Резерв без уровней — список из одного числа: он один на всех
    уровнях. Дух камень не резервирует — None."""
    for name in names or ():
        rec = (skills or {}).get(name) or {}
        per = {}
        for lv, v in (rec.get('per_level') or {}).items():
            n = ((v or {}).get('reservations') or {}).get('spirit') if isinstance(v, dict) else None
            if str(lv).isdigit() and isinstance(n, (int, float)) and not isinstance(n, bool):
                per[int(lv)] = n
        if per:
            out, last = [], per[min(per)]
            for lv in range(1, max(per) + 1):
                last = per.get(lv, last)
                out.append(last)
            return out
        flat = (((rec.get('static') or {}).get('reservations')) or {}).get('spirit')
        if isinstance(flat, (int, float)) and not isinstance(flat, bool) and flat:
            return [flat]
    return None


def build_gems(gems, items=None, skills=None):
    """Камни умений и поддержки. id — последнее слово пути камня в данных игры (SkillGemSkeletalSniper).

    У камня: name — английское имя, type — active / support (и редкие другие), level — с какого уровня
    неогранённого камня его можно огранить, req — доли требований по характеристикам (100 — целиком
    интеллект), tags — метки игры, skills — умения, которые он даёт; art — рисунок камня (путь в данных игры
    без расширения) и icon — имя файла его картинки (gem_icon). Рисунок — значок умения; у камня без него
    (камни поддержки происхождения) — рисунок самого камня-предмета из items (base_items.json). Картинки нет
    у камня без всякого рисунка в данных игры и у служебных записей («[DNT] …», «Removed Skill», «Coming Soon»).
    spirit — резерв духа по уровням камня (gem_spirit, из skills — skills.json); ascendancy — камень восхождения:
    его не огранить, умение даёт восхождение, гнёзда поддержки у него открываются с уровнем героя.
    """
    out = {}
    for path, g in gems.items():
        base = g.get('base_item') or {}
        if not base.get('display_name') or base.get('release_state') == 'unreleased':
            continue
        key = path.rsplit('/', 1)[-1]
        if key in out:
            key = path.replace('Metadata/Items/', '', 1)     # одно слово у двух камней: тогда путь целиком
        weights = g.get('requirement_weights') or {}
        out[key] = {'name': base['display_name'], 'type': g.get('gem_type'), 'color': g.get('color'),
                    'level': g.get('crafting_level'),
                    'req': {short: weights[full] for short, full in ATTRS if weights.get(full)},
                    'tags': g.get('tags') or [], 'skills': g.get('grants_skills') or []}
        spirit = gem_spirit(g.get('grants_skills'), skills)
        if spirit:
            out[key]['spirit'] = spirit
        if key.startswith('SkillGemAscendancy'):
            out[key]['ascendancy'] = True
        service = base['display_name'].startswith('[') or base['display_name'] in SERVICE_GEMS
        icon = gem_icon(base['display_name'], g.get('gem_type'))
        # значок умения, а нет его — рисунок самого камня-предмета
        own = (((items or {}).get(path) or {}).get('visual_identity') or {}).get('dds_file')
        for dds in (g.get('icon_dds_file'), own):
            art, _, ext = (dds or '').rpartition('.')
            if ext.lower() == 'dds' and art.rsplit('/', 1)[-1] and icon and not service:
                out[key]['art'], out[key]['icon'] = art, icon
                break
    return out


RE_UNCUT = re.compile(r'^Uncut (Skill|Support|Spirit) Gem \(Level (\d+)\)$')


def build_rules(items, extra=None):
    """Правила игры, которые не список вещей. Сейчас — неогранённые камни.

    uncut: род камня (skill / support / spirit) -> уровень камня -> уровень зоны, с которого он падает.
    Камень умения, выпавший в зоне, — всегда самого высокого уровня из тех, что в ней уже падают: в зоне
    40 это 10-й (с 37), а 9-й там уже не найти. Камень поддержки годится на любую поддержку не выше
    своего уровня. Остальное (extra — catalog/extra/game.json) ведётся руками, с указанием источника:
    уровень героя и характеристики для камня уровня N, уровни камней на картах.
    """
    uncut = {}
    for path, b in items.items():
        m = RE_UNCUT.match(b.get('name') or '')
        if m and 'Quest' not in path:
            uncut.setdefault(m.group(1).lower(), {})[m.group(2)] = b.get('drop_level')
    out = {'uncut': uncut}
    out.update(extra or {})
    return out


RE_MARKUP = re.compile(r'\[(?:[^\]|]*\|)?([^\]]*)\]')


def shape(text):
    """Текст свойства в общем виде: числа — знаком #, без разметки игры ([Fire|Fire] -> Fire) и без
    плюса перед числом: «+# к максимуму здоровья» и «# к максимуму здоровья» — одно и то же."""
    return RE_MARKUP.sub(r'\1', text or '').replace('+#', '#').strip()


RE_FMT = re.compile(r'\+?#%?')


def build_stat_texts(table, formats=None):
    """Тексты свойств из таблицы игры: «id id2» (свойства одной строки текста) -> её написания
    по-английски. Одна строка может нести два свойства («Adds # to # Fire Damage» — минимум и максимум),
    и один и тот же текст бывает у разных свойств (броня на поясе и броня на доспехе).
    В formats (если дан словарь) кладётся вид первого числа строки: «+#», «#%», «+#%» или «#» — по нему
    ступень подписывают так же, как она написана на вещи."""
    out = {}
    for e in table:
        ids = e.get('ids') or []
        shapes, first = [], None
        for v in e.get('English') or []:
            s = v.get('string') or ''
            for i, fmt in enumerate(v.get('format') or []):
                s = s.replace('{%d}' % i, fmt if '#' in fmt else '#')
            s = RE_MARKUP.sub(r'\1', s).strip()
            if first is None:
                m = RE_FMT.search(s)
                first = m.group(0) if m else '#'
            s = shape(s)
            if s and s not in shapes:
                shapes.append(s)
        if ids and shapes:
            out[' '.join(ids)] = shapes
            if formats is not None:
                formats[' '.join(ids)] = first or '#'
    return out


def text_lines(stats, texts, by_stat):
    """На какие строки текста ложатся свойства аффикса: список ключей таблицы текстов. Гибрид — две
    строки, пара «минимум и максимум» — одна."""
    lines, done = [], set()
    for s in stats:
        if s in done:
            continue
        # строка, в которую входит это свойство и все свойства которой есть у аффикса; из таких — самая полная
        fit = [k for k in by_stat.get(s, []) if set(k.split()) <= set(stats)]
        if not fit:
            return None                   # у свойства нет текста: аффикс на вещи не показывается строкой
        key = max(fit, key=lambda k: len(k.split()))
        lines.append(key)
        done.update(key.split())
    return lines


def build_mods(mods, texts, formats=None):
    """Аффиксы вещей по семействам. Семейство — аффиксы одного рода разной силы («здоровье»).

    У семейства: gen — префикс или суффикс, stats — свойства, lines — на какие строки текста они ложатся
    (ключи слоя языка), fmt — вид числа каждой строки («+#», «#%»). У ступени: id аффикса в игре, его имя, уровень предмета, с которого он бывает,
    числа свойств (по одной паре «от — до» на свойство) и on — метки баз с весом: аффикс бывает на базе,
    если у первой из этих меток, которая есть у базы, вес больше нуля.
    """
    by_stat = {}
    for key in texts:
        for s in key.split():
            by_stat.setdefault(s, []).append(key)
    fams = {}
    for mid, m in mods.items():
        if m.get('domain') != 'item' or m.get('generation_type') not in ('prefix', 'suffix') or m.get('is_essence_only'):
            continue
        on = [[w['tag'], w['weight']] for w in m.get('spawn_weights') or []]
        if not any(w for _, w in on):
            continue                      # сам по себе не выпадает нигде
        stats = [s['id'] for s in m.get('stats') or []]
        # одно имя семейства игра даёт и разным наборам свойств (на оружии и на украшениях):
        # ключ — имя, место и свойства вместе
        key = '%s|%s|%s' % (m.get('type'), m['generation_type'], ' '.join(stats))
        if key not in fams:
            lines = text_lines(stats, texts, by_stat)
            fams[key] = {'type': m.get('type'), 'gen': m['generation_type'], 'stats': stats, 'lines': lines,
                         'fmt': [(formats or {}).get(k, '#') for k in lines or []], 'mods': []}
        fam = fams[key]
        fam['mods'].append({'id': mid, 'name': m.get('name'), 'level': m.get('required_level'),
                            'vals': [[s.get('min'), s.get('max')] for s in m.get('stats') or []], 'on': on})
    for fam in fams.values():
        fam['mods'].sort(key=lambda x: (x['level'], x['vals']))
    return fams


RE_WAYSTONE = re.compile(r'^Waystone \(Tier (\d+)\)$')
MAP_AREA = 64                 # уровень зоны карты — 64 + тир путевого камня (тир 1 — зона 65, тир 16 — 80)
# Чем игра платит за аффикс путевого камня: свойства без текста, их сумма печатается над аффиксами.
WAY_PAY = {
    'map_map_item_drop_chance_+%_final_from_map': 'drop',            # шанс выпадения путевого камня
    'map_item_drop_rarity_+%_final_from_map': 'rarity',              # редкость предметов
    'map_pack_size_+%_final_from_map': 'pack',                       # размер групп монстров
    'map_number_of_magic_and_rare_packs_+%_final_and_rare_monster_modifiers_chance_+%_final_from_map': 'monsters',
    'map_monster_potency_+%_final_from_map': 'power',                # эффективность монстров
}


def build_waystones(items, mods, texts, formats=None):
    """Путевые камни: тиры и аффиксы по семействам.

    tiers: тир -> name (английское имя базы), area (уровень зоны карты) и band — метка силы аффиксов:
    у камня тира 1–5 они слабые (map_key_low), дальше map_key_medium, map_key_high, map_key_highest.
    mods: семейство (имя в игре: MapPlayerMaximumResists) -> gen, stats — свойства, видимые строкой,
    lines — ключи их строк в слое языка, fmt — вид числа, pay — чем игра платит за аффикс (drop — шанс
    путевого камня — и одно из rarity, pack, monsters, power), bands — числа видимых свойств для каждой
    метки силы; у аффикса одной силы на все тиры (проклятие) метка — any.
    """
    by_stat = {}
    for key in texts:
        for s in key.split():
            by_stat.setdefault(s, []).append(key)
    tiers = {}
    for b in items.values():
        m = RE_WAYSTONE.match(b.get('name') or '')
        band = next((t for t in b.get('tags') or [] if t.startswith('map_key_')), None)
        if m and band and b.get('domain') == 'area':
            tiers[m.group(1)] = {'name': b['name'], 'area': MAP_AREA + int(m.group(1)), 'band': band}
    fams = {}
    for m in mods.values():
        if m.get('domain') != 'area' or m.get('generation_type') not in ('prefix', 'suffix'):
            continue
        on = [w['tag'] for w in m.get('spawn_weights') or [] if w['weight']]
        if not on:
            continue                      # сам по себе на камне не появляется
        ids = [s['id'] for s in m.get('stats') or []]
        # видимые свойства — те, у которых есть строка текста; остальные — плата или служебные
        lines, seen = [], []
        for s in ids:
            if s in seen:
                continue
            fit = [k for k in by_stat.get(s, []) if set(k.split()) <= set(ids)]
            if fit:
                key = max(fit, key=lambda k: len(k.split()))
                lines.append(key)
                seen.extend(key.split())
        fam = fams.setdefault(m.get('type'), {
            'gen': m['generation_type'], 'stats': seen, 'lines': lines,
            'fmt': [(formats or {}).get(k, '#') for k in lines],
            'pay': {WAY_PAY[s['id']]: s.get('min') for s in m.get('stats') or [] if s['id'] in WAY_PAY},
            'bands': {}})
        vals = {s['id']: [s.get('min'), s.get('max')] for s in m.get('stats') or []}
        band = next((t for t in on if t.startswith('map_key_')), 'any')
        fam['bands'][band] = [vals[s] for s in fam['stats'] if s in vals]
    return {'tiers': tiers, 'mods': fams}


def build_lang(items_text, stats_text, texts):
    """Слой языка: название базы по её английскому имени и написания строки свойства (с # вместо чисел)
    по ключу таблицы текстов. Таблицы Exiled Exchange 2 связывают язык с английским написанием, а
    английское написание со свойствами игры связывает таблица текстов самой игры (texts)."""
    bases, gems, local, negated, granted = {}, {}, {}, set(), []
    for line in items_text.split('\n'):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('refName') and row.get('name'):
            if row.get('namespace') == 'ITEM':
                bases[row['refName']] = row['name']
            elif row.get('namespace') == 'GEM':
                gems[row['refName']] = row['name']
    for line in stats_text.split('\n'):
        if not line.strip():
            continue
        row = json.loads(line)
        ref = shape(row.get('ref'))
        if row.get('ref') == ANOINT_REF:
            granted = row.get('matchers') or []
        for m in row.get('matchers') or []:
            if m.get('string') and shape(m['string']) not in local.setdefault(ref, []):
                local[ref].append(shape(m['string']))
            if m.get('string') and m.get('negate'):
                negated.add(shape(m['string']))
    stats, less = {}, {}
    for key, shapes in texts.items():
        found = [s for en in shapes for s in local.get(en, [])]
        if found:
            stats[key] = found
            # написания «наоборот» («#% снижение скорости…»): число в такой строке идёт со знаком минус
            minus = [s for s in found if s in negated]
            if minus:
                less[key] = minus
    return {'bases': bases, 'gems': gems, 'stats': stats, 'less': less, 'anoint': build_anoint(granted)}


# Строка предмета, которая даёт узел дерева (зачарование амулета жидкими эмоциями, «Allocates Dominion»):
# в таблице Exiled Exchange 2 у неё по написанию на каждый узел, число — номер узла в данных игры (skill).
ANOINT_REF = 'Allocates #'


def build_anoint(matchers):
    """Узел дерева по строке предмета на этом языке: {line: «Активирует {0}», nodes: {номер узла: название}}.
    Начало и конец строки — общие у всех написаний (по-русски «Активирует »); между ними — название узла."""
    rows = [(m['value'], m['string']) for m in matchers
            if isinstance(m, dict) and isinstance(m.get('value'), int) and isinstance(m.get('string'), str)]
    if not rows:
        return {}
    texts = [s for _, s in rows]
    head = os.path.commonprefix(texts)
    head = head[:head.rfind(' ') + 1] if ' ' in head else ''
    tail = os.path.commonprefix([s[::-1] for s in texts])[::-1]
    tail = tail[tail.find(' '):] if ' ' in tail else ''
    cut = lambda s: s[len(head):len(s) - len(tail)].strip()
    return {'line': head + '{0}' + tail, 'nodes': {str(v): cut(s) for v, s in rows if cut(s)}}


RE_EMOTION = re.compile(r'/(?:Endgame)?DistilledEmotion\d+$')


def build_emotions(items):
    """Жидкие эмоции (Liquid Emotions, ими зачаровывают амулет): английское название -> уровень зоны, с которого
    эмоция падает (drop_level данных игры). Узнаются по id предмета: …/DistilledEmotionN, …/EndgameDistilledEmotionN."""
    return {b['name']: b.get('drop_level') or 1 for k, b in items.items()
            if isinstance(b, dict) and b.get('name') and RE_EMOTION.search(k)}


def build_class_names(classes, bases):
    """Класс предмета -> его название в таблице классов игры («Shield» -> «Shields»): так класс пишут фильтры
    предметов (условие Class) и так его называет английский клиент. Только классы, базы которых есть в каталоге."""
    mine = {b.get('class') for b in bases.values()}
    return {cid: rec['name'].strip() for cid, rec in sorted(classes.items())
            if cid in mine and isinstance(rec, dict) and isinstance(rec.get('name'), str) and rec['name'].strip()}


CRAFT_DIR = 'poe2db'      # выжимка страниц классов poe2db в папке источников
CRAFT_PARTS = ('normal', 'essence', 'perfect_essence', 'desecrated')
RE_HASH = re.compile(r'[0-9a-f]{32,}')


def read_digest(folder):
    """Выжимка страниц классов poe2db из папки источников: {имя страницы: запись}. Этот скрипт её не качает:
    страницы сохраняют отдельно и только с разрешения пользователя (рядом лежит SOURCE.txt с адресами и
    лицензией). Папки нет — пусто: части каталога о крафте тогда не будет."""
    out = {}
    root = Path(folder) / CRAFT_DIR if folder else None
    if root is not None and root.is_dir():
        for path in sorted(root.glob('*.json')):
            try:
                page = json.loads(path.read_text(encoding='utf-8'))
            except ValueError:
                continue
            if isinstance(page, dict) and isinstance(page.get('class'), str):
                out[path.stem] = page
    return out


def build_craft(pages, mods, texts, formats=None, rules=None, names=()):
    """Крафт: что и с каким весом выпадает на предмете класса, и правила валюты.

    pages — имя страницы -> class (класс предмета в данных игры), attr (род доспеха страницы: «int»,
    «str_int»; у класса с одной страницей — None) и списки свойств:
      normal — обычные: id свойства в игре, lvl — уровень свойства (с такого уровня предмета оно бывает),
               side — P (префикс) или S (суффикс), w — вес (оценка poe2db), fams — группы: два свойства
               одной группы на предмете вместе не бывают;
      essence, perfect_essence — свойства сущностей: то же без веса и essence (название сущности),
               removes (сущность сначала убирает свойство), alloy (сплав);
      desecrated — очернённые свойства «владык»: то же без веса и lord, name.
    У каждого свойства st — его свойства в игре с числами [[id, от, до]], lines и fmt — на какие строки
    текста они ложатся и вид числа (как у семейств части mods); text — текст poe2db там, где строк нет.
    Свойство, у которого poe2db дал хэш вместо id игры, находится по имени, уровню и стороне.
    rules — правила валюты (catalog/extra/craft.json), как записаны. notes — что не сошлось с данными игры.
    names — английские названия предметов игры: по ним сверяются названия валюты и сущностей."""
    by_stat, by_name = {}, {}
    for key in texts:
        for s in key.split():
            by_stat.setdefault(s, []).append(key)
    for mid, m in mods.items():
        if m.get('domain') in ('item', 'desecrated') and m.get('generation_type') in ('prefix', 'suffix'):
            by_name.setdefault((m.get('name'), m.get('required_level'), m['generation_type'][0].upper()), []).append(mid)
    names, notes, out = set(names), [], {}
    lost = moved = 0
    for slug, page in sorted(pages.items()):
        rec = {'class': page['class'], 'attr': (page.get('attr') or '').lower() or None}
        for part in CRAFT_PARTS:
            rows = []
            for r in page.get(part) or []:
                if not isinstance(r, dict) or r.get('side') not in ('P', 'S') or not isinstance(r.get('lvl'), int):
                    continue
                mid = r.get('id')
                if mid not in mods:
                    cands = by_name.get((r.get('name'), r['lvl'], r['side'])) or []
                    fams = set(r.get('fams') or ())
                    near = [c for c in cands if not fams or fams & set(mods[c].get('groups') or ())]
                    cands = near or cands
                    if len(cands) == 1:
                        mid, moved = cands[0], moved + 1
                    else:
                        lost += 1
                        if not isinstance(mid, str) or RE_HASH.fullmatch(mid):
                            mid = 'poe2db:%s' % str(mid)[:12]
                game = mods.get(mid) or {}
                st = [[s['id'], s.get('min'), s.get('max')] for s in game.get('stats') or []]
                lines = text_lines([s[0] for s in st], texts, by_stat) or []
                one = {'id': mid, 'lvl': r['lvl'], 'side': r['side'], 'fams': [f for f in r.get('fams') or [] if isinstance(f, str)],
                       'st': st, 'lines': lines, 'fmt': [(formats or {}).get(k, '#') for k in lines]}
                if not lines and r.get('text'):
                    one['text'] = r['text']
                if part == 'normal':
                    one['w'] = r['w'] if isinstance(r.get('w'), (int, float)) and r['w'] > 0 else 0
                elif part == 'desecrated':
                    one['lord'], one['name'] = r.get('lord'), r.get('name')
                else:
                    one['essence'] = r.get('essence')
                    one['removes'], one['alloy'] = bool(r.get('removes')), bool(r.get('alloy'))
                    if names and r.get('essence') not in names:
                        notes.append('сущности «%s» нет в таблице предметов игры' % r.get('essence'))
                rows.append(one)
            rec[part] = rows
        out[slug] = rec
    if lost:
        notes.append('свойств, которых нет в данных игры: %d (их вес учтён, что они дают — неизвестно)' % lost)
    rules = dict(rules or {})

    def check(x):
        if isinstance(x, str):
            if names and x not in names:
                notes.append('в правилах крафта предмет «%s», которого нет в таблице предметов игры' % x)
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ('classes',):
                    check(v)
        elif isinstance(x, list):
            for v in x:
                check(v)
    for key in ('grades', 'bones', 'omens', 'items'):
        check(rules.get(key))
    return {'pages': out, 'rules': rules, 'notes': sorted(set(notes)), 'matched': moved}


# Системные строки лога из таблицы игры BackendErrors: по ним разбирается лог клиента на любом языке.
LOG_MSG = ('LevelUp', 'PlayerSlain', 'ReceivedStatBonusWithName', 'ReceivedStatBonus', 'ReceivedPassivePoint1',
           'ReceivedPassivePointN', 'ReceivedWeaponSpecialisationPoint1', 'ReceivedWeaponSpecialisationPointN')


def read_dat(folder, table):
    """Таблица игры из источников (catalog/dat_pack.py): {"rows", "columns"}; нет файла — None."""
    if not folder:
        return None
    path = Path(folder) / 'dat' / (table + '.json.gz')
    if not path.is_file():
        return None
    import gzip
    return json.loads(gzip.decompress(path.read_bytes()).decode('utf-8'))


def dat_column(tab, col, lang):
    """Столбец таблицы на языке: общий для всех языков — как есть; языка нет — None."""
    v = tab['columns'][col]
    return v.get(lang) if isinstance(v, dict) else v


def build_log_text(folder):
    """Тексты, которые игра пишет в лог, по языкам клиента: {язык: {npc, say, msg}}.

    npc — имя NPC по номеру строки таблицы NPCs (так говорящий подписан в логе);
    say — реплики: код строки -> [текст, номера NPC, которые её говорят] (только строки с текстом);
    msg — системные строки лога (LOG_MSG): код -> шаблон с {0}, {1}…
    Код строки один на всех языках: по нему план ждёт реплику, на каком бы языке ни шёл клиент."""
    audio, npcs, backend = read_dat(folder, 'NPCTextAudio'), read_dat(folder, 'NPCs'), read_dat(folder, 'BackendErrors')
    if not (audio and npcs and backend):
        return {}
    langs = sorted(set(audio['columns']['Text']) & set(npcs['columns']['Name']) & set(backend['columns']['Text']))
    ids, who = audio['columns']['Id'], audio['columns']['NPCs']
    out = {}
    for lang in langs:
        texts, names = audio['columns']['Text'][lang], npcs['columns']['Name'][lang]
        say = {}
        for lid, text, rows in zip(ids, texts, who):
            if lid and text:
                say[lid] = [text] + list(rows or [])
        msg = {k: t for k, t in zip(backend['columns']['Id'], backend['columns']['Text'][lang]) if k in LOG_MSG and t}
        out[lang] = {'npc': [n or '' for n in names], 'say': say, 'msg': msg}
    return out


# Языки в файле описаний свойств игры -> коды языков каталога (английский — без пометки lang; упрощённого
# китайского у клиента, который читает программа, нет).
CSD_LANGS = {'Russian': 'ru', 'German': 'de', 'French': 'fr', 'Spanish': 'es', 'Portuguese': 'pt', 'Japanese': 'ja',
             'Korean': 'ko', 'Thai': 'th', 'Traditional Chinese': 'zh-Hant'}
RE_CSD_MARK = re.compile(r'\[(?:[^\]|]*\|)?([^\]]*)\]')


def parse_csd(text, negated=None):
    """Описания свойств игры (stat_descriptions.csd): [(коды свойств, {язык: [шаблоны]})]. В negated (если дан
    словарь) кладётся {язык: {коды: [шаблоны с обработчиком negate]}} — «#% уменьшение …»: число в такой строке
    идёт со знаком минус.

    Блок: строка description, строка «N код1 … кодN», число вариантов и сами варианты — условия на значения,
    шаблон в кавычках ({0:+d}% к сопротивлению [Resistances|холоду]) и обработчики; дальше то же для каждого
    lang "…". Разметка [Ключ|слово] снимается до слова — так текст видно в игре и в логе."""
    out, cur, lang = [], None, None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('description') and i + 1 < len(lines):
            head = lines[i + 1].split()
            n = int(head[0]) if head and head[0].isdigit() else 0
            cur, lang = (tuple(head[1:1 + n]), {}), 'en'
            out.append(cur)
            i += 2
            continue
        if cur is not None and line.startswith('lang '):
            lang = CSD_LANGS.get(line[5:].strip().strip('"'))
            i += 1
            continue
        if cur is not None and line.isdigit():
            count = int(line)
            for v in lines[i + 1:i + 1 + count]:
                a, b = v.find('"'), v.rfind('"')
                if lang and 0 <= a < b:
                    t = RE_CSD_MARK.sub(r'\1', v[a + 1:b])
                    if t not in cur[1].setdefault(lang, []):
                        cur[1][lang].append(t)
                    if negated is not None and 'negate' in v[b + 1:].split():
                        neg = negated.setdefault(lang, {}).setdefault(' '.join(cur[0]), [])
                        if t not in neg:
                            neg.append(t)
            i += 1 + count
            continue
        i += 1
    return out


def build_stat_lines(folder):
    """Шаблоны текстов свойств по языкам: {язык: {коды свойств через пробел: [шаблоны]}} из описаний свойств игры
    (dat/stat_descriptions.csd.gz). По ним строка награды в логе («+10% к сопротивлению холоду») находит коды
    свойств на любом языке клиента; нет файла — {}."""
    if not folder:
        return {}
    path = Path(folder) / 'dat' / 'stat_descriptions.csd.gz'
    if not path.is_file():
        return {}
    import gzip
    out = {}
    for ids, by_lang in parse_csd(gzip.decompress(path.read_bytes()).decode('utf-16')):
        if not ids:
            continue
        key = ' '.join(ids)
        for lang, temps in by_lang.items():
            out.setdefault(lang, {})[key] = temps
    return out


# Подписи копии предмета (Ctrl+C) в таблице строк игры ClientStrings: поле слоя -> код строки
COPY_STRINGS = {
    'class': 'ItemDisplayStringClass', 'rarity': 'ItemDisplayStringRarity', 'ilvl': 'ItemDisplayStringItemLevel',
    'unidentified': 'ItemPopupUnidentified', 'corrupted': 'ItemPopupCorrupted', 'twice': 'ItemPopupDoubleCorrupted',
    'cannot': 'ItemPopupCannotUseItem', 'unscalable': 'DescriptionLabelFixedValueStat',
    'prefix': 'ModDescriptionLinePrefix', 'suffix': 'ModDescriptionLineSuffix', 'implicit': 'ModDescriptionLineImplicit',
    'enchant': 'ModDescriptionLineEnchantmentImplicit', 'corruptionEnchant': 'ModDescriptionLineCorruptedImplicit',
    'uniqueMod': 'ModDescriptionLineUnique', 'crafted': 'ModDescriptionLineCrafted', 'fractured': 'ModDescriptionLineFractured',
    'desecrated': 'ModDescriptionLineDesecrated', 'tier': 'ModDescriptionLineTier', 'rank': 'ModDescriptionLineRank'}
RARITY_STRINGS = {'normal': 'ItemDisplayStringNormal', 'magic': 'ItemDisplayStringMagic', 'rare': 'ItemDisplayStringRare',
                  'unique': 'ItemDisplayStringUnique', 'gem': 'ItemDisplayStringGem', 'currency': 'ItemDisplayStringCurrency'}
# Свойства предмета в копии («Броня: 358») и слова требований («Требуется: Уровень 36, 54 Сила»)
PROP_STRINGS = {'ItemDisplayArmourArmour': 'armour', 'ItemDisplayArmourEvasionRating': 'evasion',
                'ItemDisplayArmourEnergyShield': 'energy_shield', 'ItemDisplayShieldBlockChance': 'block',
                'ItemDisplaySpiritValue': 'spirit', 'Quality': 'quality'}
WORD_STRINGS = {'sockets': 'ItemDisplayStringSockets', 'requires': 'ItemRequirementsLabel', 'level': 'Level',
                'str': 'SupportGemCountShortStrength', 'dex': 'SupportGemCountShortDexterity',
                'int': 'SupportGemCountShortIntelligence'}
RE_UI_TAG = re.compile(r'<[^<>]*>')


def ui_text(text):
    """Строка таблицы ClientStrings без разметки: [Corrupted|Осквернено] -> Осквернено, <italic>{…} -> …
    Места для подстановки ({0}, {1}) остаются."""
    t = re.sub(r'\{(\d+)\}', lambda m: '\x00%s\x01' % m.group(1), RE_CSD_MARK.sub(r'\1', text or ''))
    t = RE_UI_TAG.sub('', t).replace('{', '').replace('}', '')
    t = t.replace('\x00', '{').replace('\x01', '}')
    return ' '.join(t.split()) if t.strip() else ''


RE_NAME_TAG = re.compile(r'<[^<>{}]*>\{([^{}]*)\}')


def plain_name(text):
    """Название из таблицы игры без разметки клиента: «<size:37>{ระเบิดน้ำแข็ง}» -> «ระเบิดน้ำแข็ง»."""
    t = text or ''
    while True:
        u = RE_NAME_TAG.sub(r'\1', t)
        if u == t:
            break
        t = u
    return ' '.join(RE_UI_TAG.sub('', t).split())


def plain_link(text):
    """Название без ссылок клиента на понятия игры: «Гнездо для [Jewel|самоцвета]» -> «Гнездо для самоцвета» —
    так его показывает игра (узел дерева, строка интерфейса)."""
    return ' '.join(RE_CSD_MARK.sub(r'\1', text or '').split())


def placeholders_to_shape(template):
    """Шаблон описания свойства -> написание каталога: места для чисел — # (знак + у «{0:+d}»), без разметки."""
    t = re.sub(r'\{(\d*)(?::([^}]*))?\}', lambda m: '+#' if (m.group(2) or '').startswith('+') else '#', template)
    # число прямо в тексте шаблона («倒した敵1体ごとに…») — тоже #: копия предмета заменяет так все числа
    t = re.sub(r'\d+(?:[.,]\d+)?', '#', t)
    return shape(t)


def item_text_keys(cat):
    """Ключи строк свойств, которые бывают на предметах: строки аффиксов, собственных свойств, рун, путевых
    камней и всё, что знает слой Exiled Exchange 2. Остальные описания игры (умения, атлас, механики) копии не
    нужны — в слой языка клиента они не идут."""
    keep = set()
    for pack in (cat.get('lang') or {}).values():
        keep |= set(pack.get('stats') or {})

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ('lines', 'line', 'keys', 'key'):
                    keep.update(x for x in ([v] if isinstance(v, str) else v if isinstance(v, list) else []) if isinstance(x, str))
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    for part in ('mods', 'implicits', 'augments', 'waystones'):
        walk(cat.get(part))
    return keep


def base_key(path):
    """Путь базы без общей приставки и без регистра: в каталоге «Rings/RingDemigods1», в таблице игры
    «Metadata/Items/Rings/RingDemigods1»."""
    low = (path or '').lower()
    return low[len('metadata/items/'):] if low.startswith('metadata/items/') else low


def build_client_layers(folder, cat, descs, negated, anoint_nodes):
    """Слой языка клиента из таблиц самой игры — для каждого из её языков: {язык: слой}.

    bases / gems — английское название -> на языке клиента (BaseItemTypes); stats / less — написания строк свойств
    по ключу каталога (описания свойств игры); classes — класс предмета словом клиента -> класс игры (ItemClasses);
    heroClasses — класс и вознесение героя: имя из данных дерева -> слово клиента (Characters, Ascendancy);
    anoint — строка «Активирует {0}» и названия узлов (PassiveSkills) для тех узлов, что зачаровываются;
    props, words, copy — подписи копии предмета (ClientStrings). Так копия предмета читается на любом языке клиента."""
    tabs = {n: read_dat(folder, n) for n in ('ClientStrings', 'BaseItemTypes', 'ItemClasses', 'Characters', 'Ascendancy',
                                             'PassiveSkills')}
    if not all(tabs.values()):
        return {}
    col = lambda t, c, lang: dat_column(tabs[t], c, lang) or dat_column(tabs[t], c, 'en')
    langs = sorted(set(tabs['ClientStrings']['columns']['Text']))
    base_path = {base_key(path): b['name'] for path, b in cat['bases'].items()}
    keep = item_text_keys(cat)
    gem_name = {gid: g.get('name') for gid, g in cat['gems'].items()}
    out = {}
    for lang in langs:
        ui = dict(zip(tabs['ClientStrings']['columns']['Id'], col('ClientStrings', 'Text', lang)))
        names = dict(zip(tabs['BaseItemTypes']['columns']['Id'], col('BaseItemTypes', 'Name', lang)))
        by_key = {base_key(p): n for p, n in names.items()}
        bases = {en: plain_name(by_key[k]) for k, en in base_path.items() if plain_name(by_key.get(k))}
        gems = {}
        for path, local in names.items():
            gid = path.rsplit('/', 1)[-1]
            if gid in gem_name and gem_name[gid] and plain_name(local):
                gems[gem_name[gid]] = plain_name(local)
        stats, less = {}, {}
        for ids, by in descs:
            key = ' '.join(ids)
            if key not in keep:
                continue
            shapes = []
            for t in by.get(lang, []):
                sh = placeholders_to_shape(t)
                if sh and sh not in shapes:
                    shapes.append(sh)
            if shapes:
                stats[key] = shapes
            neg = [placeholders_to_shape(t) for t in (negated.get(lang) or {}).get(key, [])]
            if neg:
                less[key] = sorted(set(neg))
        classes = {plain_name(n): cid for cid, n in zip(tabs['ItemClasses']['columns']['Id'], col('ItemClasses', 'Name', lang))
                   if plain_name(n)}
        hero = {}
        for t in ('Characters', 'Ascendancy'):
            for en, local in zip(col(t, 'Name', 'en'), col(t, 'Name', lang)):
                if en and plain_name(local):
                    hero[en] = plain_name(local)
        skills = dict(zip([str(x) for x in tabs['PassiveSkills']['columns']['PassiveSkillGraphId']],
                          col('PassiveSkills', 'Name', lang)))
        line = next((t for ids, by in descs if ids == ('mod_granted_passive_hash',) for t in by.get(lang, [])), None)
        anoint = {'line': line, 'nodes': {n: skills[n] for n in anoint_nodes if skills.get(n)}} if line else {}
        copy = {k: ui_text(ui.get(sid)) for k, sid in COPY_STRINGS.items() if ui_text(ui.get(sid))}
        copy['unscalable'] = ' ' + copy['unscalable'] if copy.get('unscalable') else None
        copy['rarities'] = {ui_text(ui.get(sid)): k for k, sid in RARITY_STRINGS.items() if ui_text(ui.get(sid))}
        props = {ui_text(ui.get(sid)): k for sid, k in PROP_STRINGS.items() if ui_text(ui.get(sid))}
        words = {}
        for k, sid in WORD_STRINGS.items():
            w = ui_text(ui.get(sid)).rstrip(':： .').strip()
            if w:
                words[k] = w if k in ('sockets', 'requires') else [w]
        out[lang] = {'bases': bases, 'gems': gems, 'stats': stats, 'less': less, 'classes': classes,
                     'heroClasses': hero, 'anoint': anoint, 'props': props, 'words': words,
                     'copy': {k: v for k, v in copy.items() if v}}
    return out


def merge_layer(game, ee2, extra):
    """Слой языка: таблицы игры, поверх — Exiled Exchange 2 (написания свойств складываются, названия — игры: их
    пишет сам клиент), поверх — слова, которые ведём сами (catalog/extra/lang-<язык>.json; словари дополняют)."""
    out = dict(game or {})
    for k, v in (ee2 or {}).items():
        if k in ('stats', 'less') and isinstance(out.get(k), dict):
            merged = {key: list(sh) for key, sh in v.items()}
            for key, sh in out[k].items():
                merged[key] = merged.get(key, []) + [x for x in sh if x not in merged.get(key, [])]
            out[k] = merged
        elif k in ('bases', 'gems') and isinstance(out.get(k), dict):
            out[k] = dict(v, **out[k])
        elif k == 'anoint' and out.get(k):
            continue
        else:
            out[k] = v
    for k, v in (extra or {}).items():
        out[k] = dict(out[k], **v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def build_area_names(folder):
    """Названия зон по языкам из таблицы игры WorldAreas: {язык: {код зоны: название}}."""
    tab = read_dat(folder, 'WorldAreas')
    if not tab:
        return {}
    ids, names = tab['columns']['Id'], tab['columns']['Name']
    langs = names if isinstance(names, dict) else {'en': names}
    return {lang: {code: plain_name(name) for code, name in zip(ids, vals) if code and plain_name(name)}
            for lang, vals in langs.items()}


# Таблицы игры, в которых названо то, что план называет парой «Русское (English)»: предметы, монстры и боссы,
# NPC, задания, зоны, узлы деревьев, классы; короткие строки интерфейса игры — механики и метки карты мира.
NAME_TABLES = (('BaseItemTypes', 'Name'), ('MonsterVarieties', 'Name'), ('NPCs', 'Name'), ('NPCs', 'ShortName'),
               ('Quest', 'Name'), ('WorldAreas', 'Name'), ('PassiveSkills', 'Name'), ('Characters', 'Name'),
               ('Ascendancy', 'Name'), ('ItemClasses', 'Name'), ('ClientStrings', 'Text'))
RE_UI_NAME = re.compile(r"[A-Z][A-Za-z '’,:-]*")


def build_names(folder):
    """Названия из игры на её языках по английскому названию — для страницы на этом языке: {язык: {names:
    {English: местное}, nodes: {id узла дерева: местное}}}. Английского нет: английское — само название. Русский
    есть: план записывает название так, как его назвал автор (узел дерева он мог взять на карте английским),
    а русская страница показывает название игры — по id узла и по английскому названию. Одно английское название
    у нескольких записей с разным переводом — берётся самый частый перевод. Из строк интерфейса — только короткие,
    похожие на названия. nodes — по id узла (PassiveSkills.Id: так узлы названы в данных деревьев героя и атласа)."""
    tabs = {t: read_dat(folder, t) for t, _ in NAME_TABLES}
    langs = set()
    for t, c in NAME_TABLES:
        if tabs.get(t) and isinstance(tabs[t]['columns'].get(c), dict):
            langs |= set(tabs[t]['columns'][c])
    out = {}
    for lang in sorted(langs - {'en'}):
        votes = {}
        for t, c in NAME_TABLES:
            tab = tabs.get(t)
            en_col, loc_col = (dat_column(tab, c, 'en'), dat_column(tab, c, lang)) if tab else (None, None)
            if not en_col or not loc_col:
                continue
            for en, loc in zip(en_col, loc_col):
                if not isinstance(en, str) or not isinstance(loc, str) or '[' in en or '{' in en:
                    continue
                en, loc = plain_name(en), plain_link(plain_name(loc))
                if not en or not loc or en == loc or len(en) > 60:
                    continue
                if t == 'ClientStrings' and (len(en) > 40 or not RE_UI_NAME.fullmatch(en)):
                    continue
                votes.setdefault(en, collections.Counter())[loc] += 1
        nodes = {}
        ps = tabs.get('PassiveSkills')
        if ps and dat_column(ps, 'Name', lang):
            for nid, loc in zip(ps['columns']['Id'], dat_column(ps, 'Name', lang)):
                if nid and plain_link(plain_name(loc)):
                    nodes[nid] = plain_link(plain_name(loc))
        out[lang] = {'names': {en: c.most_common(1)[0][0] for en, c in sorted(votes.items())}, 'nodes': nodes}
    return out


def build(folder=None, langs=('ru', 'en')):
    """Весь каталог одним словарём."""
    world = json.loads(read_source('world_areas.json', SOURCES['world_areas.json'], folder))
    items = json.loads(read_source('base_items.json', SOURCES['base_items.json'], folder))
    mods = json.loads(read_source('mods.json', SOURCES['mods.json'], folder))
    formats = {}
    texts = build_stat_texts(json.loads(read_source('stat_descriptions.json', SOURCES['stat_descriptions.json'], folder)),
                             formats)
    gems = json.loads(read_source('skill_gems.json', SOURCES['skill_gems.json'], folder))
    skills = json.loads(read_source('skills.json', SOURCES['skills.json'], folder))
    augments = json.loads(read_source('augments.json', SOURCES['augments.json'], folder))
    classes = json.loads(read_source('item_classes.json', SOURCES['item_classes.json'], folder))
    here = Path(__file__).resolve().parent / 'extra'
    game = here / 'game.json'
    extra = json.loads(game.read_text(encoding='utf-8')) if game.is_file() else {}
    table = here / 'stats.json'
    stat_table = json.loads(table.read_text(encoding='utf-8')) if table.is_file() else {}
    craft = here / 'craft.json'
    craft_rules = json.loads(craft.read_text(encoding='utf-8')) if craft.is_file() else {}
    cat = {'version': read_source('version.txt', SOURCES['version.txt'], folder).strip(),
           'areas': build_areas(world), 'bases': build_bases(items), 'mods': build_mods(mods, texts, formats),
           'gems': build_gems(gems, items, skills), 'rules': build_rules(items, extra),
           'waystones': build_waystones(items, mods, texts, formats),
           'implicits': build_implicits(items, mods, texts), 'augments': build_augments(augments, items, texts),
           'stats': build_stats(stat_table, texts), 'emotions': build_emotions(items), 'lang': {}}
    # Веса свойств — выжимка страниц poe2db в папке источников (этот скрипт её не качает); без неё части нет.
    digest = read_digest(folder)
    item_names = {b.get('name') for b in items.values() if isinstance(b, dict) and b.get('name')}
    cat['craft'] = build_craft(digest, mods, texts, formats, craft_rules, item_names) if digest else {}
    # Тексты лога на всех языках клиента и названия зон — из таблиц игры (catalog/dat_pack.py); без них частей нет.
    cat['log'] = build_log_text(folder)
    # тексты свойств — по ним строка награды в логе находит коды свойств на языке клиента
    stat_lines = build_stat_lines(folder)
    for lang, pack in cat['log'].items():
        pack['stat'] = stat_lines.get(lang, {})
    area_names = build_area_names(folder)
    # названия из игры на её языках — для страниц на этих языках (пары «Русское (English)» плана)
    cat['names'] = build_names(folder) if folder else {}
    # слой языка клиента из таблиц игры: на нём копия предмета читается на любом из её языков
    import gzip
    csd_path = Path(folder) / 'dat' / 'stat_descriptions.csd.gz' if folder else None
    negated, descs = {}, []
    if csd_path and csd_path.is_file():
        descs = parse_csd(gzip.decompress(csd_path.read_bytes()).decode('utf-16'), negated)
    anoint_nodes = []
    game_layers = {}
    items_by_lang = {}           # таблицы предметов Exiled Exchange 2 по языкам: из них — имена уникальных
    for lang in langs:
        files = [read_source('%s-%s' % (lang, name), EE2 + lang + '/' + name, folder) for name in LANG_FILES]
        items_by_lang[lang] = files[0]
        cat['lang'][lang] = build_lang(files[0], files[1], texts)
        if lang == 'en':
            # таблица классов игры — английская: classNames этого языка — её названия для всех классов снаряжения
            cat['lang'][lang]['classNames'] = build_class_names(classes, cat['bases'])
        # Слова, которых нет в источниках, ведём сами: catalog/extra/lang-<язык>.json. Это classes —
        # как клиент пишет класс предмета («Класс предмета: Сапоги») -> класс в данных игры: запасной путь,
        # когда базу вещи не удалось найти по названию; слова проверены по тексту вещей из клиента.
        # И classNames — класс в данных игры -> как его называет таблица классов игры (взято с poe2db):
        # подпись класса на странице «Билд» там, где слова клиента нет. Это не одно и то же: сапоги клиент
        # пишет «Сапоги», а таблица классов — «Обувь», поэтому classNames в разбор вещей не идёт.
        # И heroClasses — класс героя и вознесение (имена из данных дерева GGG) -> как их называет игра
        # на этом языке (взято с poe2db; «Ученица Варашты» сверена с логом игры).
        extra =Path(__file__).resolve().parent / 'extra' / ('lang-%s.json' % lang)
        if extra.is_file():
            cat['lang'][lang].update(json.loads(extra.read_text(encoding='utf-8')))
        anoint_nodes = sorted(set(anoint_nodes) | set(((cat['lang'][lang].get('anoint') or {}).get('nodes') or {})))
    # узлы, что зачаровываются, — из слоя Exiled Exchange 2 (номера узлов одни на всех языках); названия — игры
    game_layers = build_client_layers(folder, cat, descs, negated, anoint_nodes) if descs else {}
    for lang in sorted(set(cat['lang']) | set(game_layers)):
        extra = Path(__file__).resolve().parent / 'extra' / ('lang-%s.json' % lang)
        hand = json.loads(extra.read_text(encoding='utf-8')) if extra.is_file() else {}
        ee2 = {k: v for k, v in (cat['lang'].get(lang) or {}).items() if k not in hand}
        cat['lang'][lang] = merge_layer(game_layers.get(lang), ee2, hand)
        # названия зон на этом языке — из таблицы игры: шаг маршрута по зоне называется словами клиента
        if area_names.get(lang):
            cat['lang'][lang]['areas'] = {c: n for c, n in area_names[lang].items() if c in cat['areas']}
    # Уникальные предметы: свой рисунок и имя на языке клиента — по нему копия уникального находит его картинку.
    # Нет таблицы уникальных в папке источников (папка старше) — части нет: картинкой остаётся рисунок базы.
    table = optional_source('uniques.json', SOURCES['uniques.json'], folder)
    cat['uniques'] = {}
    if table:
        for lang, sub in UNIQUE_LANGS.items():
            if lang not in items_by_lang:
                text = optional_source('%s-items.ndjson' % lang, EE2 + sub + '/items.ndjson', folder)
                if text:
                    items_by_lang[lang] = text
        cat['uniques'], unique_names = build_uniques(json.loads(table), items_by_lang)
        for lang, names in unique_names.items():
            if lang in cat['lang'] and names:
                cat['lang'][lang]['uniques'] = names
    return cat


def optional_source(name, url, folder=None):
    """Как read_source, но источник, добавленный в каталог позже: в папке источников его может не быть — тогда None
    (без папки — читается из сети, как и остальные). Так пересборка из старой папки ничего не качает молча."""
    if folder:
        path = Path(folder) / name
        return path.read_text(encoding='utf-8') if path.is_file() else None
    return read_source(name, url)


def main():
    ap = argparse.ArgumentParser(description='Каталог данных игры')
    ap.add_argument('--fetch', action='store_true', help='скачать исходные файлы в папку --sources')
    ap.add_argument('--fetch-missing', action='store_true',
                    help='докачать в текущую версию папки --sources только те исходные файлы, которых в ней нет')
    ap.add_argument('--sources', help='папка с исходными файлами (иначе читаются из сети в память)')
    ap.add_argument('--out', help='куда записать каталог (иначе только сводка)')
    ap.add_argument('--lang', nargs='*', default=['ru', 'en'])
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    if args.fetch:
        if not args.sources:
            ap.error('--fetch нужна папка --sources')
        folder = fetch(args.sources, args.lang)
    elif args.fetch_missing:
        if not args.sources:
            ap.error('--fetch-missing нужна папка --sources')
        folder = fetch_missing(args.sources, args.lang)
    else:
        folder = current(args.sources) if args.sources else None
    cat = build(folder, args.lang)
    print('версия данных игры: %s' % cat['version'])
    print('зон: %d | баз снаряжения: %d | семейств аффиксов: %d (ступеней %d) | камней: %d' % (
        len(cat['areas']), len(cat['bases']), len(cat['mods']), sum(len(f['mods']) for f in cat['mods'].values()),
        len(cat['gems'])))
    print('путевые камни: тиров %d, семейств аффиксов %d' % (
        len(cat['waystones']['tiers']), len(cat['waystones']['mods'])))
    print('собственных свойств баз: %d | вставок в гнёзда: %d | статов героя: %d' % (
        len(cat['implicits']), len(cat['augments']), len(cat['stats']['stats'])))
    if cat['stats']['missing']:
        print('В ТАБЛИЦЕ СТАТОВ свойства, которых нет в данных игры: %s' % '; '.join(cat['stats']['missing']))
    if cat['craft']:
        pages = cat['craft']['pages']
        print('крафт: страниц классов %d, свойств с весом %d, свойств сущностей %d, очернённых %d; по имени найдено %d' % (
            len(pages), sum(len(p['normal']) for p in pages.values()),
            sum(len(p['essence']) + len(p['perfect_essence']) for p in pages.values()),
            sum(len(p['desecrated']) for p in pages.values()), cat['craft']['matched']))
        for note in cat['craft']['notes']:
            print('КРАФТ: %s' % note)
    else:
        print('крафт: выжимки poe2db в папке источников нет — части о крафте не будет')
    for lang, pack in cat['lang'].items():
        print('язык %s: названий баз %d, камней %d, текстов свойств %d, узлов зачарования %d, зон %d, уникальных %d' % (
            lang, len(pack['bases']), len(pack['gems']), len(pack['stats']), len((pack.get('anoint') or {}).get('nodes') or {}),
            len(pack.get('areas') or {}), len(pack.get('uniques') or {})))
    print('уникальных предметов: %d (с базами %d)' % (
        len(cat.get('uniques') or {}), sum(1 for u in (cat.get('uniques') or {}).values() if u['bases'])))
    if cat['log']:
        first = next(iter(cat['log'].values()))
        print('тексты лога: %s — реплик %d, системных строк %d, текстов свойств %d' % (
            ', '.join(sorted(cat['log'])), len(first['say']), len(first['msg']), len(first.get('stat') or {})))
    else:
        print('тексты лога: таблиц игры (dat/) в папке источников нет — части не будет')
    if cat['names']:
        print('названия из игры для страниц: %s' % ', '.join(
            '%s %d (+%d узлов)' % (lang, len(p['names']), len(p['nodes'])) for lang, p in sorted(cat['names'].items())))
    if args.out:
        if not re.fullmatch(r'[0-9A-Za-z._-]{1,40}', cat['version']):
            raise ValueError('странная версия данных: %r' % cat['version'][:60])
        out = Path(args.out) / cat['version']
        out.mkdir(parents=True, exist_ok=True)
        (Path(args.out) / 'current.txt').write_text(cat['version'] + '\n', encoding='utf-8')
        dump = lambda name, data: (out / name).write_text(
            json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        dump('meta.json', {'version': cat['version'], 'languages': list(cat['lang']), 'log': sorted(cat['log']),
                           'names': sorted(cat['names'])})
        for part in ('areas', 'bases', 'mods', 'gems', 'rules', 'waystones', 'implicits', 'augments', 'stats', 'emotions'):
            dump(part + '.json', cat[part])
        if cat.get('uniques'):
            dump('uniques.json', cat['uniques'])
        if cat['craft']:
            dump('craft.json', cat['craft'])
        for lang, pack in cat['lang'].items():
            dump('lang-%s.json' % lang, pack)
        import gzip
        if cat['log']:
            # системные строки всех языков — маленький файл: по нему плеер узнаёт язык клиента по самому логу
            dump('log-msg.json', {lang: pack['msg'] for lang, pack in sorted(cat['log'].items())})
        for lang, pack in cat['names'].items():
            # названия из игры на языке страницы — сжаты; программа читает только язык открытой страницы
            (out / ('names-%s.json.gz' % lang)).write_bytes(gzip.compress(
                json.dumps(pack, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), mtime=0))
        for lang, pack in cat['log'].items():
            # реплики всех NPC игры — большой файл: сжат; плеер читает только язык клиента и языки страниц
            (out / ('log-%s.json.gz' % lang)).write_bytes(gzip.compress(
                json.dumps(pack, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), mtime=0))
        print('записано в %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
