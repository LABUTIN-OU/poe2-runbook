# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Библиотека планов: в программе их несколько — свои и присланные другими.

Каждый план — своя папка в plans/: оглавление plan.json и части, которые оно называет (маршрут, билд;
planfiles). Имя папки — id плана: по нему герой привязан к плану (runs/plans.json) и его открывает
редактор (/admin?plan=…). Название плана — название его билда; id после создания плана не меняется.

Оглавление сверх прежнего (route, build, groups) держит:
  uid       — постоянная метка плана: с ней план уходит в файл и по ней узнаётся, когда приходит снова;
  received  — план прислан: {file — имя файла, at — когда добавлен}. Присланный сам не правится: правка
              ложится в копию, а он остаётся, каким его прислали, — поверх потом ляжет новая версия от автора;
  from      — копия: {uid, title} плана, с которого её сделали.

Файл плана для обмена — один JSON: {"format": FORMAT, "version": 1, "uid", "title", "groups",
"route": текст файла маршрута, "build": текст файла билда}. Тексты идут как есть: у принятого плана файлы
такие же, как у автора, и правки со страницы ложатся в них так же, как у него.
"""
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

import buildplan
import planfiles
from i18n import tr

FORMAT = 'poe2-runbook-plan'
MANIFEST = 'plan.json'
ROUTE, BUILD = 'route.json', 'build.json'      # части плана, который программа пишет сама (копия, присланный)
# Шаблон кампании идёт с программой (knowledge/campaign.json, как справочник игры: одна версия на версию игры): маршрут
# только из того, что задаёт игра, — основа плана, созданного не с чужого плана. Его группы целей — как у первого плана.
TEMPLATE = 'campaign.json'
TEMPLATE_GROUPS = ['Навыки', 'Уровень', 'Восхождение', 'Награды', 'Задания', 'Механики', 'Тайники', 'Лагеря', 'Ресурсы', 'Прочее']
RE_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
MAX_TEXT = 2 * 1024 * 1024                     # часть плана в файле для обмена — не больше

# Русские буквы латиницей: из названия «Ведьма на хаосе» выходит id «vedma-na-khaose».
_LAT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't',
                 'u', 'f', 'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya']))


def slug(title):
    """id плана из его названия: латиница, цифры и дефисы («HC SSF · DoV» -> «hc-ssf-dov»)."""
    s = ''.join(_LAT.get(c, c) for c in str(title or '').lower())
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:48].strip('-')
    return s or 'plan'


def free_id(root, base):
    """Свободное имя папки плана: base, base-2, base-3…"""
    root, base = Path(root), slug(base)
    pid, n = base, 1
    while (root / pid).exists():
        n += 1
        pid = '%s-%d' % (base, n)
    return pid


def new_uid():
    return secrets.token_hex(6)


def stamp_text(now=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))


def manifest_path(root, pid):
    """Оглавление плана pid или None, если такого id быть не может (имя папки — только RE_ID)."""
    if not isinstance(pid, str) or not RE_ID.fullmatch(pid):
        return None
    return Path(root) / pid / MANIFEST


def scan(root):
    """Планы библиотеки: [{id, path — оглавление, manifest}] по id. Папка без оглавления плана — не план."""
    out = []
    try:
        names = sorted(p.name for p in Path(root).iterdir() if p.is_dir())
    except OSError:
        return out
    for name in names:
        path = manifest_path(root, name)
        if path is None:
            continue
        try:
            raw = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if planfiles.is_manifest(raw):
            out.append({'id': name, 'path': path, 'manifest': raw})
    return out


def project_plans(project):
    """Настоящие планы проекта — для проверок, что программа читает и пишет их файлы знак в знак: [(оглавление, {часть:
    файл})] всех планов библиотеки (plans/<id>/) и прежнего единственного плана (plan.json в корне), если он ещё есть.
    План без маршрута или билда не входит."""
    project = Path(project)
    paths = [rec['path'] for rec in scan(project / 'plans')]
    if (project / MANIFEST).is_file():
        paths.append(project / MANIFEST)
    out = []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding='utf-8-sig'))
            parts = planfiles.part_paths(path, raw) if planfiles.is_manifest(raw) else {}
        except (OSError, ValueError):
            continue
        if set(parts) == {'route', 'build'} and all(p.is_file() for p in parts.values()):
            out.append((path, parts))
    return out

def stamp(root):
    """Отметка библиотеки: папки планов и время их оглавлений и частей. Изменилась — список планов
    собирается заново (план добавлен, удалён, переименован)."""
    out = []
    for rec in scan(root):
        try:
            parts = planfiles.part_paths(rec['path'], rec['manifest'])
        except ValueError:
            parts = {}
        times = []
        for path in [rec['path']] + [parts[k] for k in sorted(parts)]:
            try:
                times.append(path.stat().st_mtime)
            except OSError:
                times.append(None)
        out.append((rec['id'], tuple(times)))
    return tuple(out)


def summary(rec):
    """Что о плане видно в списке: {id, title, cls — класс героя билда (имя из данных игры), uid,
    received, from}. Название — из билда; нет его — id."""
    m = rec['manifest']
    title, cls = '', None
    try:
        build = planfiles.read_parts(rec['path'], m).get('build') or {}
        title = build.get('title') if isinstance(build.get('title'), str) else ''
        hero = build.get('hero') if isinstance(build.get('hero'), dict) else {}
        cls = hero.get('class') if isinstance(hero.get('class'), str) else None
    except ValueError:
        pass
    out = {'id': rec['id'], 'title': title.strip() or rec['id'], 'cls': cls,
           'uid': m.get('uid') if isinstance(m.get('uid'), str) else None}
    if isinstance(m.get('received'), dict):
        out['received'] = {k: m['received'][k] for k in ('file', 'at') if isinstance(m['received'].get(k), str)}
    if isinstance(m.get('from'), dict):
        out['from'] = {k: m['from'][k] for k in ('uid', 'title', 'take', 'template') if isinstance(m['from'].get(k), str)}
    return out


def write_manifest(path, manifest):
    """Оглавление плана — по ключу на строку, как его пишут руками."""
    order = ['version', 'uid', 'route', 'build', 'groups', 'received', 'from']
    keys = [k for k in order if k in manifest] + [k for k in manifest if k not in order]
    body = ',\n'.join('  %s: %s' % (json.dumps(k, ensure_ascii=False), json.dumps(manifest[k], ensure_ascii=False))
                      for k in keys)
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(('{\n%s\n}\n' % body).encode('utf-8'))
    os.replace(tmp, path)


def _parts_text(path, manifest):
    """Тексты частей плана как они лежат на диске: (маршрут, билд). Нет части — ValueError."""
    paths = planfiles.part_paths(path, manifest)
    if set(paths) != {'route', 'build'}:
        raise ValueError(tr('у плана нет маршрута или билда'))
    return buildplan.read_text(paths['route'])[0], buildplan.read_text(paths['build'])[0]


def _make(root, pid, route_text, build_text, manifest):
    """Новая папка плана: части и оглавление. Не вышло — папки нет."""
    folder = Path(root) / pid
    folder.mkdir(parents=True)
    try:
        for name, text in ((ROUTE, route_text), (BUILD, build_text)):
            (folder / name).write_bytes(text.encode('utf-8'))
        write_manifest(folder / MANIFEST, dict({'version': 2, 'uid': manifest.get('uid') or new_uid(),
                                                'route': ROUTE, 'build': BUILD}, **manifest))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return pid


def copy(root, src, title=None):
    """Копия плана src под названием title (нет — «<название> · копия»): новая папка, новая метка,
    from — с какого плана. Копия присланного — уже своя. Возвращает id копии."""
    path = manifest_path(root, src)
    if path is None or not path.is_file():
        raise ValueError(tr('плана «%s» нет') % src)
    rec = next((r for r in scan(root) if r['id'] == src), None)
    if rec is None:
        raise ValueError(tr('план «%s» не читается') % src)
    info = summary(rec)
    route_text, build_text = _parts_text(path, rec['manifest'])
    name = str((title or '').strip() or tr('%s · копия') % info['title'])[:120]
    build_text = buildplan.render_sections(build_text, {'title': name})
    m = rec['manifest']
    keep = {k: m[k] for k in ('groups',) if isinstance(m.get(k), list)}
    return _make(root, free_id(root, name), route_text, build_text,
                 dict(keep, uid=new_uid(), **{'from': {'uid': info['uid'] or '', 'title': info['title'], 'take': 'all'}}))


def empty_build(title, route_id):
    """Текст пустого билда нового плана: название и маршрут, без героя, слотов, этапов и целей. Разделы на своих местах
    и в том виде, в каком их пишет сама страница (пустые слоты и этапы — в одну строку, цели — открытым списком):
    запись раздела, в котором ничего не изменилось, оставляет файл знак в знак."""
    dump = lambda x: json.dumps(x, ensure_ascii=False)     # noqa: E731
    return ('{\n  "version": 2,\n  "title": %s,\n  "routeId": %s,\n  "hero": {},\n'
            '  "slots": [],\n  "stages": [],\n  "goals": [\n  ]\n}\n') % (dump(title), dump(route_id))


def route_only(text):
    """Маршрут плана для нового плана с пустым билдом: то, что в маршруте ссылается на цели билда (у цели шага —
    «даёт цель билда», grantedBy), уходит. Остальное — знак в знак."""
    data = json.loads(text)
    goals = data.get('goals') or []
    clean = [{k: v for k, v in g.items() if k != 'grantedBy'} if isinstance(g, dict) else g for g in goals]
    return text if clean == goals else buildplan.splice_goals(text, clean)


def create(root, title, route_text, build_text, groups=None, origin=None):
    """Новый свой план: папка по названию, части — эти тексты, оглавление с новой меткой; origin — на основе чего
    (from). Возвращает id."""
    manifest = {'uid': new_uid()}
    if groups:
        manifest['groups'] = list(groups)
    if origin:
        manifest['from'] = origin
    return _make(root, free_id(root, title), route_text, build_text, manifest)


def bundle(root, pid):
    """Файл плана pid для обмена (словарь FORMAT)."""
    path = manifest_path(root, pid)
    rec = next((r for r in scan(root) if r['id'] == pid), None)
    if path is None or rec is None:
        raise ValueError(tr('плана «%s» нет') % pid)
    route_text, build_text = _parts_text(path, rec['manifest'])
    info = summary(rec)
    m = rec['manifest']
    return {'format': FORMAT, 'version': 1, 'uid': info['uid'] or '', 'title': info['title'],
            'groups': m.get('groups') if isinstance(m.get('groups'), list) else [],
            'route': route_text, 'build': build_text}


def parse_bundle(data):
    """Проверяет присланный файл плана: (текст маршрута, текст билда, сведения {uid, title, groups}).
    Не файл плана или в нём что-то не так — ValueError со словами для игрока."""
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValueError(tr('это не файл плана'))
    if not isinstance(data.get('version'), int) or data['version'] > 1:
        raise ValueError(tr('файл плана новее программы: обновите программу'))
    texts = {}
    for part, word in (('route', tr('маршрут')), ('build', tr('билд'))):
        text = data.get(part)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError(tr('в файле плана нет части «%s»') % word)
        try:
            obj = json.loads(text)
        except ValueError as e:
            raise ValueError(tr('часть «%s» файла плана не читается: %s') % (word, e))
        if not isinstance(obj, dict):
            raise ValueError(tr('часть «%s» файла плана записана не так') % word)
        texts[part] = text
    uid = data.get('uid') if isinstance(data.get('uid'), str) and re.fullmatch(r'[0-9a-z]{1,40}', data['uid']) else ''
    title = data.get('title') if isinstance(data.get('title'), str) else ''
    groups = [g for g in data.get('groups') or [] if isinstance(g, str)][:40] if isinstance(data.get('groups'), list) else []
    return texts['route'], texts['build'], {'uid': uid, 'title': title.strip()[:120], 'groups': groups}


def _file_name(name):
    name = str(name or '').replace('\\', '/').rsplit('/', 1)[-1]
    return re.sub(r'[\x00-\x1f]', '', name)[:120]


def add(root, data, file_name='', now=None, uid=None):
    """Присланный план — в библиотеку: новая папка с пометкой received. uid — своя метка вместо метки
    файла (план добавляют отдельно от того, что у игрока уже есть). Возвращает id."""
    route_text, build_text, meta = parse_bundle(data)
    own = json.loads(build_text).get('title')
    title = meta['title'] or (own if isinstance(own, str) else '')
    manifest = {'uid': uid or meta['uid'] or new_uid(), 'received': {'file': _file_name(file_name), 'at': stamp_text(now)}}
    if meta['groups']:
        manifest['groups'] = meta['groups']
    return _make(root, free_id(root, title or 'plan'), route_text, build_text, manifest)


def same(root, data):
    """План библиотеки с той же меткой, что у присланного файла: {id, title, received} или None."""
    try:
        uid = parse_bundle(data)[2]['uid']
    except ValueError:
        return None
    if not uid:
        return None
    for rec in scan(root):
        if rec['manifest'].get('uid') == uid:
            return summary(rec)
    return None


def replace(root, pid, data, file_name='', now=None, backup_dir=None):
    """Новая версия присланного плана pid из файла: части переписываются (прежние — в backup_dir),
    папка, id и метка остаются — герои, которые по нему идут, идут дальше по новой версии."""
    route_text, build_text, meta = parse_bundle(data)
    path = manifest_path(root, pid)
    rec = next((r for r in scan(root) if r['id'] == pid), None)
    if path is None or rec is None:
        raise ValueError(tr('плана «%s» нет') % pid)
    m = dict(rec['manifest'])
    if not isinstance(m.get('received'), dict):
        raise ValueError(tr('план «%s» — ваш: присланный файл его не заменяет') % summary(rec)['title'])
    paths = planfiles.part_paths(path, m)
    for part, text in (('route', route_text), ('build', build_text)):
        buildplan.write_text(paths[part], text, False, backup_dir, part, now)
    m['received'] = {'file': _file_name(file_name), 'at': stamp_text(now)}
    if meta['groups']:
        m['groups'] = meta['groups']
    write_manifest(path, m)
    return pid


def remove(root, pid, trash, now=None):
    """Убирает план из библиотеки: папка уходит в trash (<id>-<время>), назад её можно вернуть руками."""
    path = manifest_path(root, pid)
    if path is None or not path.is_file():
        raise ValueError(tr('плана «%s» нет') % pid)
    trash = Path(trash)
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / ('%s-%s' % (pid, time.strftime('%Y%m%d-%H%M%S', time.localtime(now))))
    shutil.move(str(path.parent), str(dest))
    return dest


def adopt(plan_path, root):
    """Прежний единственный план (оглавление вне библиотеки, например plan.json в корне проекта) переезжает
    в библиотеку: папка по его названию, части — route.json и build.json (файлы переносятся, не копируются),
    оглавление получает метку; прежнее оглавление и опустевшие папки частей уходят. Возвращает id."""
    plan_path = Path(plan_path)
    raw = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    if not planfiles.is_manifest(raw):
        raise ValueError(tr('%s — не оглавление плана') % plan_path.name)
    paths = planfiles.part_paths(plan_path, raw)
    if set(paths) != {'route', 'build'}:
        raise ValueError(tr('у плана нет маршрута или билда'))
    build = json.loads(paths['build'].read_text(encoding='utf-8-sig'))
    pid = free_id(root, build.get('title') if isinstance(build.get('title'), str) else 'plan')
    folder = Path(root) / pid
    folder.mkdir(parents=True)
    os.replace(paths['route'], folder / ROUTE)
    os.replace(paths['build'], folder / BUILD)
    manifest = {k: v for k, v in raw.items() if k not in ('route', 'build', 'profile')}
    manifest.update({'version': raw.get('version', 2), 'uid': raw.get('uid') or new_uid(), 'route': ROUTE, 'build': BUILD})
    write_manifest(folder / MANIFEST, manifest)
    plan_path.unlink()
    for part in paths.values():
        try:
            part.parent.rmdir()          # только пустая
        except OSError:
            pass
    return pid
