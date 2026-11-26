# -*- coding: utf-8 -*-
"""Raw pictures of the program for its site — from a trial copy with a fictional hero, never from the player's own data.

    python -X utf8 make_shots.py <program folder with planner/> <project> <work dir> <out dir> <language code> [port]

One run for one language (any language of the program): fresh trial data in that language of the game client
(prep_trial.py) -> the program's server on a free port (every data path inside the work dir; --offline: no request
leaves the computer) -> an ordinary state of the hero (dress_trial.py) -> pictures in a hidden Chrome. The program
shows its pages in the client's language by itself. Each picture is taken twice as dense as it is shown at its largest
on the site, so nothing is resampled afterwards (pack_shots.py only places two of them on a canvas). The server is
this script's own child and is stopped at the end.

What is taken (names get the language at the end; «shown» is the largest width on the page, set by the sample):
  window  the «Игра» page in the program's window, down to the step card      shown 1040 -> 2080 px   «Вы просто играете»
  tiles   the three time tiles of that page: stage, act, current zone         shown 1040 -> 2080 px   «В темпе автора»
  time    «Разбор»: steps, time bars with the target mark, time in the zone   shown  876 -> 1752 px   «Каждая минута на счету»
  plan    «Редактор», the route tab: steps and their target time              shown  511 -> 1040 px   «Знаете, как лучше?»
  answer  the answer to a copied item                                         shown  560 -> 1120 px   «Надеть или выбросить»
  list    the step list that stands over the game, opened                     shown  832 -> 1664 px   the first screen
  late    the same list with one goal late, its first rows close up           shown  992 -> 1984 px   «Красная строка не уйдёт»
The list is taken at the moment the step's time reads LIST_TIME: the page's description of that picture names it.
Beside every picture <name>-<code>.txt holds all the text inside its frame — words_check.py reads it."""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdp import Chrome  # noqa: E402

program, project, work, out = (Path(a).resolve() for a in sys.argv[1:5])
lang = sys.argv[5]
port = int(sys.argv[6]) if len(sys.argv) > 6 else 4751
HERO = 'Проба' if lang == 'ru' else 'Trial'
# the editor's tab with the route, by the program's own name for it in this language
TAB = 'Маршрут' if lang == 'ru' else json.loads((program / 'planner' / 'lang' / ('%s.json' % lang)).read_text(encoding='utf-8'))['texts']['Маршрут']
WINDOW, WINDOW_RATIO = 2080, 1400 / 1850                 # the program's window: pixels wide; height to width, as in the sample page
TILES, TILES_RATIO = 2080, 212 / 1772                    # the strip of time tiles: pixels wide; height to width, as in the sample
REVIEW, REVIEW_SCALE = (1752, 984), 1.71 * 1752 / 1000   # the «Разбор» picture's canvas and the density its piece is taken at
PLAN = (1040, 584)                                       # the editor picture, pixels
LIST, CLOSE, ANSWER = 1664, 1984, 1120                   # pixels wide; the windows themselves are 540 and 480 points
CLOSE_RATIO = 138 / 810                                  # the close-up: this much of the list's height to its width, as in the sample
LATE = 'skill-essence-drain'                             # the goal left undone: its row is red in the list
LIST_TIME = '1:26'                                       # the step's time on the list picture
trial = work / 'trial' / lang
URL = 'http://127.0.0.1:%d' % port


def free(p):
    s = socket.socket()
    try:
        s.bind(('127.0.0.1', p))
        return True
    except OSError:
        return False
    finally:
        s.close()


def run(script, *args):
    subprocess.run([sys.executable, '-X', 'utf8', str(HERE / script)] + [str(a) for a in args], check=True)


def view():
    with urllib.request.urlopen('%s/api/view?lang=%s' % (URL, lang), timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def mark(goal, status):
    req = urllib.request.Request(URL + '/api/mark', data=json.dumps({'goal': goal, 'status': status}).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8')).get('ok')


def trial_hero():
    """The page is the trial one: the hero on it is the fictional hero and nobody else."""
    v = view()
    names = {r.get('name') for r in v.get('runs') or []} | {v['hero'].get('name')}
    if names != {HERO}:
        raise SystemExit('NOT the trial hero on port %d — no picture taken' % port)


if not free(port) or not free(port + 7):
    raise SystemExit('port %d or %d is busy' % (port, port + 7))
out.mkdir(parents=True, exist_ok=True)
run('prep_trial.py', project, trial, lang, 'hunting')
server = subprocess.Popen(
    [sys.executable, '-X', 'utf8', '-u', str(program / 'planner' / 'server.py'), '--port', str(port),
     '--log', str(trial / 'game' / 'logs' / 'Client.txt'), '--runs', str(trial / 'runs'),
     '--archive', str(trial / 'archive'), '--config', str(trial / 'config.ini'),
     '--filters', str(trial / 'OnlineFilters'), '--plans', str(trial / 'plans'),
     '--settings', str(trial / 'settings.json'), '--clip-file', str(trial / 'clip' / 'now.txt'),
     '--hotkey-file', str(trial / 'clip' / 'key.txt'), '--catalog', str(project / 'catalog' / 'data'),
     '--knowledge', str(project / 'knowledge'), '--lang', 'en', '--offline'],
    cwd=str(program), stdout=open(trial / 'server.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
chrome = None
try:
    for _ in range(160):
        try:
            view()
            break
        except OSError:
            time.sleep(0.25)
    trial_hero()
    log = (trial / 'server.log').read_text(encoding='utf-8', errors='replace')
    if 'catalogue: version' not in log:
        raise SystemExit('the trial server runs without the game-data catalogue — see %s' % (trial / 'server.log'))
    run('dress_trial.py', port, lang, trial, 'dress')
    chrome = Chrome(str(work / 'chrome-profile'), port + 7)
    tab = chrome.tab()

    def page(path, width, height, scale, ready):
        tab.size(width, height, scale=scale, dark=True)
        tab.go(URL + path)
        tab.wait("document.readyState === 'complete' && (%s)" % ready, 40)
        time.sleep(2.0)
        shown = tab.js('document.documentElement.lang')
        if shown != lang:
            raise SystemExit('the page %s is shown in %r, %r wanted' % (path, shown, lang))

    def calm():
        """The «Взято» check of the tree points and other pop-ups leave by themselves in a few seconds."""
        for _ in range(40):
            if not tab.js("[...document.querySelectorAll('#cmp,#way,#pts')].some(e => e.getBoundingClientRect().height > 0)"):
                return
            time.sleep(0.5)

    # every piece of text a picture shows: text nodes and field values whose box lies inside the picture's frame
    SEEN = ("(function(c){var out=[], w=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n, r=document.createRange();"
            "var inside=function(b){var x=b.left+scrollX, y=b.top+scrollY; return b.width>0 && b.height>0 && x<c.x+c.width && x+b.width>c.x && y<c.y+c.height && y+b.height>c.y};"
            "var shown=function(e){for(;e;e=e.parentElement){var s=getComputedStyle(e); if(s.display==='none'||s.visibility==='hidden'||+s.opacity===0) return false;} return true};"
            "while((n=w.nextNode())){var t=n.nodeValue.trim(); if(!t||!shown(n.parentElement)) continue; r.selectNodeContents(n); if(inside(r.getBoundingClientRect())) out.push(t);}"
            "document.querySelectorAll('input,textarea,select').forEach(function(e){var t=(e.tagName==='SELECT'?(e.selectedOptions[0]||{}).text:e.value)||'';"
            "if(t.trim()&&shown(e)&&inside(e.getBoundingClientRect())) out.push(t.trim());});"
            "return out})(%s)")

    def take(name, clip, say=None, checked=False):
        if not checked:
            trial_hero()
        n = tab.shot(out / ('%s-%s.png' % (name, lang)), clip=clip)
        print('%-8s %7d bytes  %s x %s' % (name, n, round(clip['width'], 1), round(clip['height'], 1)))
        # what the picture says, for the check of words that are not in the page's language (words_check.py)
        (out / ('%s-%s.txt' % (name, lang))).write_text('\n'.join(tab.js(SEEN % json.dumps(clip))), encoding='utf-8')
        if say:
            print('   ', repr(tab.js(say)))

    def fit(path, width, pixels, ready):
        """A page in a window of the given width, at the density that makes its own width (without the gutter it
        keeps for the scrollbar) exactly the wanted number of pixels."""
        page(path, width, 900, pixels / (width - 15), ready)
        wide = round(tab.js('document.body.getBoundingClientRect().width'))     # the gutter is kept even with no scrollbar drawn
        if wide != width - 15:
            tab.size(width, 900, scale=pixels / wide, dark=True)
            time.sleep(1.0)
        return wide

    # --- the «Игра» page in the program's window ---------------------------------------------------------------------
    wide = fit('/', 940, WINDOW, "document.querySelector('.status') && document.querySelector('.zname') && document.querySelector('#s-route')")
    calm()
    take('window', {'x': 0, 'y': 0, 'width': wide, 'height': round(wide * WINDOW_RATIO)},
         "document.querySelector('.top').innerText.replace(/\\s+/g,' ') + ' | ' + document.querySelector('.srow').innerText.replace(/\\s+/g,' ')")

    # --- its three time tiles: stage, act, the current zone ------------------------------------------------------------
    def tiles_box(pad=8):
        """The three tiles with a margin of the page around them: «pad» at the sides, above and below as much as
        gives the strip the sample's proportion."""
        box = tab.js("(function(){var t=[...document.querySelectorAll('.tt')].map(e => e.getBoundingClientRect()).filter(r => r.width > 0);"
                     "if(!t.length) return null;"
                     "var l=Math.min(...t.map(r => r.left)), r=Math.max(...t.map(r => r.right)), a=Math.min(...t.map(r => r.top)), b=Math.max(...t.map(r => r.bottom));"
                     "return {x:l-%d+scrollX, y:a+scrollY, width:r-l+%d, height:b-a, n:t.length}})()" % (pad, 2 * pad))
        if box:
            tall = box['width'] * TILES_RATIO
            if tall < box['height'] + 4:
                raise SystemExit('the time tiles are taller than the strip of the sample allows: %r' % box)
            box['y'] -= (tall - box['height']) / 2
            box['height'] = tall
        return box

    box = tiles_box()
    if not box or box.pop('n') != 3:
        raise SystemExit('the «Игра» page shows no three time tiles: %r' % box)
    tab.size(940, 900, scale=TILES / box['width'], dark=True)
    time.sleep(1.0)
    box = tiles_box()
    box.pop('n')
    take('tiles', box, "[...document.querySelectorAll('.tt')].map(e => e.innerText.replace(/\\s+/g,' ')).join(' | ')")

    # --- «Разбор»: the table's left part — steps, bars with the target mark, time in the zone ----------------------------
    page('/review', 940, 900, REVIEW_SCALE, "document.querySelector('#rv-tb tbody tr')")
    box = tab.js("(function(){var t=document.querySelector('#rv-tb').getBoundingClientRect(),"
                 "c=document.querySelectorAll('#rv-tb thead th'),r=document.querySelectorAll('#rv-tb tbody tr');"
                 "return {x:t.left+scrollX, y:document.querySelector('#rv-tb tbody').getBoundingClientRect().top+scrollY-32, right:c[2].getBoundingClientRect().right+scrollX,"
                 "bottom:r[Math.min(7, r.length-1)].getBoundingClientRect().bottom+scrollY,"
                 "heads:[...c].map(e => e.innerText.trim())}})()")
    print('    review columns:', box['heads'])
    take('time', {'x': box['x'] - 4, 'y': box['y'], 'width': box['right'] - box['x'] + 8, 'height': box['bottom'] - box['y']},
         "[...document.querySelectorAll('#rv-tb tbody tr')].slice(0, 8).map(r => r.innerText.replace(/\\s+/g,' ').trim()).join(' | ')")

    # --- «Редактор», the route tab ---------------------------------------------------------------------------------------
    wide = fit('/admin', 620, PLAN[0], "document.querySelector('nav.tabs button')")
    if not tab.js("(function(){var b=[...document.querySelectorAll('nav.tabs button')].find(e => e.textContent.trim() === %s);"
                  "if(b) b.click(); return !!b})()" % json.dumps(TAB)):
        raise SystemExit('the editor has no tab %r' % TAB)
    time.sleep(1.2)
    tabs = tab.js("document.querySelector('nav.tabs').getBoundingClientRect().top")
    take('plan', {'x': 0, 'y': tabs, 'width': wide, 'height': wide * PLAN[1] / PLAN[0]},
         "document.querySelector('nav.tabs').innerText.replace(/\\s+/g,' ') + ' | ' + "
         "document.querySelector('#app').innerText.replace(/\\s+/g,' ').slice(0, 160)")

    # --- the answer to a copied item, as its window over the game shows it -------------------------------------------------
    page('/?ov=answer&arm=0', 480, 700, ANSWER / 480, "document.querySelector('#cmp')")
    run('dress_trial.py', port, lang, trial, 'copy')
    tab.wait("document.querySelector('#cmp').getBoundingClientRect().height > 150", 20)
    time.sleep(1.0)
    take('answer', tab.rect('#cmp'), "document.querySelector('#cmp').innerText.replace(/\\s+/g,' ')")
    run('dress_trial.py', port, lang, trial, 'drop')
    time.sleep(0.6)

    # --- the step list that stands over the game: opened, as with Alt held ------------------------------------------------
    def step_list(name, pixels):
        page('/?ov=list&arm=0', 540, 600, pixels / 540, "document.querySelector('#app') && document.querySelector('#app').getBoundingClientRect().height > 30")
        tab.js('window.ovArm && ovArm(2)')
        time.sleep(1.0)
        box = tab.rect('#app')
        if name == 'late':                          # the close-up: the late goal and the two due ones
            box['height'] = box['width'] * CLOSE_RATIO
            return take(name, box, "document.querySelector('#app').innerText.replace(/\\s+/g,' ')")
        # the list is taken in the very second the step's time reads LIST_TIME: wait for the second before it, then for it
        trial_hero()
        reads = "new RegExp('(^|[^0-9:])%s([^0-9]|$)').test(document.querySelector('#app').innerText)"
        m, s = (int(x) for x in LIST_TIME.split(':'))
        before = '%d:%02d' % divmod(m * 60 + s - 1, 60)
        try:
            tab.wait(reads % before, 90, every=0.1)
            tab.wait(reads % LIST_TIME, 5, every=0.03)
        except TimeoutError:
            raise SystemExit('the list never read %s — it reads: %r' % (LIST_TIME, tab.js("document.querySelector('#app').innerText.replace(/\\s+/g,' ')")))
        take(name, box, "document.querySelector('#app').innerText.replace(/\\s+/g,' ')", checked=True)

    step_list('list', LIST)
    # one goal is left undone: its row is red and stays in the list
    print('    leave undone:', LATE, mark(LATE, 0))
    time.sleep(1.0)
    step_list('late', CLOSE)
    print('    mark back   :', mark(LATE, 2))
finally:
    if chrome is not None:
        chrome.stop()
    server.terminate()
    try:
        server.wait(10)
    except subprocess.TimeoutExpired:
        server.kill()
