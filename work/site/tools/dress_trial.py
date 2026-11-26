# -*- coding: utf-8 -*-
"""Give the trial hero an ordinary mid-campaign state through the program's own doors: tree points taken (log lines),
items worn (copy file + «Надеть»), earlier goals marked done (page marks).

    python -X utf8 dress_trial.py <port> <language code> <trial dir> [copy | dress | drop]

«copy» — only the last step: the new boots are copied again (the comparison lives 60 s); «dress» — everything but
that copy; «drop» — take the comparison off the page."""
import json
import sys
import time
import urllib.request
from pathlib import Path

port, lang, trial = sys.argv[1], sys.argv[2], Path(sys.argv[3])
mode = sys.argv[4] if len(sys.argv) > 4 else ''
only_copy = mode in ('copy', 'drop')
URL = 'http://127.0.0.1:%s' % port
log, clip = trial / 'game' / 'logs' / 'Client.txt', trial / 'clip' / 'now.txt'
items = json.loads((trial / 'items.json').read_text(encoding='utf-8'))      # prep_trial.py wrote them, in the client's language


def view():
    with urllib.request.urlopen('%s/api/view?lang=%s' % (URL, lang), timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def post(body):
    req = urllib.request.Request(URL + '/api/mark', data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8')).get('ok')
    except urllib.error.HTTPError as e:
        return 'HTTP %d' % e.code


def log_line(text, back=0.0):
    ts = time.time() - back
    stamp = time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(ts))
    with open(log, 'a', encoding='utf-8', newline='\n') as f:
        f.write('%s %d cff945b9 [INFO Client 4321] %s\n' % (stamp, int(ts * 1000) % 100000000, text))


def copy(text, tries=40):
    """Put an item text where the trial server reads «the clipboard»; wait until the page shows the comparison."""
    before = (view().get('copy') or {}).get('at')
    clip.write_text(text, encoding='utf-8')
    for _ in range(tries):
        time.sleep(0.25)
        cp = view().get('copy')
        if cp and cp.get('at') != before:
            return cp
    return None


def wear(key):
    cp = copy(items[key])
    if not cp:
        print('  %-10s copy not seen' % key)
        return
    rows = cp.get('rows') or []
    row = next((r for r in rows if r['row'] == cp.get('pick')), rows[0] if rows else None)
    ok = post({'wear': {'row': row['row']}}) if row else None
    print('  %-10s row %-14s verdict %-8s wear %s' % (key, row and row['row'], row and row.get('verdict'), ok))
    time.sleep(0.4)


if not only_copy:
    v = view()
    assert v['hero']['name'] in ('Проба', 'Trial'), 'not the trial hero'
    # 1. passive tree: take the free points in the plan's order
    t = v['tree']
    for k, node in enumerate(t['plan'][t['taken']:t['taken'] + t['free']]):
        log_line('Successfully allocated passive skill id: %s, name: %s' % (node['id'], node['name']), back=t['free'] - k)
    time.sleep(1.5)
    t = view()['tree']
    print('tree: taken %d of %d, free %d' % (t['taken'], t['total'], t['free']))
    # 2. worn items
    for key in ('wand', 'sceptre', 'ring', 'boots_worn'):
        wear(key)
    # 3. everything due on earlier steps: done
    for round_ in range(6):
        v = view()
        late = [g for g in v['overdue']]
        if not late:
            break
        for g in late:
            res = post({'goal': g['id'], 'status': 2})
            if round_:
                print('  still late: %s (auto %s) -> %s | closedBy %s expect %s' % (
                    g['id'], g.get('auto'), res, json.dumps(g.get('closedBy'), ensure_ascii=False),
                    json.dumps(g.get('expect'), ensure_ascii=False)))
        time.sleep(0.5)
    v = view()
    print('overdue left: %s' % [g['id'] for g in v['overdue']])
    print('missed left : %s' % [g['id'] for g in v['missed']])
    print('step goals  : %s' % [(g['id'], g.get('status'), g.get('urgency')) for g in v['step']['goals']])
    print('step bosses : %s' % [(g['id'], g.get('status'), g.get('urgency')) for g in v['step']['bosses']])
    print('worn slots  : %s' % [(s['id'], bool(s.get('worn'))) for s in v['slots']])
if mode == 'drop':
    print('drop: %s' % post({'wear': {'drop': True}}))
    sys.exit(0)
if mode == 'dress':
    sys.exit(0)
cp = copy(items['boots_new'])
print('copy: %s' % (cp and {k: cp[k] for k in cp if k in ('pick', 'verdict', 'until', 'name', 'up', 'down')}))
if cp:
    for r in cp.get('rows') or []:
        print('  row', {k: r[k] for k in r if k in ('row', 'verdict', 'up', 'down', 'same', 'keep', 'can')})
