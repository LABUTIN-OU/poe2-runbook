# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Правка дерева пассивных умений со страницы: версии дерева записываются в файл плана.

Версия — дерево целиком, каким оно должно быть на своём отрезке забега (до вознесения, до карт, карты):
название и полный порядок узлов от старта класса. С какого шага версия действует, она сама не говорит:
её называет этап билда (раздел stages). Правят версии на вкладке «Дерево» страницы «Билд»; страница
присылает полный набор версий вместе с остальными разделами билда (server.tree_section), версию — списком
[{id, attr?}]. Здесь список проверяется по данным дерева
(узлы существуют, не повторяются, каждый примыкает к взятым раньше — такой порядок можно пройти
в игре), превращается в записи плана (id, название, вид, атрибут) и вписывается в раздел "tree"
файла. Остальной текст файла не меняется: это проверяется перед записью, а прежний файл
сохраняется копией.

Так же правится дерево атласа — раздел "atlas" того же файла (данные — atlas.json, их собирает
atlasgeo.py). Отличий два: деревьев в атласе несколько, у каждого свой корень, поэтому узел может
примыкать к любому корню; и раздела в файле сначала нет — первая запись его создаёт.
"""
import copy
import json
import os
import re
import shutil
import time
from pathlib import Path
from i18n import tr

ATTRS = ('str', 'dex', 'int')                 # что можно выбрать в узле «Характеристика»
# какими словами атрибут бывает записан в файлах: id, английское и русское название, сокращение
ATTR_WORDS = {'str': 'str', 'strength': 'str', 'сила': 'str', 'сил': 'str',
              'dex': 'dex', 'dexterity': 'dex', 'ловк': 'dex', 'ловкость': 'dex',
              'int': 'int', 'intelligence': 'int', 'инт': 'int', 'интеллект': 'int'}
KINDS = {1: 'attribute', 2: 'notable', 3: 'keystone', 4: 'socket'}   # вид узла в tree.json -> поле kind
ATTRIBUTE, START = 1, 5
CHOICE = 3           # в атласе узел вида 3 — узел с выбором: взяв его, выбирают один из вариантов
MAX_NODES = 700      # столько узлов в одной версии не бывает: у героя очков около ста двадцати, в атласе 530 узлов
MAX_VERSIONS = 40    # версий дерева в одном плане
MAX_NAME = 60        # длина названия версии
RE_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,39}')
KEEP_BACKUPS = 20    # сколько прежних версий файла хранить


def attr_id(word):
    """Атрибут, как бы он ни был записан: «int», «Intelligence», «инт» -> 'int'. Не атрибут — None."""
    return ATTR_WORDS.get(str(word or '').strip().lower())


def with_default(nodes, default, geo=None):
    """Узлы версии для страницы: [{id, attr?}], где прежний атрибут дерева «по умолчанию» (поле attr раздела
    tree в старых файлах) записан каждому узлу «Характеристика», у которого своего нет. Общего «по
    умолчанию» у дерева больше нет: атрибут узла выбирает автор, узел без выбора — пустой. Что узел —
    «Характеристика», говорят данные дерева (geo), а без них — поле kind его записи."""
    kinds, default = (geo or {}).get('kind') or {}, attr_id(default)
    out = []
    for n in nodes or []:
        if not (isinstance(n, dict) and n.get('id')):
            continue
        attr = n.get('attr')
        if not attr and default:
            generic = kinds[n['id']] == ATTRIBUTE if n['id'] in kinds else n.get('kind') == KINDS[ATTRIBUTE]
            attr = default if generic else None
        rec = {'id': n['id'], 'attr': attr} if attr else {'id': n['id']}
        # узел атласа с выбором: номер выбранного варианта
        if isinstance(n.get('opt'), int) and not isinstance(n.get('opt'), bool) and n['opt'] > 0:
            rec['opt'] = n['opt']
        out.append(rec)
    return out


def load_geo(path):
    """Данные дерева из tree.json или atlas.json (их собирают treegeo.py и atlasgeo.py): виды и названия
    узлов, соседи. Название — как в клиенте игры, если файл его знает (слой ru), иначе английское.
    forest — деревьев в файле несколько, у каждого свой корень (атлас)."""
    with open(path, encoding='utf-8') as f:
        geo = json.load(f)
    ids = [n[0] for n in geo['nodes']]
    near = {i: set() for i in ids}
    for e in geo['edges']:
        a, b = ids[e[0]], ids[e[1]]
        near[a].add(b)
        near[b].add(a)
    ru = geo.get('ru') or {}
    return {'kind': {n[0]: n[3] for n in geo['nodes']}, 'name': {n[0]: ru.get(n[4]) or n[4] for n in geo['nodes']},
            'en': {n[0]: n[4] for n in geo['nodes']},      # как узел назван в данных игры
            'near': near, 'forest': bool(geo.get('trees')),
            # с какими атрибутами начинает класс узла старта: {id узла: [сила, ловкость, интеллект]} (дерево героя)
            'starts': geo.get('starts') or {},
            # классы героя: {имя: {base: [сила, ловкость, интеллект], start: id узла старта, ascendancies: [{id, name}]}}
            'classes': {c['id']: c for c in geo.get('classes') or [] if isinstance(c, dict) and c.get('id')},
            # узлы, которые берут зачарованием амулета, и их рецепты (дерево героя; см. treegeo.anoints)
            'anoint': geo.get('anoint') or {}}


def check(versions, tree, geo):
    """Проверяет присланные версии. Возвращает ({id версии: [{id, attr?}]}, замечания)."""
    problems, out = [], {}
    known = {ph.get('id') for ph in (tree or {}).get('phases') or [] if isinstance(ph, dict)}
    if not isinstance(versions, list) or not versions:
        return {}, [tr('нет ни одной версии дерева')]
    for v in versions:
        if not (isinstance(v, dict) and isinstance(v.get('id'), str) and isinstance(v.get('nodes'), list)):
            problems.append(tr('версия записана не так: нужны id и список узлов'))
            continue
        vid = v['id']
        if vid not in known:
            problems.append(tr('версии «%s» в плане нет') % vid)
            continue
        if vid in out:
            problems.append(tr('версия «%s» прислана дважды') % vid)
            continue
        nodes = _nodes(vid, v['nodes'], geo, problems)
        if nodes is not None:
            out[vid] = nodes
    return (out if not problems else {}), problems


def _nodes(vid, raw, geo, problems):
    """Узлы одной версии: [{id, attr?, opt?}] или None, если с ними что-то не так (замечание — в problems).
    attr — атрибут узла «Характеристика» дерева героя; opt — номер выбранного варианта у узла атласа с
    выбором (сколько вариантов у узла, говорит geo['opts'], если они известны)."""
    if len(raw) > MAX_NODES:
        problems.append(tr('версия «%s»: узлов больше %d') % (vid, MAX_NODES))
        return None
    nodes, seen = [], set()
    for n in raw:
        nid = n.get('id') if isinstance(n, dict) else None
        kind = geo['kind'].get(nid) if isinstance(nid, str) else None
        if kind is None or kind == START:
            problems.append(tr('версия «%s»: узла «%s» нет в дереве') % (vid, nid))
            return None
        if nid in seen:
            problems.append(tr('версия «%s»: узел «%s» записан дважды') % (vid, nid))
            return None
        attr = n.get('attr')
        if attr is not None and (attr not in ATTRS or kind != ATTRIBUTE):
            problems.append(tr('версия «%s», узел «%s»: атрибут бывает только str, dex или int и только '
                            'у узла «Характеристика»') % (vid, nid))
            return None
        opt = n.get('opt')
        if opt is not None:
            top = (geo.get('opts') or {}).get(nid)
            if (isinstance(opt, bool) or not isinstance(opt, int) or opt < 1 or kind != CHOICE or not geo.get('forest')
                    or (top is not None and opt > top)):
                problems.append(tr('версия «%s», узел «%s»: вариант — это номер с единицы%s, и только у узла атласа '
                                'с выбором') % (vid, nid, tr(' до %d') % top if top else ''))
                return None
        # Порядок должен проходиться в игре: узел примыкает к взятому раньше, первый — к старту класса.
        # В атласе деревьев несколько: там узел может примыкать и к корню своего дерева.
        near = geo['near'].get(nid, ())
        by_root = (geo.get('forest') or not seen) and any(geo['kind'].get(x) == START for x in near)
        if not (by_root or any(x in seen for x in near)):
            problems.append(tr('версия «%s»: узел «%s» стоит раньше своих соседей — такой порядок '
                            'в игре не пройти') % (vid, nid))
            return None
        seen.add(nid)
        rec = {'id': nid, 'attr': attr} if attr else {'id': nid}
        if opt:
            rec['opt'] = opt
        nodes.append(rec)
    return nodes


MAX_ITEMS = 8        # узлов с предметов у одной версии


def _items(vid, raw, nodes, geo, slots, problems):
    """Узлы версии, которые дают предметы (зачарование амулета): [{id, slot}] или None, если с ними что-то не так
    (замечание — в problems). Узел — из тех, что берут зачарованием (карта дерева, раздел anoint); в пути версии его
    нет — очко на него не тратят; слот — слот билда (slots — их id; None — не проверять); на одном предмете один
    узел: новое зачарование заменяет прежнее."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        problems.append(tr('версия «%s»: узлы с предметов записаны не так') % vid)
        return None
    known = ((geo or {}).get('anoint') or {}).get('nodes') or {}
    path = {n['id'] for n in nodes}
    out, seen, per = [], set(), {}
    for x in raw:
        nid = x.get('id') if isinstance(x, dict) else None
        slot = x.get('slot') if isinstance(x, dict) else None
        if not isinstance(nid, str) or nid not in known:
            problems.append(tr('версия «%s»: узел «%s» зачарованием не берут') % (vid, nid))
            return None
        if nid in seen:
            problems.append(tr('версия «%s»: узел «%s» с предмета записан дважды') % (vid, nid))
            return None
        if nid in path:
            problems.append(tr('версия «%s»: узел «%s» и в пути версии, и с предмета — оставьте одно') % (vid, nid))
            return None
        if not isinstance(slot, str) or (slots is not None and slot not in slots):
            problems.append(tr('версия «%s», узел «%s»: в билде нет слота «%s»') % (vid, nid, slot))
            return None
        per[slot] = per.get(slot, 0) + 1
        if per[slot] > 1:
            problems.append(tr('версия «%s»: на предмете один узел — в слоте «%s» их больше') % (vid, slot))
            return None
        seen.add(nid)
        out.append({'id': nid, 'slot': slot})
    return out


def _without(out, ids, problems):
    """Запасная версия (поле without): действует вместо версии, пока узлов, которые та берёт с предметов, на надетых
    предметах нет (core.derive). Бывает только у версии с такими узлами; это другая версия того же набора; по цепочке
    запасных круга нет. None или пустое — запасной нет: версия действует и без узла на предмете."""
    names = {r['id']: r['name'] for r in out}
    nxt = {}
    for r in out:
        w = r.get('without')
        if w in (None, ''):
            r.pop('without', None)
            continue
        if not isinstance(w, str) or w == r['id'] or w not in ids:
            problems.append(tr('версия «%s»: запасной версии «%s» нет') % (r['name'], w))
        elif not r.get('items'):
            problems.append(tr('версия «%s»: запасная версия нужна только версии с узлами с амулета') % r['name'])
        else:
            nxt[r['id']] = w
    for start in nxt:
        seen, cur = set(), start
        while cur in nxt and cur not in seen:
            seen.add(cur)
            cur = nxt[cur]
        if cur in seen:
            problems.append(tr('версия «%s»: запасные версии ссылаются друг на друга по кругу') % names[start])
            break


def check_all(versions, used, geo, slots=None):
    """Проверяет ПОЛНЫЙ набор версий — так страница присылает дерево, когда версии создают, удаляют или
    переименовывают. Версий сколько угодно, у каждой своё имя. used — {id версии: [названия этапов билда,
    которые её назвали]}: такую версию из набора убрать нельзя — сначала этапу дают другую. slots — id слотов
    билда: к ним привязаны узлы с предметов (items). Возвращает (версии в присланном порядке:
    [{id, name, nodes, items?}], замечания); items — только если страница их прислала."""
    problems, out = [], []
    if not isinstance(versions, list) or not versions:
        return [], [tr('нет ни одной версии дерева')]
    if len(versions) > MAX_VERSIONS:
        return [], [tr('версий больше %d') % MAX_VERSIONS]
    ids = set()
    for v in versions:
        if not (isinstance(v, dict) and isinstance(v.get('id'), str) and isinstance(v.get('nodes'), list)):
            problems.append(tr('версия записана не так: нужны id и список узлов'))
            continue
        vid = v['id']
        if not RE_ID.fullmatch(vid):
            problems.append(tr('версия «%s»: id — латинские буквы, цифры, дефис') % vid)
            continue
        if vid in ids:
            problems.append(tr('версия «%s» прислана дважды') % vid)
            continue
        ids.add(vid)
        name = v.get('name').strip() if isinstance(v.get('name'), str) else ''
        if not name or len(name) > MAX_NAME:
            problems.append(tr('версия «%s»: нужно название не длиннее %d знаков') % (vid, MAX_NAME))
            continue
        nodes = _nodes(name, v['nodes'], geo, problems)
        items = _items(name, v.get('items'), nodes, geo, slots, problems) if nodes is not None else None
        if nodes is not None and items is not None:
            rec = dict({'id': vid, 'name': name, 'nodes': nodes}, **({'items': items} if 'items' in v else {}))
            if 'without' in v:
                rec['without'] = v['without']
            out.append(rec)
    _without(out, ids, problems)
    for vid, stages in (used or {}).items():
        if vid not in ids:
            problems.append(tr('версию «%s» убрать нельзя: она действует на этапе «%s» — сначала дайте этапу '
                            'другую (вкладка «Этапы»)') % (vid, '», «'.join(stages)))
    if problems:
        return [], problems
    return out, []


def records(nodes, names, geo):
    """Записи узлов для плана: id, название (как в игре, если оно известно), вид, выбранный атрибут
    («Характеристика» дерева героя) и номер выбранного варианта (узел атласа с выбором)."""
    out = []
    for n in nodes:
        rec = {'id': n['id'], 'name': names.get(n['id']) or geo['name'].get(n['id']) or n['id']}
        kind = KINDS.get(geo['kind'].get(n['id']))
        if kind:
            rec['kind'] = kind
        if n.get('attr'):
            rec['attr'] = n['attr']
        if n.get('opt'):
            rec['opt'] = n['opt']
        out.append(rec)
    return out


def known_names(tree, extra=None):
    """Названия узлов, как в игре: из лога (extra) и из уже записанного плана. План важнее: он выверен."""
    names = dict(extra or {})
    for ph in (tree or {}).get('phases') or []:
        for n in (ph.get('nodes') or []) + (ph.get('items') or []):
            if isinstance(n, dict) and n.get('id') and n.get('name'):
                names[n['id']] = n['name']
    return names


def apply(tree, versions, names, geo):
    """Раздел "tree" с новыми списками узлов у присланных версий; остальное в разделе не меняется."""
    new = copy.deepcopy(tree)
    for ph in new.get('phases') or []:
        if ph.get('id') in versions:
            ph['nodes'] = records(versions[ph['id']], names, geo)
    return new


def apply_all(tree, versions, names, geo, attr=None, drop_default=False):
    """Раздел "tree" с полным набором версий (после check_all). Поля версии идут как в файле: id, name,
    прочее, nodes; у прежней версии её прочие поля сохраняются. Атрибут дерева «по умолчанию» (поле attr
    раздела) — прошлое: drop_default убирает его (страница прислала атрибут каждого узла явно — см.
    with_default); attr — новое значение этого поля от страницы, которая ещё присылает его по-старому."""
    new = copy.deepcopy(tree)
    old = {ph.get('id'): ph for ph in new.get('phases') or [] if isinstance(ph, dict)}
    phases = []
    for v in versions:
        ph = {'id': v['id']}
        ph['name'] = v['name']
        for k, val in (old.get(v['id']) or {}).items():
            # узлы с предметов и запасная версия: прислала страница — пишутся её, нет — остаются прежние
            if k not in ('id', 'from', 'name', 'nodes') and not (k in ('items', 'without') and k in v):
                ph[k] = val
        if v.get('items'):
            # узел с предмета: id, название (как в игре) и слот, предмет которого его даёт
            ph['items'] = [{'id': x['id'], 'name': names.get(x['id']) or x['id'], 'slot': x['slot']} for x in v['items']]
        if v.get('without'):
            ph['without'] = v['without']      # запасная версия: пока узлов с предметов на предметах нет
        ph['nodes'] = records(v['nodes'], names, geo)
        phases.append(ph)
    if drop_default:
        new.pop('attr', None)
    elif attr in ATTRS:
        new['attr'] = attr
    new['phases'] = phases
    return new


def _dumps(x):
    return json.dumps(x, ensure_ascii=False)


def render(tree, key='tree'):
    """Текст раздела "tree" (или "atlas") в том виде, в каком он лежит в файле плана: узел — одна строка."""
    lines = ['  %s: {' % _dumps(key)]
    for k, v in tree.items():
        if k != 'phases':
            lines.append('    %s: %s,' % (_dumps(k), _dumps(v)))
    lines.append('    "phases": [')
    phases = tree.get('phases') or []
    for pi, ph in enumerate(phases):
        meta = ', '.join('%s: %s' % (_dumps(k), _dumps(v)) for k, v in ph.items() if k != 'nodes')
        lines.append('      {%s"nodes": [' % (meta + ', ' if meta else ''))
        nodes = ph.get('nodes') or []
        for ni, n in enumerate(nodes):
            lines.append('        %s%s' % (_dumps(n), ',' if ni < len(nodes) - 1 else ''))
        lines.append('      ]}%s' % (',' if pi < len(phases) - 1 else ''))
    lines.append('    ]')
    lines.append('  }')
    return lines


def _section_end(lines, start):
    """Строка, на которой кончается раздел верхнего уровня, начатый строкой start."""
    return next((i for i in range(start + 1, len(lines)) if lines[i] in ('  },', '  }')), None)


def splice(text, tree, key='tree'):
    """Текст файла плана с новым разделом key ("tree" или "atlas"). Всё остальное остаётся как было —
    иначе ValueError. Раздела ещё нет (атлас правят впервые) — он встаёт сразу за деревом героя, а если
    нет и его, то последним в файле."""
    eol = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(eol)
    starts = [i for i, ln in enumerate(lines) if ln == '  %s: {' % _dumps(key)]
    new = render(tree, key)
    before = json.loads(text)
    if len(starts) > 1 or (not starts and key in before) or (starts and key not in before):
        raise ValueError(tr('раздел «%s» записан непривычно — править его со страницы нельзя') % key)
    if starts:
        s = starts[0]
        e = _section_end(lines, s)
        if e is None:
            raise ValueError(tr('у раздела «%s» не найден конец') % key)
        if lines[e].endswith(','):
            new[-1] += ','
        out = eol.join(lines[:s] + new + lines[e + 1:])
    else:
        after_tree = [i for i, ln in enumerate(lines) if ln == '  "tree": {']
        e = _section_end(lines, after_tree[0]) if len(after_tree) == 1 else None
        if e is None:
            # в конец файла: перед закрывающей скобкой, прежний последний раздел получает запятую
            ends = [i for i, ln in enumerate(lines) if ln == '}']
            e = (ends[-1] if ends else 0) - 1
            while e >= 0 and not lines[e].strip():
                e -= 1
            if not ends or e < 0:
                raise ValueError(tr('файл плана записан непривычно — добавить в него раздел «%s» нельзя') % key)
        if lines[e].endswith(','):
            new[-1] += ','
        else:
            lines[e] += ','
        out = eol.join(lines[:e + 1] + new + lines[e + 1:])
    after = json.loads(out)
    rest = lambda d: {k: v for k, v in d.items() if k != key}   # noqa: E731
    order = list(before) == (list(after) if key in before else [k for k in after if k != key])
    if after.get(key) != tree or rest(before) != rest(after) or not order:
        raise ValueError(tr('после правки изменилось бы что-то ещё — файл не тронут'))
    return out


def save(path, tree, backup_dir=None, now=None, key='tree'):
    """Записывает раздел key ("tree" или "atlas") в файл плана. Прежний файл перед этим копируется
    в backup_dir."""
    path = Path(path)
    raw = path.read_bytes()
    bom = raw.startswith(b'\xef\xbb\xbf')
    out = splice(raw.decode('utf-8-sig'), tree, key)
    if backup_dir:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(now))
        shutil.copy2(path, backup_dir / ('%s.%s-%s%s' % (path.stem, key, stamp, path.suffix)))
        old = sorted(backup_dir.glob('%s.%s-*%s' % (path.stem, key, path.suffix)))
        for extra in old[:-KEEP_BACKUPS]:
            try:
                extra.unlink()
            except OSError:
                pass
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes((b'\xef\xbb\xbf' if bom else b'') + out.encode('utf-8'))
    os.replace(tmp, path)
    return out
