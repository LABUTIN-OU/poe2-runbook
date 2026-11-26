# -*- coding: utf-8 -*-
"""Trial data for site screenshots: a fictional hero, a copy of the bundled plan with neutral filter names, a generated
game log and item texts — in any language of the game client the program knows. Nothing of the real run, log, config
or filter names is read or copied.

    python -X utf8 prep_trial.py <project> <trial dir> <language code> <step id to stand on>

The game's own words (zone names, the hero's class, the level-up line of the log, item texts) come from the catalogue
of game data in that language. The plan is the bundled one as it is: its own words (step names, stage titles) the
program translates itself (since 0.5.5.23 — the «plan» layer of planner/lang/<code>.json), so the pictures show what
a player of that language sees.
"""
import gzip
import json
import random
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import items  # noqa: E402

project, trial, lang, upto = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
cat = project / 'catalog' / 'data' / (project / 'catalog' / 'data' / 'current.txt').read_text(encoding='utf-8').strip()
pack = json.loads((cat / ('lang-%s.json' % lang)).read_text(encoding='utf-8'))
with gzip.open(cat / ('log-%s.json.gz' % lang), 'rt', encoding='utf-8') as f:
    LEVEL = json.load(f)['msg']['LevelUp']                    # «{0} ({1}) достигает {2} уровня»
HERO = ('Проба' if lang == 'ru' else 'Trial', pack['heroClasses']['Sorceress'])
FILTER_NAMES = {'ru': 'Фильтр кампании %d', 'en': 'Campaign filter %d', 'de': 'Kampagnenfilter %d', 'es': 'Filtro de campaña %d',
                'fr': 'Filtre de campagne %d', 'ja': 'キャンペーンフィルター %d', 'ko': '캠페인 필터 %d', 'pt': 'Filtro da campanha %d',
                'th': 'ฟิลเตอร์แคมเปญ %d'}[lang]
STAND = 40                       # the hero entered the last zone this many seconds ago

if trial.exists():
    shutil.rmtree(trial)
for sub in ('plans', 'OnlineFilters', 'runs', 'archive', 'clip', 'game/logs'):
    (trial / sub).mkdir(parents=True)

# --- plan copy: filter codes and names replaced ---------------------------------------------------------------
src = project / 'plans' / 'hc-ssf-dov'
dst = trial / 'plans' / 'hc-ssf-dov'
dst.mkdir()
for name in ('plan.json', 'build.json'):
    shutil.copyfile(src / name, dst / name)
route = json.loads((src / 'route.json').read_text(encoding='utf-8-sig'))
codes = {}
for s in route['steps']:
    fid = s.get('filter')
    if isinstance(fid, str) and len(fid) == 8:
        codes.setdefault(fid, 'TrialAa%d' % (len(codes) + 1))
        s['filter'] = codes[fid]
        s['filterName'] = FILTER_NAMES % int(codes[fid][-1])
    elif 'filterName' in s:
        del s['filterName']
areas = json.loads((cat / 'areas.json').read_text(encoding='utf-8'))
(dst / 'route.json').write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding='utf-8')
for n, code in enumerate(sorted(codes.values()), 1):
    head = ['#Online Item Filter', '#name:' + FILTER_NAMES % n, '#version:0.5.5', '#realm:poe2', '#errors:',
            '#hash:%032x' % (0x5eed0000 + n), '#filterVersion:1', '#filterType:Normal',
            '#lastUpdate:2026-11-20T10:00:00Z', '#monthTimeStamp:2026-11', '', 'Show', '']
    (trial / 'OnlineFilters' / code).write_text('\n'.join(head), encoding='utf-8')

# --- log ---------------------------------------------------------------------------------------------------------
local = pack.get('areas') or {}


def zone_name(code):
    return local.get(code) or areas[code]['name']


def secs(target):
    m, s = target.split(':')
    return int(m) * 60 + int(s)


steps = route['steps']
ids = [s['id'] for s in steps]
if upto not in ids:
    sys.exit('no step %s' % upto)
walk = steps[:ids.index(upto) + 1]
rnd = random.Random(7)
spans = [int(secs(s.get('target') or '2:00') * rnd.choice((0.86, 0.9, 0.93, 0.97, 1.02, 1.05))) for s in walk]
start = time.time() - STAND - sum(spans[:-1])
lines = []


def put(ts, kind, text):
    stamp = time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(ts))
    lines.append('%s %d cff945b9 [%s Client 4321] %s' % (stamp, int(ts * 1000) % 100000000, kind, text))


put(start - 50, 'INFO', '***** LOG FILE OPENING *****')
put(start - 48, 'INFO', '[HTTP2] User agent: PoE poe2_production/tags/0.5.5h Windows x64')
put(start - 30, 'INFO', '[SCENE] Set Source [(unknown)]')
t, level, current_filter = start, 1, None
for n, (s, span) in enumerate(zip(walk, spans)):
    last = n == len(walk) - 1
    fid = s.get('filter')
    if isinstance(fid, str) and len(fid) == 8:
        current_filter = fid
        put(t + 2, 'INFO', '[Item Filter] Finished reloading online filter %s. Result: true. Hash: %032x Type: Normal. Message: '
            % (fid, 0x5eed0000 + int(fid[-1])))
    code = s.get('zone')
    if code:
        area = areas[code]
        put(t, 'DEBUG', 'Generating level %d area "%s" with seed %d' % (area['level'], code, rnd.randrange(10 ** 9)))
        put(t + 1, 'INFO', '[SCENE] Set Source [%s]' % zone_name(code))
        want = level if area.get('town') else max(level, area['level'] + (0 if last else 1))
        room = (STAND - 20) if last else span
        gain = list(range(level + 1, want + 1))
        if last:
            gain = gain[:1] if gain and level < area['level'] else []
        for k, lv in enumerate(gain, 1):
            put(t + room * k / (len(gain) + 1), 'INFO', ': ' + LEVEL.format(HERO[0], HERO[1], lv))
            level = lv
    t += span
lines.sort(key=lambda x: x[:19])
(trial / 'game' / 'logs' / 'Client.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
(trial / 'config.ini').write_text('[LANGUAGE]\nlanguage=%s\n[GENERAL]\nitem_filter=%s\n' % (lang, current_filter or 'None'),
                                  encoding='utf-8')
(trial / 'clip' / 'now.txt').write_text('', encoding='utf-8')
(trial / 'items.json').write_text(json.dumps(items.texts(project, lang), ensure_ascii=False, indent=1), encoding='utf-8')
print('trial %s: hero %s (%s), steps %d, stands on %s, level %d, filter %s, log lines %d'
      % (lang, HERO[0], HERO[1], len(walk), upto, level, current_filter, len(lines)))
