# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Геометрия дерева атласа для страницы — из открытой выгрузки таблиц игры.

Исходник: catalog/sources/<версия>/Atlas.min.json (выгрузка repoe-fork, её скачивает catalog/build.py;
рядом лежит SOURCE.txt: откуда, размер, контрольная сумма). В файле семь деревьев с общими очками
внутри каждого: основное («Атлас») и по одному на механику. Результат — planner/static/atlas.json
того же вида, что и tree.json дерева героя, поэтому карта и правка на странице у них общие:

    trees: [{id, key, name}]              деревья по порядку: id корневого узла, слово игры (Breach),
                                          название как в клиенте («Разлом»)
    nodes: [id, x, y, вид, название, дерево, условия]
                                          вид: 0 малый, 2 значимый, 3 ключевой (в атласе это узел с выбором),
                                          5 корень дерева; название английское; дерево — номер в trees;
                                          условия — номера строк в conds; поля нет — условий нет; null —
                                          данных нет (см. node_when); id — как в логе игры
    edges: [a, b] или [a, b, cx, cy]      номера узлов в nodes; cx, cy — центр дуги, по которой идёт связь
    ru:    {английское название: русское} как узел называет клиент (catalog/extra/atlas-ru.json)
    conds: [строка]                       условия узлов словами клиента: когда узел действует («Действует
                                          на области 70+ уровня») и что нужно, чтобы его взять («Требует
                                          активации большого зеркала»). В выгрузке игры их нет — они из
                                          того же atlas-ru.json

В выгрузке у узла нет готовых координат: он стоит на орбите своей группы (радиус и место по часовой
стрелке), а у связи вместо центра дуги — номер орбиты со знаком. Как из этого получается то, что
рисует игра, проверено на дереве героя: его GGG выкладывает уже с координатами и центрами дуг.

    узел:   угол = 2π · место / мест_на_орбите; x = x_группы + R·sin(угол), y = y_группы − R·cos(угол)
    связь:  0 — прямая; ±k — дуга радиуса орбиты k через оба узла. Если идти от узла, у которого связь
            записана, к другому, центр дуги лежит слева при k > 0 и справа при k < 0 (ось y — вниз).

Не входят «мастерства» — картинки в центре групп, которые взять нельзя.

Второй файл — planner/static/atlasstats.json: что даёт каждый узел — для правки атласа на карте:
{id: {text: [строки], opts: [варианты выбора]}}. Текст — словами клиента (atlas-ru.json), а если узла
там нет — английский из выгрузки, без разметки. Варианты есть только у узлов с выбором. По нему программа
проверяет номер выбранного варианта (сколько их у узла).

На языках страниц программы (en, ru, de, fr, es, pt, ja, ko, th) — planner/static/atlasstats.<язык>.json того же
вида, словами самой игры: строки выгрузки переводятся описаниями свойств атласа из файлов игры в источниках
каталога (dat/atlas_variant_stat_descriptions.csd.gz, dat/atlas_stat_descriptions.csd.gz; catalog/dat_pack.py), а
варианты выбора — они известны только по-русски (карточки poe2db) — тем же описанием с русского. В atlas.json для
них же: condsLang — условия узлов строками интерфейса игры (ClientStrings AtlasPassive…), treesLang — названия
деревьев; по-русски — conds и trees как были.

После патча: python -I catalog/build.py --fetch …, затем этот скрипт.
Запуск: python planner/atlasgeo.py [Atlas.min.json] [atlas.json] [atlasstats.json] [atlas-ru.json]
"""
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from treegeo import RE_MARK, RE_MARK1, SMALL, NOTABLE, KEYSTONE, START  # noqa: E402
import treegeo  # noqa: E402

SOURCES = HERE.parent / 'catalog' / 'sources'
NAMES = HERE.parent / 'catalog' / 'extra' / 'atlas-ru.json'
TARGET = HERE / 'static' / 'atlas.json'
STATS = HERE / 'static' / 'atlasstats.json'
NO_ORBIT = 2147483647     # так в выгрузке помечена связь без орбиты: прямая
# Строка, которую база не перевела: внутреннее имя свойства с числом («map item drop rarity +% [10]»)
RE_RAW = re.compile(r'[a-z][a-z0-9_ +%\-]*\[-?\d+\]')


def source_path(root=SOURCES):
    """Файл дерева атласа в папке текущей версии данных игры (её имя записано в current.txt)."""
    root = Path(root)
    try:
        name = (root / 'current.txt').read_text(encoding='utf-8').strip()
    except OSError:
        name = ''
    return (root / name if name else root) / 'Atlas.min.json'


def kind_of(p):
    if p.get('is_atlas_root'):
        return START
    if p.get('is_keystone'):
        return KEYSTONE
    if p.get('is_notable'):
        return NOTABLE
    return SMALL


def arc_centre(a, b, radius, sign):
    """Центр дуги радиуса radius через точки a и b. sign > 0 — центр слева от пути a → b, иначе справа
    (ось y направлена вниз). Радиус меньше половины расстояния — полуокружность: центр посередине."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if not length:
        return None
    h = math.sqrt(max(0.0, radius * radius - length * length / 4))
    nx, ny = -dy / length, dx / length
    if sign > 0:
        return mx - nx * h, my - ny * h
    return mx + nx * h, my + ny * h


def node_when(node_id, info, main):
    """Условия узла: список строк ([] — условий нет) или None — данных нет. info — запись его названия
    в atlas-ru.json, main — узел основного дерева.

    Название носит один узел — условия из списка точные. Малый узел с повторяющимся названием стоит
    в разных разделах дерева, и условия у таких узлов разные: берутся те, что названы для него самого
    (поле ids). Если его там нет: в дереве механики условия несут значимые узлы, а не малые — когда все
    перечисленные узлы этого названия без условий, без условий и он; в основном дереве условие малого
    узла зависит от раздела, и угадывать его по соседям нельзя (проверено: ошибается) — данных нет."""
    if not info:
        return []
    if info.get('count', 1) <= 1:
        return info.get('when') or []
    listed = info.get('ids') or {}
    if node_id in listed:
        return listed[node_id]
    if not main and listed and not any(listed.values()):
        return []
    return None


def build(data, names=None):
    """Выгрузка -> компактная геометрия: {'trees': [...], 'nodes': [...], 'edges': [...], 'ru': {...}}."""
    names = names or {}
    passives = {int(p['hash']): p for p in data['passives'].values() if isinstance(p, dict) and p.get('id')}
    radii, per = data['orbit_radii'], data['skills_per_orbit']
    xy, links = {}, []
    for g in data['groups']:
        for n in g.get('passives') or []:
            h = n['hash']
            p = passives.get(h)
            if p is None or p.get('is_icon_only'):
                continue
            angle = 2 * math.pi * n['position_clockwise'] / per[n['radius']]
            r = radii[n['radius']]
            xy[h] = (g['x'] + r * math.sin(angle), g['y'] - r * math.cos(angle))
            splines = n.get('splines') or []
            for k, to in enumerate(n.get('connections') or []):
                links.append((h, to, splines[k] if k < len(splines) else 0))
    near = {}
    for a, b, _ in links:
        if a in xy and b in xy and a != b:
            near.setdefault(a, set()).add(b)
            near.setdefault(b, set()).add(a)
    # дерево узла — по корню, до которого от него можно дойти
    tree_of, trees = {}, []
    label = names.get('trees') or {}
    for root in data.get('roots') or []:
        if root not in xy or root in tree_of:
            continue
        index = len(trees)
        seen, queue = {root}, [root]
        while queue:
            for nb in near.get(queue.pop(), ()):
                if nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        for h in seen:
            tree_of[h] = index
        key = next(((passives[h].get('atlas_subtree') or {}).get('id') for h in seen
                    if (passives[h].get('atlas_subtree') or {}).get('id')), None) or 'Atlas'
        rid = passives[root]['id']
        trees.append({'id': rid, 'key': key, 'name': label.get(rid) or key})
    keep = sorted(tree_of, key=lambda h: (xy[h][1], xy[h][0], passives[h]['id']))
    index = {h: i for i, h in enumerate(keep)}
    # условия узла — номерами строк в общем списке: одни и те же строки стоят у сотни узлов
    details, conds, cond_at = names.get('nodes') or {}, [], {}
    nodes = []
    for h in keep:
        p = passives[h]
        node = [p['id'], int(round(xy[h][0])), int(round(xy[h][1])), kind_of(p), str(p.get('name') or ''), tree_of[h]]
        when = node_when(p['id'], details.get(node[4]), tree_of[h] == 0) if node[4] and details else []
        if when is None:
            node.append(None)
        elif when:
            for line in when:
                if line not in cond_at:
                    cond_at[line] = len(conds)
                    conds.append(line)
            node.append([cond_at[line] for line in when])
        nodes.append(node)
    edges, seen = [], set()
    for a, b, spline in links:
        ia, ib = index.get(a), index.get(b)
        if ia is None or ib is None or ia == ib:
            continue
        pair = (min(ia, ib), max(ia, ib))
        if pair in seen:
            continue
        seen.add(pair)
        centre = None
        if spline and spline != NO_ORBIT and abs(spline) < len(radii):
            centre = arc_centre(xy[a], xy[b], radii[abs(spline)], spline)
        edges.append([ia, ib, int(round(centre[0])), int(round(centre[1]))] if centre else [ia, ib])
    words = names.get('names') or {}
    ru = {n[4]: words[n[4]] for n in nodes if n[4] and words.get(n[4]) and words[n[4]] != n[4]}
    return {'tree': 'Atlas', 'trees': trees, 'nodes': nodes, 'edges': edges, 'ru': dict(sorted(ru.items())),
            'conds': conds}


# --- тексты атласа на языках страниц: описания свойств и строки интерфейса игры ----------------------------------
ATLAS_DESC_FILES = ('atlas_variant_stat_descriptions.csd.gz', 'atlas_stat_descriptions.csd.gz')
PAGE_LANGS = ('en',) + treegeo.PAGE_LANGS
RE_BRACE = re.compile(r'\{\{|\}\}|\{[^{}]*\}')


def ui_template(text):
    """Строка интерфейса игры как шаблон описания: «{{» и «}}» — скобки разметки, они снимаются вместе с тегами <…>;
    {0} — место числа. «Applies to <rgb(…)>{{Level {0}+}} Areas» -> «Applies to Level {0}+ Areas»."""
    t = RE_BRACE.sub(lambda m: '' if m.group(0) in ('{{', '}}') else m.group(0), str(text or ''))
    return ' '.join(treegeo.plain(re.sub(r'<[^<>]*>', '', t)).split())


def read_texts(base):
    """Из папки версии источников каталога: описания свойств атласа (за ними общие), условия узлов строками интерфейса
    игры (AtlasPassive… — в виде описаний с одним вариантом) и сама таблица строк интерфейса. Нет описаний атласа —
    ([], [], None)."""
    import gzip
    descs = []
    for name in ATLAS_DESC_FILES:
        path = Path(base) / 'dat' / name
        if path.is_file():
            descs += treegeo.parse_descriptions(gzip.decompress(path.read_bytes()).decode('utf-16'))
    if not descs:
        return [], [], None
    descs += treegeo.read_descriptions(base)
    path = Path(base) / 'dat' / 'ClientStrings.json.gz'
    ui = json.loads(gzip.decompress(path.read_bytes()).decode('utf-8')) if path.is_file() else None
    conds = []
    if ui:
        texts = ui['columns']['Text']
        langs = texts if isinstance(texts, dict) else {'en': texts}
        for k, rid in enumerate(ui['columns']['Id']):
            if rid.startswith('AtlasPassive'):
                conds.append({'ids': [rid], 'lang': {lang: [([], ui_template(vals[k]), [])] for lang, vals in langs.items()
                                                     if isinstance(vals[k], str) and vals[k].strip()}})
    return descs, conds, ui


def tree_names(trees, ui):
    """Названия деревьев атласа на языках страниц, кроме русского: {язык: [название по порядку trees]}. Русское
    название (atlas-ru.json) ищется среди строк интерфейса игры с тем же английским словом (key); не нашлось —
    английское слово."""
    texts = ((ui or {}).get('columns') or {}).get('Text') or {}
    ru, en = texts.get('ru') or [], texts.get('en') or []
    at = {}
    for k, (r, e) in enumerate(zip(ru, en)):
        if isinstance(r, str) and isinstance(e, str):
            at.setdefault((ui_template(r), ui_template(e).lower()), k)
    out = {}
    for lang in PAGE_LANGS:
        if lang == 'ru':
            continue
        vals = texts.get(lang) or []
        names = []
        for t in trees:
            k = at.get((t['name'], str(t['key']).lower()))
            local = ui_template(vals[k]) if k is not None and k < len(vals) and isinstance(vals[k], str) else ''
            names.append(local or t['key'])
        out[lang] = names
    return out


def lang_texts(data, names, lang, tr_text, tr_opt):
    """Что даёт каждый узел на языке lang: {id: {text, opts}} и счёт (строк переведено, всего, вариантов переведено,
    всего). Текст — строки выгрузки словами игры на этом языке (свойство целиком, а нет — по строкам; что не нашлось,
    остаётся английским), по-английски — как в выгрузке; по-русски узел, у которого описание игры знает не все
    строки, остаётся карточкой poe2db. Варианты выбора известны только по-русски: на другом языке — их перевод
    тем же описанием игры; не нашлось — как в карточке."""
    details = (names or {}).get('nodes') or {}
    out, counts = {}, [0, 0, 0, 0]
    for p in data['passives'].values():
        if not isinstance(p, dict) or not p.get('id') or p.get('is_icon_only'):
            continue
        card_text, card_opts = client_text(p, (details.get(p.get('name')) or {}).get('text'))
        if lang == 'en' or tr_text is None:
            text = english(p)
        else:
            text, whole = [], True
            for item in p.get('stat_text') or []:
                item = treegeo.plain(item).strip()
                parts = [x.strip() for x in item.split('\n') if x.strip()]
                counts[1] += len(parts)
                got = tr_text(item)
                if got:
                    counts[0] += len(parts)
                    text += got
                    continue
                for part in parts:
                    one = tr_text(part)
                    whole = whole and bool(one)
                    counts[0] += bool(one)
                    text += one or [part]
            if lang == 'ru' and not whole:
                text = card_text
        if lang == 'ru' or tr_opt is None:
            opts = card_opts
        else:
            opts = []
            for o in card_opts:
                one = tr_opt(o)
                counts[3] += 1
                counts[2] += bool(one)
                opts.append(' '.join(one) if one else o)
        if text or opts:
            out[p['id']] = dict({'text': text}, **({'opts': opts} if opts else {}))
    return out, counts


def english(p):
    """Строки текста узла из выгрузки, без разметки ссылок."""
    lines = []
    for s in p.get('stat_text') or []:
        for part in str(s).split('\n'):
            part = RE_MARK1.sub(r'\1', RE_MARK.sub(r'\2', part)).strip()
            if part:
                lines.append(part)
    return lines


def client_text(p, page):
    """Текст узла словами клиента: (строки, варианты выбора). page — строки карточки узла из atlas-ru.json
    по порядку; нет карточки — английский текст выгрузки.

    У узла с выбором (в атласе это все ключевые узлы) выгрузка знает только заглавную строку («100%
    увеличение шанса нахождения Сущностей определенного типа»), а карточка перечисляет за ней варианты.
    У прочих узлов все строки карточки — текст. Карточка короче выгрузки бывает по двум причинам:
    английская фраза перенесена на вторую строку (тогда потери нет) или база часть строк не показала —
    эти строки дописываются по-английски, чтобы узел не выглядел слабее, чем он есть."""
    en = english(p)
    if not page:
        return en, []
    if p.get('is_keystone') and len(page) > len(en):
        text, opts = page[:len(en)], page[len(en):]
        # непереведённая служебная строка, повторённая у каждого варианта, ничего не сообщает
        repeated = {x for x in opts if RE_RAW.fullmatch(x) and opts.count(x) > 1}
        return text, [x for x in opts if x not in repeated]
    if len(page) < len(en):
        rest = en[len(page):]
        if not (len(rest) == 1 and not re.search(r'\d', rest[0])):
            return page + rest, []
    return page, []


def stats(data, names=None):
    """Что даёт каждый узел: {id: {text: [строки], opts: [варианты]}} — словами клиента, где они известны."""
    details = (names or {}).get('nodes') or {}
    out = {}
    for p in data['passives'].values():
        if not isinstance(p, dict) or not p.get('id') or p.get('is_icon_only'):
            continue
        text, opts = client_text(p, (details.get(p.get('name')) or {}).get('text'))
        if text or opts:
            out[p['id']] = dict({'text': text}, **({'opts': opts} if opts else {}))
    return out


def main(argv):
    src = Path(argv[1]) if len(argv) > 1 else source_path()
    dst = Path(argv[2]) if len(argv) > 2 else TARGET
    dst_stats = Path(argv[3]) if len(argv) > 3 else STATS
    names_path = Path(argv[4]) if len(argv) > 4 else NAMES
    with open(src, encoding='utf-8') as f:
        data = json.load(f)
    names = json.loads(names_path.read_text(encoding='utf-8')) if names_path.is_file() else {}
    geo = build(data, names)
    # тексты на языках страниц: описания свойств атласа и строки интерфейса игры из той же папки источников
    descs, cond_rows, ui = read_texts(src.parent)
    if descs:
        geo['condsLang'], geo['treesLang'] = {}, tree_names(geo['trees'], ui)
        for lang in PAGE_LANGS:
            if lang != 'ru':
                tr = treegeo.desc_translator(cond_rows, lang, source='ru')
                geo['condsLang'][lang] = [' '.join(tr(c)) if tr(c) else c for c in geo['conds']]
    with open(dst, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(geo, f, ensure_ascii=False, separators=(',', ':'))
    what = stats(data, names)
    with open(dst_stats, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(what, f, ensure_ascii=False, separators=(',', ':'))
    for lang in PAGE_LANGS if descs else ():
        out, (done, total, opt_done, opt_total) = lang_texts(
            data, names, lang, treegeo.desc_translator(descs, lang) if lang != 'en' else None,
            treegeo.desc_translator(descs, lang, source='ru') if lang != 'ru' else None)
        target = dst_stats.with_name('atlasstats.%s.json' % lang)
        with open(target, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
        print('тексты атласа, %s: строк %d из %d, вариантов %d из %d, условий %d, записано: %s' % (
            lang, done, total, opt_done, opt_total,
            sum(1 for a, b in zip(geo.get('condsLang', {}).get(lang, geo['conds']), geo['conds']) if a != b or lang == 'ru'),
            target))
    print('условий: %d разных, узлов с условиями: %d, без данных об условиях: %d | узлов с выбором: %d | '
          'узлов с английским текстом: %d' % (
        len(geo['conds']), sum(1 for n in geo['nodes'] if len(n) > 6 and n[6]),
        sum(1 for n in geo['nodes'] if len(n) > 6 and n[6] is None), sum(1 for v in what.values() if v.get('opts')),
        sum(1 for v in what.values() if any(not re.search('[а-яА-Я]', x) and not RE_RAW.fullmatch(x) for x in v['text']))))
    kinds = [0] * 6
    for n in geo['nodes']:
        kinds[n[3]] += 1
    print('деревья: %s' % ', '.join('%s %d' % (t['name'], sum(1 for n in geo['nodes'] if n[5] == i and n[3] != START))
                                   for i, t in enumerate(geo['trees'])))
    named = sum(1 for n in geo['nodes'] if n[4])
    print('узлов: %d (малых %d, значимых %d, ключевых %d, корней %d), связей: %d (дуг %d), русских названий: %d из %d'
          % (len(geo['nodes']), kinds[SMALL], kinds[NOTABLE], kinds[KEYSTONE], kinds[START], len(geo['edges']),
             sum(1 for e in geo['edges'] if len(e) == 4), sum(1 for n in geo['nodes'] if n[4] in geo['ru']), named))
    print('записано: %s, %d байт; %s, %d байт' % (dst, dst.stat().st_size, dst_stats, dst_stats.stat().st_size))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
