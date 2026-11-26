# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка языка страниц: план из комплекта программы на каждом её языке — одной командой.

    python -X utf8 planner/lang_pages.py [--client ru,en] [--langs ru,en,de,…] [--views play,ov=list,…]
                                         [--upto grotto] [--port N] [--planner <папка>] [--project <папка>]
                                         [--data-root <папка с catalog/data и knowledge>] [--out <папка>]

Что делает. Пробная папка (временная): план из комплекта (первый план в plans/ проекта) лежит в библиотеке так, как
его получает игрок, — «пришёл с программой», только просмотр; коды и названия фильтров вымышленные. Герой «Proba»
идёт по маршруту плана до шага --upto (по умолчанию «Грот Титанов»): заходит в зоны шагов, растёт в уровне, берёт
узлы дерева из плана, в испытании Сехем — узлы Восхождения, на двух картах прерывает попытку (выходит из игры на
карте и входит уже в новую её копию: «Разбор» показывает «Где больше попыток»). Строки лога — на языке клиента
(--client, по умолчанию русский и английский по очереди) и только из данных игры этого языка: шаблоны системных
строк, названия зон, классов и узлов. Сервер программы (server.py папки --planner) — на свободном порту 4771–4779,
Chrome — без окна (как у hostile_pages.py). Для каждого языка клиента и каждого языка страницы открываются виды:
«Игра» (раскрыты блоки, шаги, карты дерева), «Разбор» (последний порядок — «Где больше попыток»), список шага поверх
игры (раскрыт, как под Alt), все вкладки «Редактора» (раскрыты карточки). С вида берётся то, что видит игрок: текст
страницы, подсказки (title), подписи узлов на картах, значения полей.

Слово не на том языке:
  * страница не по-русски — кириллица (кроме названия языка в его списке);
  * страница не по-английски — английское название из игры вне скобок пары «Местное (English)», когда у клиента
    этого языка у названия есть своё: зона, узел дерева, предмет, камень, класс героя, монстр, задание
    (данные игры: catalog/data — слой языка и names-<язык>; русская страница так ловит «Spell Critical Damage»,
    немецкая при английском клиенте — «Clearfell»). Сверяется целая латинская фраза (и её части до и после «, » и
    «: »), а не слово внутри неё; слово, которым пользуется сам перевод программы на этот язык («Build»), и
    английское название второй строкой под местным (плитки умений) — не в счёт.
Что слово стоит не на месте, а нарочно (название плана, имя героя, названия фильтров — их дали люди), сюда не
попадает: в пробе они латиницей и не совпадают с названиями игры.

Итог — по языку клиента и языку страницы: сколько разных слов не на том языке и первые примеры с видом; подробности —
в JSON (--out). Код выхода 0 — чисто, 1 — найдены слова не на том языке, 2 — проверка не прошла (сервер, браузер).
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gamedata  # noqa: E402
import hostile  # noqa: E402
import hostile_pages as hp  # noqa: E402
import i18n  # noqa: E402
import planfiles  # noqa: E402
import planlib  # noqa: E402

HERO = 'Proba'
RESTART = ('mausoleum', 'keth')      # шаги, где герой прерывает попытку: «Разбор» показывает «Где больше попыток»
TABS = ('build', 'tree', 'route', 'stages', 'items', 'gems', 'other')
VIEWS = ([('play', '/', 'play'), ('review', '/review', 'review'), ('ov=list', '/?ov=list', 'list')]
         + [('admin#' + t, '/admin#' + t, 'admin') for t in TABS])
TAG = '0.5.5h'

# Что сделать на странице, чтобы показалось всё, что она показывает из плана (как у hostile_pages, без окна
# «О программе»): ничего не отмечается, не надевается и не правится.
ACTIONS = r'''
(async (kind) => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const SKIP = 'a, [data-fpage], [data-planfile], [data-cxpick], [data-cxrun], [data-cxgone], [data-cxrm], [data-cxyes], ' +
    '[data-cxadd], [data-cxsame], [data-goal], [data-move], [data-hold], [data-wear], [data-off], [data-set], [data-forget], ' +
    '[data-copydrop], [data-copyrow], [data-amark], [data-afrom], [data-atlasask], [data-hattr], [data-pendoff], [data-cfgv], ' +
    '[data-lang], [data-lgt], [data-leave], [data-gamepick], [data-plancopy], [data-cxnew], input, select, textarea';
  const click = async (sel, max = 40, pause = 40) => {
    let n = 0;
    for (const el of Array.from(document.querySelectorAll(sel))) {
      if (n >= max) break;
      if (!el.isConnected || el.matches(SKIP) || el.closest('a') || el.disabled) continue;
      el.click(); n++; await wait(pause);
    }
    return n;
  };
  if (kind === 'play') {
    await click('[data-open]', 60);
    await click('[data-peek]', 25, 60);
    await click('[data-strip]', 6, 80);
    await click('[data-map]', 8, 80);
    await click('[data-skill], [data-list], [data-jump], [data-atree]', 30);
    await click('[data-open]', 60);
  } else if (kind === 'review') {
    await click('[data-rvo], [data-open], [data-peek]', 40);
  } else if (kind === 'admin') {
    await click('[data-more], [data-rmore], [data-smore], [data-stopen], [data-treeopen], [data-tver], [data-tkind], [data-tmap]', 400, 15);
  } else if (kind === 'list') {
    if (window.ovArm) { window.ovArm(2); await wait(600); }
    await click('[data-open], [data-peek]', 20);
  }
  await wait(500);
  return true;
})
'''

# Что видит игрок: текст страницы, подсказки, подписи узлов на картах, значения полей. Список языков в шапке —
# названия языков на их же языке: не в счёт.
COLLECT = r'''(() => {
  // английское название второй строкой под местным (плитки умений: .ce) — часть пары «Местное (English)»
  for (const e of document.querySelectorAll('.ce')) if (e.textContent && !/^\(.*\)$/.test(e.textContent)) e.textContent = '(' + e.textContent + ')';
  const out = {text: document.body ? document.body.innerText : '', attrs: [], svg: [], fields: []};
  const lang = el => el.closest('[data-lang], .lgm, .lgl');
  for (const el of document.querySelectorAll('[title], [aria-label], [placeholder]')) {
    if (lang(el)) continue;
    for (const a of ['title', 'aria-label', 'placeholder']) if (el.hasAttribute(a) && el.getAttribute(a)) out.attrs.push(el.getAttribute(a));
  }
  for (const t of document.querySelectorAll('svg title')) if (t.textContent) out.svg.push(t.textContent);
  for (const f of document.querySelectorAll('input, textarea')) {
    if (['hidden', 'checkbox', 'radio', 'button', 'submit', 'range', 'number', 'color', 'file'].includes(f.type)) continue;
    if (f.value && f.offsetParent !== null) out.fields.push(f.value);
  }
  return out;
})()'''


# --- план из комплекта и герой «Proba» ---------------------------------------------------------------------

def bundled(project):
    """План из комплекта (первый в plans/ проекта): маршрут, билд, группы, метка. Коды фильтров — вымышленные
    (TrialAaN), названия — «Qx N»: их дали люди на сайте игры, и в пробе они не похожи ни на один язык."""
    lib = planlib.scan(project / 'plans')
    if not lib:
        raise SystemExit('в %s нет плана' % (project / 'plans'))
    rec = lib[0]
    parts = planfiles.read_parts(rec['path'], rec['manifest'])
    route, build = parts['route'], parts['build']
    codes = {}
    for s in route.get('steps') or []:
        if s.get('filter') and s['filter'] != 'none':
            s['filter'] = codes.setdefault(s['filter'], 'TrialAa%d' % (len(codes) + 1))
        if 'filterName' in s:
            s['filterName'] = 'Qx %s' % (s.get('filter') or '')[-1:]
    return route, build, list(rec['manifest'].get('groups') or []), rec['manifest'].get('uid') or 'a1b2c3d4e5f6'


def client_words(cat, client, geo):
    """Слова клиента из данных игры: (названия зон {код: …}, классы героя {English: …}, узлы {id: …})."""
    layer = ((cat or {}).get('lang') or {}).get(client) or {}
    areas = {code: ((layer.get('areas') or {}).get(code) if client != 'en' else None) or a.get('name') or code
             for code, a in ((cat or {}).get('areas') or {}).items() if isinstance(a, dict)}
    classes = dict(layer.get('heroClasses') or {})
    english = {n[0]: n[4] for n in (geo or {}).get('nodes') or () if isinstance(n, list) and len(n) > 4}
    local = ((gamedata.names_pack(cat, client) or {}).get('nodes') or {}) if client != 'en' else {}
    nodes = {nid: local.get(nid) or en for nid, en in english.items()}
    return areas, classes, nodes


def trial_log(cat, route, build, client, upto, geo, now=None):
    """Строки лога героя HERO: от первого шага маршрута до шага upto, на языке клиента client."""
    msg = gamedata.log_msgs(cat).get(client) or {}
    level_t = msg.get('LevelUp') or '{0} ({1}) is now level {2}'
    areas, classes, nodes = client_words(cat, client, geo)
    cat_areas = cat.get('areas') or {}
    hero = build.get('hero') or {}
    word = classes.get(hero.get('class'), hero.get('class') or 'Sorceress')
    asc_word = classes.get(hero.get('ascendancy'), hero.get('ascendancy') or word)
    phases = (build.get('tree') or {}).get('phases') or []
    plain = [n['id'] for ph in phases[:1] for n in ph.get('nodes') or () if isinstance(n, dict)
             and not str(n.get('id', '')).startswith('Ascendancy')]
    ascend = [n['id'] for ph in phases for n in ph.get('nodes') or () if isinstance(n, dict)
              and str(n.get('id', '')).startswith('Ascendancy')][:2]
    steps = route.get('steps') or []
    end = next((i for i, s in enumerate(steps) if s.get('id') == upto), len(steps) - 1)
    t = (now or time.time()) - 95 * (end + 2) - 60
    stamp = lambda x: time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(x))      # noqa: E731
    lines = [stamp(t) + ' 1 a [INFO Client 1] [HTTP2] User agent: PoE poe2_production/tags/%s Windows x64' % TAG]
    level, queue = 1, list(plain)
    for i, s in enumerate(steps[:end + 1]):
        code = s.get('zone')
        if code and code in cat_areas:
            t += 90
            lvl = (cat_areas[code] or {}).get('level') or 1
            lines += [stamp(t) + ' 1 a [DEBUG Client 1] Generating level %d area "%s" with seed %d' % (lvl, code, 1000 + i),
                      stamp(t + 1) + ' 1 a [INFO Client 1] [SCENE] Set Source [%s]' % areas.get(code, code)]
            if s.get('id') in RESTART:
                # прерванная попытка: выход на экран персонажей на карте и вход уже в новую её копию
                t += 40
                lines += [stamp(t) + ' 1 a [INFO Client 1] [SCENE] Set Source [(unknown)]',
                          stamp(t + 20) + ' 1 a [DEBUG Client 1] Generating level %d area "%s" with seed %d' % (lvl, code, 5000 + i),
                          stamp(t + 21) + ' 1 a [INFO Client 1] [SCENE] Set Source [%s]' % areas.get(code, code)]
                t += 20
            town = bool((cat_areas[code] or {}).get('town'))
            while not town and level < min(lvl + 1, 60):
                level += 1
                t += 2
                lines.append(stamp(t) + ' 1 a [INFO Client 1] : ' + level_t.format(HERO, word, level))
                if queue:
                    nid = queue.pop(0)
                    lines.append(stamp(t + 1) + ' 1 a [INFO Client 1] Successfully allocated passive skill id: %s, name: %s'
                                 % (nid, nodes.get(nid, nid)))
        if s.get('event') == 'ascend' and ascend:
            for nid in ascend:
                t += 2
                lines.append(stamp(t) + ' 1 a [INFO Client 1] Successfully allocated passive skill id: %s, name: %s'
                             % (nid, nodes.get(nid, nid)))
            word = asc_word
            ascend = []
    return lines


def prepare(out, project, cat, client, upto, geo):
    """Пробная папка одного языка клиента: библиотека с планом из комплекта (пришёл с программой), фильтры,
    настройки игры с языком клиента, лог героя."""
    for d in ('plans', 'runs', 'archive', 'OnlineFilters', 'logs'):
        (out / d).mkdir(parents=True, exist_ok=True)
    route, build, groups, uid = bundled(project)
    planlib.add(out / 'plans', hostile.bundle(route, build, groups, title=build.get('title') or 'Plan', uid=uid), '',
                uid=uid, extra={'received': {'file': '', 'at': planlib.stamp_text(), 'by': 'program'}})
    codes = sorted({s['filter'] for s in route.get('steps') or [] if s.get('filter') and s['filter'] != 'none'})
    for i, code in enumerate(codes, 1):
        (out / 'OnlineFilters' / code).write_text('#name:Qx %d\n#type:filter\nShow\n' % i, encoding='utf-8')
    (out / 'config.ini').write_text('[UI]\nitem_filter=%s\nlanguage=%s\n' % (codes[0] if codes else 'None', client),
                                    encoding='utf-8')
    lines = trial_log(cat, route, build, client, upto, geo)
    (out / 'logs' / 'Client.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return len(lines)


# --- что считается словом не на том языке -------------------------------------------------------------------

RE_CYR = re.compile(r'[А-Яа-яЁё][А-Яа-яЁё\-]*(?:[  ]+[А-Яа-яЁё][А-Яа-яЁё\-]*)*')
RE_PAREN = re.compile(r'\([^()]*\)')
# латиница — с буквами европейских языков: «Portões» — одно слово, а не «Port» и «ões»
LAT = "A-Za-zÀ-ÖØ-öø-ÿĀ-ſ"
RE_WORD = re.compile(r"[%s][%s0-9'’\-]*" % (LAT, LAT))
RE_PHRASE = re.compile(r"[%s][%s0-9'’\-]*(?:(?:, |: | )[%s][%s0-9'’\-]*)*" % (LAT, LAT, LAT, LAT))
RE_PATH = re.compile(r'\S*[\\/]\S*|\S+\.(?:txt|json|exe|md|ini)\b|https?://\S+')


def game_names(cat, lang, geos):
    """{английское название из игры: название на языке lang} — только где они разные: зоны, узлы деревьев (по id),
    базы, камни, уникальные предметы, классы героя и всё, что знают таблицы игры этого языка (names-<язык>)."""
    if lang == 'en':
        return {}
    out = {}
    layer = ((cat or {}).get('lang') or {}).get(lang) or {}
    pack = gamedata.names_pack(cat, lang) or {}
    for code, a in ((cat or {}).get('areas') or {}).items():
        loc = (layer.get('areas') or {}).get(code)
        if isinstance(a, dict) and a.get('name') and loc:
            out.setdefault(a['name'], loc)
    nodes = pack.get('nodes') or {}
    for geo in geos:
        for n in (geo or {}).get('nodes') or ():
            if isinstance(n, list) and len(n) > 4 and nodes.get(n[0]):
                out.setdefault(n[4], nodes[n[0]])
    for part in ('bases', 'gems', 'heroClasses'):
        for en, loc in (layer.get(part) or {}).items():
            if isinstance(loc, str):
                out.setdefault(en, loc)
    for loc, en in (layer.get('uniques') or {}).items():
        for e in (en if isinstance(en, list) else [en]):
            out.setdefault(e, loc)
    for en, loc in (pack.get('names') or {}).items():
        out.setdefault(en, loc)
    # слово, которым пользуется сам перевод программы на этот язык («Build» в немецком и португальском), — не чужое
    own = set()
    tab = i18n.table(lang) or {}
    for text in list((tab.get('texts') or {}).values()) + list((tab.get('plan') or {}).values()):
        for m in RE_PHRASE.finditer(str(text)):
            own.add(m.group())
            own.update(w.group() for w in RE_WORD.finditer(m.group()))
    # местное, которое отличается от английского только знаками («Mana :» во французских строках интерфейса), — то же слово
    same = lambda en, loc: re.sub(r'[\s:：.,]+', '', loc) == re.sub(r'[\s:：.,]+', '', en)      # noqa: E731
    return {en: loc for en, loc in out.items() if isinstance(en, str) and isinstance(loc, str) and loc and not same(en, loc)
            and len(en) >= 4 and RE_WORD.match(en) and en not in own}


def chunks(res):
    """Строки вида: (где, строка) — текст страницы по строкам, подсказки, подписи узлов, поля."""
    for line in (res.get('text') or '').splitlines():
        if line.strip():
            yield 'text', line.strip()
    for kind in ('attrs', 'svg', 'fields'):
        for s in res.get(kind) or ():
            for line in str(s).splitlines():
                if line.strip():
                    yield kind, line.strip()


def wrong_words(res, lang, names, allow=()):
    """Слова не на языке lang в собранном с вида res: [{kind: 'cyr' | 'name', word, where, line}]."""
    found = []
    langs = {x['name'] for x in i18n.languages()}
    for where, line in chunks(res):
        if lang != i18n.SOURCE:
            for m in RE_CYR.finditer(line):
                w = m.group()
                if w in langs or any(w in a for a in allow):
                    continue
                found.append({'kind': 'cyr', 'word': w, 'where': where, 'line': line[:160]})
        if not names:
            continue
        # Название из игры — целая латинская фраза (или её часть до / после «, » и «: »: «Ancient Ruin: Ring»), а не
        # слово внутри фразы: «Elemental» в «Elemental Offering» или «Passage» в немецком «Lichtlose Passage» — не оно.
        bare = RE_PATH.sub(' ', RE_PAREN.sub(' ', line))
        for m in RE_PHRASE.finditer(bare):
            phrase = m.group()
            for cand in [phrase] + [p for p in re.split(r', |: ', phrase) if p != phrase]:
                if cand in names and cand not in allow:
                    found.append({'kind': 'name', 'word': cand, 'want': names[cand], 'where': where, 'line': line[:160]})
                    if cand == phrase:
                        break
    return found


# --- проход ------------------------------------------------------------------------------------------------

def visit(dt, port, url, kind):
    dt.call('Page.navigate', url='about:blank')
    dt.pump(0.2)
    dt.events.clear()
    dt.call('Page.navigate', url='http://127.0.0.1:%d%s' % (port, url))
    ok = False
    ready = hp.READY if kind in ('play', 'review', 'admin') else \
        "document.readyState === 'complete' && !!document.querySelector('#app') && (document.body.innerText || '').length > 20"
    for _ in range(80):
        dt.pump(0.25)
        try:
            ok = bool(dt.js(ready, timeout=10))
        except Exception:     # noqa: BLE001 — страница ещё грузится
            ok = False
        if ok:
            break
    dt.pump(1.0)
    err = None
    try:
        dt.js('(%s)(%s)' % (ACTIONS.strip(), json.dumps(kind)), timeout=120)
    except Exception as e:     # noqa: BLE001 — действия не прошли: собираем то, что есть
        err = str(e)[:300]
    dt.pump(0.5)
    res = dt.js(COLLECT) or {}
    res['ready'], res['actionError'] = ok, err
    return res


def run_client(args, project, planner, cat, geos, client, langs, views):
    out = Path(tempfile.mkdtemp(prefix='langpages-%s-' % client, dir=args.out))
    n = prepare(out, project, cat, client, args.upto, geos[0])
    port = args.port or hp.free_port()
    server = hp.start_server(planner, out, port, Path(args.data_root))
    chrome, ws = hp.start_chrome(out)
    rows = []
    try:
        dt = hp.DevTools(ws)
        for domain in ('Page', 'Runtime', 'Log', 'Network'):
            dt.call(domain + '.enable')
        dt.call('Network.setBlockedURLs', urls=['*/api/open*', '*/api/game*', 'https://*', 'http://localhost*', 'ws://*'])
        dt.call('Emulation.setDeviceMetricsOverride', width=1280, height=900, deviceScaleFactor=1, mobile=False)
        script = None
        for lang in langs:
            if script:
                dt.call('Page.removeScriptToEvaluateOnNewDocument', identifier=script)
            script = dt.call('Page.addScriptToEvaluateOnNewDocument',
                             source="try { localStorage.setItem('lang', %s); } catch (e) {}" % json.dumps(lang))['identifier']
            names = game_names(cat, lang, geos)
            for name, url, kind in views:
                res = visit(dt, port, url, kind)
                bad = wrong_words(res, lang, names, args.allow)
                rows.append({'client': client, 'lang': lang, 'view': name, 'ready': res['ready'],
                             'actionError': res['actionError'], 'chars': len(res.get('text') or ''), 'found': bad})
                uniq = sorted({(b['kind'], b['word']) for b in bad})
                print('  клиент %-2s · страница %-2s · %-12s %s' % (
                    client, lang, name, ('не на том языке: %d — %s' % (len(uniq), ', '.join(w for _, w in uniq[:6]))
                                         if uniq else 'чисто') + ('' if res['ready'] else ' · СТРАНИЦА НЕ ГОТОВА')),
                      flush=True)
    finally:
        try:
            chrome.terminate()
        except Exception:     # noqa: BLE001
            pass
        server.terminate()
        try:
            server.wait(10)
            chrome.wait(10)
        except Exception:     # noqa: BLE001
            pass
        shutil.rmtree(out / 'chrome', ignore_errors=True)
    return rows, n, out


def main(argv=None):
    ap = argparse.ArgumentParser(description='Проверка языка страниц: план из комплекта на каждом языке программы')
    ap.add_argument('--planner', default=str(HERE), help='папка planner, чей сервер и страницы проверяются')
    ap.add_argument('--project', default=str(HERE.parent), help='папка проекта: план из комплекта (plans/)')
    ap.add_argument('--data-root', help='папка с catalog/data и knowledge (по умолчанию — --project)')
    ap.add_argument('--client', default='ru,en', help='языки клиента игры через запятую (по умолчанию ru,en)')
    ap.add_argument('--langs', help='языки страницы через запятую (по умолчанию все языки программы)')
    ap.add_argument('--views', help='только эти виды (через запятую): ' + ', '.join(v[0] for v in VIEWS))
    ap.add_argument('--upto', default='grotto', help='шаг маршрута, до которого дошёл герой (id)')
    ap.add_argument('--port', type=int, help='порт пробного сервера (по умолчанию — первый свободный из 4771–4779)')
    ap.add_argument('--out', help='куда положить пробные папки и отчёт (по умолчанию — временная папка)')
    ap.add_argument('--allow', default='', help='слова, которые не в счёт (через |)')
    args = ap.parse_args(argv)
    args.allow = tuple(x for x in args.allow.split('|') if x)
    project, planner = Path(args.project).resolve(), Path(args.planner).resolve()
    args.data_root = str(Path(args.data_root).resolve() if args.data_root else project)
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
    else:
        args.out = tempfile.mkdtemp(prefix='langpages-')
    cat = gamedata.load(Path(args.data_root) / 'catalog' / 'data')
    geos = [json.loads((planner / 'static' / f).read_text(encoding='utf-8')) for f in ('tree.json', 'atlas.json')]
    langs = args.langs.split(',') if args.langs else [x['code'] for x in i18n.languages()]
    views = [v for v in VIEWS if not args.views or v[0] in args.views.split(',')]
    report, total = {'planner': str(planner), 'catalog': cat.get('version'), 'upto': args.upto, 'rows': []}, 0
    for client in args.client.split(','):
        rows, n, folder = run_client(args, project, planner, cat, geos, client, langs, views)
        report['rows'] += rows
        print('клиент %s: строк лога %d, пробная папка %s' % (client, n, folder), flush=True)
    summary = {}
    for r in report['rows']:
        key = '%s/%s' % (r['client'], r['lang'])
        s = summary.setdefault(key, {'words': set(), 'views': 0, 'notReady': 0})
        s['views'] += 1
        s['notReady'] += 0 if r['ready'] else 1
        s['words'] |= {(b['kind'], b['word']) for b in r['found']}
    print('\nИтог (клиент/страница: разных слов не на том языке):')
    for key, s in summary.items():
        total += len(s['words'])
        print('  %-6s %4d%s%s' % (key, len(s['words']), '' if not s['words'] else '  — ' + ', '.join(
            w for _, w in sorted(s['words'])[:8]), '' if not s['notReady'] else '  · не готово видов: %d' % s['notReady']))
    report['summary'] = {k: {'words': sorted(list(w) for w in s['words']), 'views': s['views'], 'notReady': s['notReady']}
                         for k, s in summary.items()}
    path = Path(args.out) / 'lang-report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    not_ready = sum(s['notReady'] for s in summary.values())
    print('Всего разных слов не на том языке: %d; видов, которые не нарисовались: %d. Отчёт: %s' % (total, not_ready, path))
    return 2 if not_ready else (1 if total else 0)


if __name__ == '__main__':
    sys.exit(main())
