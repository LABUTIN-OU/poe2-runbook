# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Инструмент одобрения планов: каталог одобренных планов для сайта (site/plans) — его берёт программа (plancat.py).
Ничего никуда не отправляет: пишет файлы в site/plans, а на сайт они попадают вместе с сайтом.

    python -X utf8 release/plans.py add <файл плана> --author "Имя" [--author-url https://…]
            [--summary-ru "…" --summary-en "…"] [--changed-ru "…" --changed-en "…"] [--tags hc,ssf] [--langs ru]
            [--game 0.5.5] [--date ГГГГ-ММ-ДД]
        Принимает файл плана тем же строгим приёмом, что программа (planlib.parse_bundle), открывает его так же, как
        программа, и прогоняет проверку плана (planner/buildcheck.py; catalog/check_plan.py — если в плане есть строки
        аффиксов с тирами, записанными руками). Печатает итог для одобряющего: что за план, для какой игры, сколько шагов
        и целей, замечания проверки. Отказывает, если в текстах плана есть разметка или ссылки не http(s), если у плана
        нет метки (uid) или названия, если у этой метки в каталоге уже другой автор. Кладёт файл в
        site/plans/<uid>/<версия>.plan (версия — следующая по счёту для этой метки), обновляет и подписывает
        site/plans/index.json (подпись — index.json.sig). Имя автора плана — только отсюда (--author): в файле плана его
        нет. Класс и восхождение — из самого плана, версия игры — данных игры программы (--game — другая). «Что
        изменилось» обязательно для второй и следующих версий; у первой — «Первая версия».
    python -X utf8 release/plans.py remove <uid>
        Убирает план из каталога (файлы его версий остаются в site/plans/<uid>: счёт версий продолжится; у игроков
        поставленный план остаётся — только без новых версий).
    python -X utf8 release/plans.py list
        Что в каталоге.
    python -X utf8 release/plans.py verify
        Проверяет site/plans тем же кодом и ключом, что программа: подпись каталога, каждый файл плана — размер, SHA-256,
        метка и приём плана.

Подпись — тем же ключом и тем же кодом, что у файла обновления (release/publish.py: ключ автора
%USERPROFILE%\\.poe2runbook\\release-key.pem, открытый ключ в planner/updatekey.py). Перед записью каталог проверяется
кодом программы (plancat.read_index): программа такой не примет — он не пишется. Для проверок: --key, --site, --planner,
--root — другие места.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent          # release/
ROOT = HERE.parent                               # папка проекта
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'planner'))
import publish  # noqa: E402 — ключ и подпись: тот же код, что у файла обновления
from publish import Stop  # noqa: E402
import appversion  # noqa: E402
import planlib  # noqa: E402
import planguard  # noqa: E402
import plancat  # noqa: E402
import signed  # noqa: E402

SITE = ROOT / 'site' / 'plans'
# Где лежат файлы планов на сайте: https://poe2.labutin.gg/plans/<uid>/<версия>.plan — рядом с каталогом
BASE_URL = plancat.INDEX_URL.rsplit('/', 1)[0] + '/'
FIRST = {'ru': 'Первая версия.', 'en': 'The first version.'}
LANGS = ('ru', 'en')

# Разметка в тексте плана: тег (<b>, </b>, <!--, <?xml) или знак-ссылка HTML (&amp;, &#60;)
RE_MARKUP = re.compile(r'<\s*[A-Za-z!/?]|&#?[A-Za-z0-9]{1,12};')
# Ссылка: схема перед двоеточием («javascript:», «ftp://»); http и https — можно
RE_SCHEME = re.compile(r'(?<![A-Za-z0-9+.\-])([A-Za-z][A-Za-z0-9+.\-]{1,30}):')
DANGER = {'javascript', 'vbscript', 'livescript', 'mocha', 'data', 'file', 'blob', 'about', 'jar', 'view-source', 'mailto',
          'tel', 'sms', 'chrome', 'chrome-extension', 'intent', 'ftp', 'ws', 'wss', 'smb', 'res', 'ms-settings'}


# --- тексты плана -------------------------------------------------------------------------------------------------

def text_problem(s):
    """Что не так с текстом для каталога: разметка, ссылка не http(s); всё хорошо — ''."""
    if RE_MARKUP.search(s):
        return 'разметка'
    for m in RE_SCHEME.finditer(s):
        scheme, rest = m.group(1).lower(), s[m.end():m.end() + 2]
        if scheme in ('http', 'https'):
            continue
        if rest.startswith('//') or scheme == 'javascript' or scheme.startswith('ms-') \
                or (scheme in DANGER and rest[:1] and not rest[:1].isspace()):
            return 'ссылка %s:' % scheme
    return ''


def plan_text_problems(obj, where):
    """Тексты плана (все строки маршрута и билда, и ключи, и значения) с разметкой или ссылкой не http(s): [(место, что)]."""
    out, stack = [], [(obj, where)]
    while stack:
        x, place = stack.pop()
        if isinstance(x, str):
            why = text_problem(x)
            if why:
                out.append((place, why))
        elif isinstance(x, dict):
            for k, v in x.items():
                why = text_problem(str(k))
                if why:
                    out.append((place + '.' + str(k), why))
                stack.append((v, '%s.%s' % (place, k)))
        elif isinstance(x, list):
            stack.extend((v, '%s[%d]' % (place, i)) for i, v in enumerate(x))
    return sorted(out)


def one_line(text, name, limit):
    """Текст для каталога: одна строка простого текста — иначе отказ."""
    if text is None:
        return None
    if any(c in text for c in '\r\n\t') or planguard.RE_BAD.search(text):
        raise Stop('%s: одна строка простого текста, без переводов строк и управляющих знаков' % name)
    text = ' '.join(text.split())
    if not text:
        raise Stop('%s: пусто' % name)
    if len(text) > limit:
        raise Stop('%s: длиннее %d знаков (%d)' % (name, limit, len(text)))
    why = text_problem(text)
    if why:
        raise Stop('%s: в тексте %s — нельзя' % (name, why))
    return text


def pair(ru, en, name, limit):
    """{ru, en} из двух текстов: оба или ни одного."""
    if (ru is None) != (en is None):
        raise Stop('%s — на обоих языках сразу: %s-ru и %s-en' % (name, name, name))
    if ru is None:
        return None
    return {'ru': one_line(ru, name + '-ru', limit), 'en': one_line(en, name + '-en', limit)}


# --- каталог на диске ---------------------------------------------------------------------------------------------

def read_site(site, planner):
    """Каталог в site (если есть): (документ как записан, байты) — подпись проверена кодом программы и ключом,
    вписанным в программу. Нет каталога — (None, None)."""
    site = Path(site)
    path = site / 'index.json'
    if not path.exists():
        return None, None
    try:
        data, sig = path.read_bytes(), (site / 'index.json.sig').read_bytes()
    except OSError as e:
        raise Stop('каталог не читается: %s' % e) from None
    der = publish.program_key(planner)
    try:
        plancat.read_index(data, sig, signed.public_point(der) if der else None)
    except plancat.Refused as e:
        raise Stop('каталог %s не проходит проверку программы (%s %s) — разберитесь с ним руками' % (path, e.code, e.detail)) from None
    return json.loads(data.decode('utf-8')), data


def versions_on_disk(site, uid):
    """Номера версий плана uid, файлы которых лежат в site/<uid>/."""
    out = []
    for p in (Path(site) / uid).glob('*.plan') if (Path(site) / uid).is_dir() else ():
        if re.fullmatch(r'[1-9]\d{0,5}', p.stem):
            out.append(int(p.stem))
    return out


def write_index(doc, site, key, planner):
    """index.json и подпись — в site. Перед записью — проверка кодом программы. Ответ — записанные байты."""
    data = (json.dumps(doc, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
    point_der = publish.program_key(planner)
    if point_der is None:
        raise Stop('в программе нет открытого ключа (planner/updatekey.py): сначала release/publish.py keygen')
    signer = publish.public_der(key)
    if signer != point_der:
        raise Stop('ключ %s — не тот, что вписан в программу (отпечатки %s и %s): программа каталог не примет'
                   % (key, publish.fingerprint(signer), publish.fingerprint(point_der)))
    sig = publish.sign(data, key)
    try:
        plancat.read_index(data, sig, signed.public_point(point_der))          # как прочтёт программа
    except plancat.Refused as e:
        raise Stop('программа этот каталог не примет (%s %s) — не записан' % (e.code, e.detail)) from None
    site = Path(site)
    site.mkdir(parents=True, exist_ok=True)
    for name, body in (('index.json', data), ('index.json.sig', sig + b'\n')):
        (site / (name + '.tmp')).write_bytes(body)
    os.replace(site / 'index.json.tmp', site / 'index.json')
    os.replace(site / 'index.json.sig.tmp', site / 'index.json.sig')
    return data


# --- проверка плана, как его откроет программа ----------------------------------------------------------------------

def open_plan(bundle, root):
    """План, как его откроет программа: временная библиотека с одним планом (planlib.add), сервер программы читает его
    (server.App). Ответ: (app — план в app.plan, что не так — app.plan_problems и app.plan_error; временная папка)."""
    import server
    tmp = Path(tempfile.mkdtemp(prefix='poe2runbook-approve-'))
    pid = planlib.add(tmp / 'plans', bundle, 'approve.plan')
    app = server.App(None, tmp / 'plans' / pid / planlib.MANIFEST, tmp / 'runs', catalog_dir=Path(root) / 'catalog' / 'data',
                     knowledge_dir=Path(root) / 'knowledge', backup_dir=tmp / 'backup')
    app.load_plan()
    return app, tmp


def check_plan(bundle, root):
    """Проверка плана: (итог {steps, routeGoals, buildGoals, hero}, замечания [строки], ошибка плана или None, вывод
    catalog/check_plan.py или пояснение)."""
    import buildcheck
    route, build = json.loads(bundle['route']), json.loads(bundle['build'])
    app, tmp = open_plan(bundle, root)
    try:
        if app.plan_error:
            return None, [], app.plan_error, ''
        found = buildcheck.run(app.catalog, app.plan, app.tree_lines(), app.tree_geo('tree'), app.plan_problems, 'ru')
        lines = []
        for f in found:
            where = ' · '.join(str(x) for x in (f.get('what'), f.get('where')) if x)
            lines.append('%s%s%s' % ('надо править: ' if f.get('level') == 'bad' else 'заметка: ', f.get('text'),
                                     ' (%s)' % where if where else ''))
        hero = build.get('hero') or {}
        ru = ((((app.base_catalog or {}).get('lang') or {}).get('ru') or {}).get('heroClasses') or {})
        words = [('%s (%s)' % (ru[x], x) if ru.get(x) and ru[x] != x else x) for x in (hero.get('class'), hero.get('ascendancy')) if x]
        info = {'steps': len(app.plan.get('steps') or []), 'routeGoals': len(route.get('goals') or []),
                'buildGoals': len(build.get('goals') or []), 'hero': hero, 'heroWords': ' · '.join(words) or 'класс не назван'}
        # catalog/check_plan.py сверяет тиры строк аффиксов, записанные руками (раздел affixes старого вида плана)
        if isinstance(route.get('affixes'), dict) or isinstance(build.get('affixes'), dict):
            import planfiles
            raw = json.loads((tmp / 'plans').joinpath(next(p.name for p in (tmp / 'plans').iterdir()), planlib.MANIFEST)
                             .read_text(encoding='utf-8'))
            composed, _ = planfiles.compose(raw, route, build, app.marks)
            plan_file = tmp / 'composed.json'
            plan_file.write_text(json.dumps(composed, ensure_ascii=False), encoding='utf-8')
            done = subprocess.run([sys.executable, '-X', 'utf8', str(Path(root) / 'catalog' / 'check_plan.py'), '--plan',
                                   str(plan_file)], capture_output=True, text=True, encoding='utf-8', errors='replace')
            tiers = (done.stdout + done.stderr).strip()
        else:
            tiers = 'catalog/check_plan.py: строк аффиксов с тирами, записанными руками, в плане нет — сверять нечего'
        return info, lines, None, tiers
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# --- команды ------------------------------------------------------------------------------------------------------

def read_plan_file(path):
    """Файл плана -> (словарь файла плана в виде, как его пишет программа, маршрут, билд). Приём — как у программы."""
    try:
        text = Path(path).read_bytes().decode('utf-8-sig')
    except (OSError, UnicodeDecodeError) as e:
        raise Stop('файл плана не читается: %s' % e) from None
    try:
        data = json.loads(text, parse_constant=plancat._no_constant)
    except (ValueError, RecursionError):
        raise Stop('это не файл плана: в нём не JSON') from None
    try:
        route_text, build_text, meta = planlib.parse_bundle(data)
    except ValueError as e:                     # и planguard.Refused
        raise Stop('программа этот план не примет: %s' % e) from None
    if not meta['uid']:
        raise Stop('у плана нет метки (uid): по ней программа узнаёт его новые версии — сохраните план в программе заново')
    build = json.loads(build_text)
    title = build.get('title').strip() if isinstance(build.get('title'), str) else ''
    if not title:
        raise Stop('у плана нет названия')
    bundle = {'format': planlib.FORMAT, 'version': 1, 'uid': meta['uid'], 'title': title, 'groups': meta['groups'],
              'route': route_text, 'build': build_text}
    return bundle, json.loads(route_text), build


def detect_langs(route, build):
    """На каком языке тексты автора плана: по письму (кириллица — ru, кана — ja, хангыль — ko, тайское — th), иначе en."""
    blob = json.dumps([route.get('steps'), build.get('title'), build.get('goals')], ensure_ascii=False)
    for code, rx in (('ru', '[А-Яа-яЁё]'), ('ja', '[ぁ-ゟ゠-ヿ]'), ('ko', '[가-힣]'), ('th', '[ก-๛]')):
        if re.search(rx, blob):
            return [code]
    return ['en']


def add(path, author, author_url=None, summary=None, changed=None, tags=None, langs=None, game=None, day=None,
        key=publish.KEY, site=SITE, planner=publish.PLANNER, root=ROOT, out=print):
    """Одобрить план: файл версии — в site/<uid>/<версия>.plan, запись — в каталог, каталог подписан. Ответ — запись."""
    bundle, route, build = read_plan_file(path)
    uid = bundle['uid']
    bad = plan_text_problems(route, 'маршрут') + plan_text_problems(build, 'билд')
    why = text_problem(bundle['title'])
    if why:
        bad.insert(0, ('название', why))
    if bad:
        raise Stop('в текстах плана %s — такой план в каталог не берётся: %s%s' % (
            'разметка или ссылка не http(s)', '; '.join('%s — %s' % b for b in bad[:6]),
            ' (и ещё %d)' % (len(bad) - 6) if len(bad) > 6 else ''))
    name = one_line(author, '--author', plancat.NAME_MAX)
    if not name:
        raise Stop('--author: имя автора плана обязательно')
    if author_url is not None and plancat.web_url(author_url) is None:
        raise Stop('--author-url: только адрес http:// или https:// (без пробелов, имени и пароля): %s' % author_url)
    doc, _ = read_site(site, planner)
    doc = doc or {'format': plancat.FORMAT, 'v': 1, 'updated': '', 'plans': []}
    had = next((p for p in doc.get('plans') or [] if isinstance(p, dict) and p.get('uid') == uid), None)
    if had is not None:
        was = ((had.get('author') or {}).get('name') or '') if isinstance(had.get('author'), dict) else ''
        if was != name:
            raise Stop('у плана с этой меткой (%s) в каталоге автор «%s», а не «%s»: план другого автора — другой план '
                       '(его автор делает свой план через «Новый план» и присылает его файл)' % (uid, was, name))
    version = max([had['version'] if had and type(had.get('version')) is int else 0] + versions_on_disk(site, uid)) + 1
    changed = changed or (FIRST if version == 1 else None)
    if changed is None:
        raise Stop('что изменилось в версии %d — обязательно: --changed-ru и --changed-en (это видят игроки до «Обновить»)'
                   % version)
    info, notes, error, tiers = check_plan(bundle, root)
    if error:
        raise Stop('программа этот план не откроет: %s' % error)
    made = appversion.stem((Path(root) / 'catalog' / 'data' / 'current.txt').read_text(encoding='utf-8').strip())
    game = game or made
    if not game or not plancat.RE_GAME.fullmatch(game):
        raise Stop('--game: версия игры вида 0.5.5')
    data = planlib.bundle_bytes(bundle)
    if len(data) > plancat.MAX_PLAN:
        raise Stop('файл плана больше %d байт' % plancat.MAX_PLAN)
    day = day or datetime.date.today().isoformat()
    hero = info['hero']
    entry = {'uid': uid, 'version': version, 'title': {lang: bundle['title'] for lang in LANGS},
             'author': dict({'name': name}, **({'url': author_url} if author_url else {})), 'game': game,
             'class': hero.get('class') or '', 'ascendancy': hero.get('ascendancy') or '',
             'tags': tags if tags is not None else ((had or {}).get('tags') or []),
             'langs': langs or detect_langs(route, build),
             'summary': summary or ((had or {}).get('summary') or {}), 'changed': changed, 'published': day,
             'file': {'url': '%s%s/%d.plan' % (BASE_URL, uid, version), 'size': len(data),
                      'sha256': hashlib.sha256(data).hexdigest()}}
    for k in ('tags', 'langs'):
        if any(not isinstance(x, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,23}', x) for x in entry[k]):
            raise Stop('--%s: слова из латинских букв, цифр и «-» через запятую' % k)
    if not entry['class']:
        del entry['class']
    if not entry['ascendancy']:
        del entry['ascendancy']
    plans = [p for p in doc.get('plans') or [] if not (isinstance(p, dict) and p.get('uid') == uid)]
    at = next((i for i, p in enumerate(doc.get('plans') or []) if isinstance(p, dict) and p.get('uid') == uid), len(plans))
    plans.insert(at, entry)
    doc = dict(doc, updated=day, plans=plans)
    # файл версии — раньше каталога: каталог не назовёт файл, которого нет
    folder = Path(site) / uid
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('%d.plan' % version)
    if target.exists():
        raise Stop('%s уже есть — версия %d занята' % (target, version))
    (folder / ('%d.plan.tmp' % version)).write_bytes(data)
    os.replace(folder / ('%d.plan.tmp' % version), target)
    try:
        write_index(doc, site, key, planner)
    except Stop:
        target.unlink()
        raise
    out('План: «%s» (метка %s), версия %d%s' % (bundle['title'], uid, version, ' — новая версия' if had else ' — новый в каталоге'))
    out('Автор плана в каталоге: %s%s' % (name, ' (%s)' % author_url if author_url else ''))
    out('Герой: %s · игра %s (данные игры программы — %s)' % (info['heroWords'], game, made))
    out('Шагов: %d · целей: %d (маршрута %d, билда %d)' % (info['steps'], info['routeGoals'] + info['buildGoals'],
                                                          info['routeGoals'], info['buildGoals']))
    out('Проверка плана: %s' % ('замечаний нет' if not notes else 'замечаний %d' % len(notes)))
    for line in notes:
        out('  · %s' % line)
    out(tiers)
    out('Тексты плана: разметки и ссылок не http(s) нет')
    out('Записано: %s (%d байт, SHA-256 %s)' % (target, len(data), entry['file']['sha256']))
    out('Записано: %s и index.json.sig — подпись сходится, программа каталог примет' % (Path(site) / 'index.json'))
    out('На сайт каталог попадёт вместе с сайтом (папка site/plans).')
    return entry


def remove(uid, key=publish.KEY, site=SITE, planner=publish.PLANNER, out=print):
    doc, _ = read_site(site, planner)
    had = next((p for p in (doc or {}).get('plans') or [] if isinstance(p, dict) and p.get('uid') == uid), None)
    if had is None:
        raise Stop('плана с меткой %s в каталоге нет' % uid)
    doc = dict(doc, updated=datetime.date.today().isoformat(),
               plans=[p for p in doc['plans'] if not (isinstance(p, dict) and p.get('uid') == uid)])
    write_index(doc, site, key, planner)
    title = plancat.in_lang(update_texts(had.get('title')), 'ru')
    out('Убран из каталога: «%s» (метка %s), была версия %s' % (title, uid, had.get('version')))
    out('Файлы версий остались в %s: следующая версия этой метки продолжит счёт. У игроков поставленный план остаётся — '
        'без новых версий.' % (Path(site) / uid))
    return had


def update_texts(value):
    import update
    return update._texts(value, plancat.TITLE_MAX, True)


def verify(site=SITE, planner=publish.PLANNER, out=print):
    """site — как его проверит программа. Ответ — число проблем."""
    site = Path(site)
    try:
        data, sig = (site / 'index.json').read_bytes(), (site / 'index.json.sig').read_bytes()
    except OSError as e:
        raise Stop('нет файла: %s' % e) from None
    der = publish.program_key(planner)
    try:
        doc = plancat.read_index(data, sig, signed.public_point(der) if der else None)
    except plancat.Refused as e:
        raise Stop('программа этот каталог НЕ примет: %s %s' % (e.code, e.detail)) from None
    raw = json.loads(data.decode('utf-8'))
    out('Подпись сходится, программа каталог примет: планов %d (в файле записей %d), каталог от %s'
        % (len(doc['plans']), len(raw.get('plans') or []), doc['updated'] or '?'))
    bad = len(raw.get('plans') or []) - len(doc['plans'])
    if bad:
        out('ВНИМАНИЕ: записей, которые программа пропустит, — %d' % bad)
    for e in doc['plans']:
        want = '%s%s/%d.plan' % (BASE_URL, e['uid'], e['version'])
        local = site / e['uid'] / ('%d.plan' % e['version'])
        head = '«%s» (%s) версия %d, автор %s' % (plancat.in_lang(e['title'], 'ru'), e['uid'], e['version'], e['author']['name'])
        try:
            if e['url'] != want:
                raise Stop('адрес файла %s, а должен быть %s' % (e['url'], want))
            try:
                body = local.read_bytes()
            except OSError:
                raise Stop('нет файла %s' % local) from None
            try:
                planlib.parse_bundle(plancat.read_plan(body, e))
            except plancat.Refused as x:
                raise Stop('файл не сходится с каталогом (%s %s)' % (x.code, x.detail)) from None
            except ValueError as x:
                raise Stop('программа план не примет: %s' % x) from None
        except Stop as x:
            bad += 1
            out('НЕ ТАК: %s — %s' % (head, x))
        else:
            out('ок: %s — %d байт, SHA-256 сходится' % (head, e['size']))
    return bad


def show(site=SITE, planner=publish.PLANNER, out=print):
    doc, _ = read_site(site, planner)
    if doc is None:
        out('Каталога ещё нет: %s' % (Path(site) / 'index.json'))
        return
    out('Каталог от %s, планов: %d' % (doc.get('updated') or '?', len(doc.get('plans') or [])))
    for p in doc.get('plans') or []:
        e = plancat._entry(p)
        if e is None:
            out('  (запись, которую программа пропустит: %s)' % str(p)[:120])
            continue
        out('  %s · «%s» · версия %d от %s · %s · игра %s · %s%s · %d байт' % (
            e['uid'], plancat.in_lang(e['title'], 'ru'), e['version'], e['published'] or '?', e['author']['name'],
            e['game'] or '?', e['cls'] or '—', ' · ' + e['asc'] if e['asc'] else '', e['size']))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description='Каталог одобренных планов PoE2 Runbook (ничего не отправляет)')
    ap.add_argument('--key', default=str(publish.KEY), help='закрытый ключ автора программы (PEM)')
    ap.add_argument('--planner', default=str(publish.PLANNER), help='папка программы с updatekey.py')
    ap.add_argument('--site', default=str(SITE), help='папка каталога (site/plans)')
    ap.add_argument('--root', default=str(ROOT), help='папка проекта: данные игры (catalog/data) и справочник (knowledge)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('add', help='одобрить план: файл плана — в каталог')
    a.add_argument('plan', help='файл плана (*.plan.json — «Скачать файл плана» в редакторе)')
    a.add_argument('--author', required=True, help='имя автора плана, как его видят игроки')
    a.add_argument('--author-url', help='страница автора: http:// или https://')
    for name in ('summary', 'changed'):
        for lang in LANGS:
            a.add_argument('--%s-%s' % (name, lang))
    a.add_argument('--tags', help='метки через запятую: hc,ssf')
    a.add_argument('--langs', help='на каком языке тексты автора плана, через запятую: ru (по умолчанию — по письму)')
    a.add_argument('--game', help='версия игры, для которой план (по умолчанию — данных игры программы)')
    a.add_argument('--date', help='день версии ГГГГ-ММ-ДД (по умолчанию — сегодня)')
    r = sub.add_parser('remove', help='убрать план из каталога')
    r.add_argument('uid')
    sub.add_parser('list', help='что в каталоге')
    sub.add_parser('verify', help='проверить site/plans тем же кодом, что программа')
    args = ap.parse_args(argv)
    try:
        if args.cmd == 'add':
            if args.date and not plancat.RE_DAY.fullmatch(args.date):
                raise Stop('--date: ГГГГ-ММ-ДД')
            split = lambda v: [x.strip() for x in v.split(',') if x.strip()] if v is not None else None   # noqa: E731
            add(args.plan, args.author, args.author_url,
                pair(args.summary_ru, args.summary_en, '--summary', plancat.SUMMARY_MAX),
                pair(args.changed_ru, args.changed_en, '--changed', plancat.CHANGED_MAX),
                split(args.tags), split(args.langs), args.game, args.date, args.key, args.site, args.planner, args.root)
        elif args.cmd == 'remove':
            remove(args.uid, args.key, args.site, args.planner)
        elif args.cmd == 'list':
            show(args.site, args.planner)
        else:
            if verify(args.site, args.planner):
                return 1
    except Stop as e:
        print('Отказ: %s' % e)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
