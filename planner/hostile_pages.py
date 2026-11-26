# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка страниц враждебными планами — одной командой, на пробной странице:

    python -X utf8 planner/hostile_pages.py [--port 4771] [--no-csp] [--planner <папка>] [--families img,dquote]

Что делает. Пробная папка (временная): библиотека с одним своим планом героя «Проба» (план проекта с вымышленными
кодами и названиями фильтров, к нему hostile.enrich дописывает записи, в которых заполнено каждое поле схемы), лог,
фильтры, настройки игры, «буфер обмена» — файл. Сервер программы (server.py этой папки или --planner) на свободном
порту 4771–4779; Chrome без окна (DevTools по своему порту, свой временный профиль). Каждый враждебный план
(hostile.text_plans: в каждом текстовом поле — разметка с обработчиком, закрытие атрибута и тега, ссылки javascript:
и data:, кавычки… со своим номером) идёт настоящим путём: файл плана → POST /api/plans {import} (библиотека) →
{use} (план выбран героем). Потом каждый вид: «Игра» (список героев и планов, «Новый план», «Настройки», раскрытые
цели, шаги, карты дерева и атласа, окна при наведении, окно сравнения скопированного предмета), «Разбор»,
«Редактор» — все вкладки (карточки, версии дерева), окна поверх игры: список шага (/?ov=list, раскрытый Alt),
ответ на копию (/?ov=answer), окно дерева (/?ov=tree).

Что считается провалом:
  * отметка: window.__hit — код из плана выполнился;
  * разметка из плана легла разметкой (элемент с data-zz или тег x-zz появился в документе хоть на миг — следит
    MutationObserver с первого мгновения страницы) или ссылка javascript: / data: в href / src;
  * нарушение Content-Security-Policy (страница пыталась выполнить то, что политика запрещает) — с исправленными
    страницами их быть не должно; с --no-csp политика выключена (Page.setBypassCSP) — проверка одних esc;
  * ошибка JavaScript (исключение, необработанное обещание, console.error) или страница не нарисовалась.
Ошибки сети (картинка 404 у вымышленного рисунка цели) — не провал, считаются отдельно.

Ни одна кнопка, которая открывает браузер системы (/api/open) или выбирает папку игры (/api/game), не нажимается,
а сами эти адреса и всё, что не на 127.0.0.1, у страницы закрыты (Network.setBlockedURLs): наружу ничего не уходит.

Итог — строка «0 срабатываний из N» (N — вставок, которые побывали на страницах: поля × виды) и подробности в JSON;
код выхода 0 — чисто, 1 — есть провалы.
"""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hostile  # noqa: E402
import planlib  # noqa: E402

PORTS = range(4771, 4780)
CHROMES = [r'C:\Program Files\Google\Chrome\Application\chrome.exe',
           r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
           r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
           r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe']

ITEM = '''Класс предмета: Нательные доспехи
Редкость: Редкий
Колючий спаситель
Полные латы
--------
Броня: 358 (augmented)
--------
Требуется: Уровень 36, 54 Сила
--------
Уровень предмета: {n}
--------
+95(85-99) к максимуму здоровья
+36(28-56) к броне
'''

# Сторож страницы — ставится до её собственных скриптов (Page.addScriptToEvaluateOnNewDocument): нарушения политики,
# ошибки, вставленная разметка и опасные ссылки — всё, что появилось хоть на миг.
PROBE = r'''
(() => {
  const S = window.__probe = {csp: [], err: [], zz: [], links: [], inline: [], seen: new Set()};
  // какие поля плана побывали на странице текстом (номер поля стоит в каждой вставке): счёт покрытия
  const TAG = /(?:__hit=|x-zz&gt;|x-zz>|Ш)(\d+)/g;
  const tags = s => { if (s) for (const m of String(s).matchAll(TAG)) S.seen.add(+m[1]); };
  addEventListener('securitypolicyviolation', e => S.csp.push([e.violatedDirective, String(e.blockedURI || ''),
    String(e.sample || '').slice(0, 80), e.lineNumber || 0]));
  addEventListener('error', e => { if (e instanceof ErrorEvent) S.err.push(String(e.message) + ' @' + e.lineno + ':' + e.colno); }, true);
  addEventListener('unhandledrejection', e => S.err.push('rejection: ' + String(e.reason && (e.reason.stack || e.reason)).slice(0, 300)));
  const ce = console.error.bind(console);
  console.error = (...a) => { S.err.push('console.error: ' + a.map(String).join(' ').slice(0, 300)); ce(...a); };
  const bad = v => /^\s*(javascript|data|vbscript):/i.test(v || '');
  const look = n => {
    if (!n || n.nodeType !== 1) return;
    tags(n.textContent);
    for (const el of [n, ...n.querySelectorAll('*')]) {
      for (const a of ['title', 'aria-label', 'value', 'placeholder', 'alt']) if (el.hasAttribute(a)) tags(el.getAttribute(a));
      if (el.hasAttribute('data-zz') || el.localName === 'x-zz') S.zz.push(el.outerHTML.slice(0, 160));
      for (const a of ['href', 'src', 'action', 'formaction', 'xlink:href', 'srcdoc'])
        if (el.hasAttribute(a) && (a === 'srcdoc' || bad(el.getAttribute(a)))) S.links.push(el.localName + ' ' + a + '=' + el.getAttribute(a).slice(0, 80));
      for (const at of el.attributes) if (/^on/i.test(at.name)) S.inline.push(el.localName + ' ' + at.name + '=' + at.value.slice(0, 60));
    }
  };
  new MutationObserver(ms => {
    for (const m of ms) {
      for (const n of m.addedNodes) { if (n.nodeType === 3) tags(n.data); else look(n); }
      if (m.type === 'attributes') look(m.target);
    }
  }).observe(document, {childList: true, subtree: true, attributes: true, characterData: true,
                         attributeFilter: ['href', 'src', 'data-zz', 'srcdoc', 'title', 'value']});
})();
'''

# Что сделать на странице, чтобы показалось всё, что она умеет показать из плана. Ничего не правит в плане; кнопки
# «отметить», «надеть», «убрать», ссылки и выбор героя / плана не нажимаются.
ACTIONS = r'''
(async (kind) => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const SKIP = 'a, [data-fpage], [data-planfile], [data-cxpick], [data-cxrun], [data-cxgone], [data-cxrm], [data-cxyes], ' +
    '[data-cxadd], [data-cxsame], [data-goal], [data-move], [data-hold], [data-wear], [data-off], [data-set], [data-forget], ' +
    '[data-copydrop], [data-copyrow], [data-amark], [data-afrom], [data-atlasask], [data-hattr], [data-pendoff], [data-cfgv], ' +
    '[data-lang], [data-lgt], [data-leave], [data-gamepick], input, select, textarea';
  const click = async (sel, max = 40, pause = 40) => {
    let n = 0;
    for (const el of Array.from(document.querySelectorAll(sel))) {
      if (n >= max) break;
      if (!el.isConnected || el.matches(SKIP) || el.closest('a') || el.disabled) continue;
      el.click(); n++; await wait(pause);
    }
    return n;
  };
  const hover = async () => {
    for (const el of Array.from(document.querySelectorAll('.tt[data-tk], [data-tip], [title]')).slice(0, 120)) {
      el.dispatchEvent(new PointerEvent('pointermove', {bubbles: true})); el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
      await wait(10);
    }
    for (const box of document.querySelectorAll('.mbox')) {
      const dots = Array.from(box.querySelectorAll('circle'));
      const step = Math.max(1, Math.floor(dots.length / 80));
      for (let i = 0; i < dots.length; i += step) {
        const r = dots[i].getBoundingClientRect();
        if (!r.width) continue;
        box.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2}));
        await wait(8);
      }
    }
    for (const el of Array.from(document.querySelectorAll('svg line, svg path, svg rect')).slice(0, 60)) {
      const r = el.getBoundingClientRect();
      el.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, clientX: r.x + 1, clientY: r.y + 1}));
      await wait(5);
    }
  };
  const about = async () => {
    await click('[data-cfg="toggle"]', 1, 300);
    const o = document.querySelector('[data-cfgv="about:open"]');
    if (!o) return;
    o.click(); await wait(700);
    const shown = [];
    for (const name of ['LICENSE', 'NOTICE.md', 'THIRD-PARTY.md']) {
      const b = document.querySelector('#abt [data-abt="file:' + name + '"]');
      if (!b) continue;
      b.click(); await wait(700);
      const pre = document.querySelector('#abt pre.abx');
      if (pre && pre.textContent.length > 200) shown.push(name);
      const back = document.querySelector('#abt [data-abt="shut"]');
      if (back) { back.click(); await wait(200); }
    }
    window.__about = shown;
    const shut = document.querySelector('#abt [data-abt="shut"]');
    if (shut) { shut.click(); await wait(200); }
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await wait(100);
  };
  const header = async () => {
    await about();
    await click('[data-ctx="toggle"]', 1, 300);
    await click('[data-cxall]', 1, 200);
    await click('[data-cxnew]', 1, 300);
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await wait(100);
    await click('[data-ctx="toggle"]', 1, 200);
    await click('[data-cfg="toggle"]', 1, 300);
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await wait(100);
  };
  if (kind === 'play') {
    await header();
    await click('[data-open]', 60);
    await click('[data-peek]', 25, 60);
    await click('[data-strip]', 6, 80);
    await click('[data-map]', 8, 80);
    await click('[data-skill], [data-list], [data-jump], [data-atree], [data-rvo]', 30);
    await hover();
    await click('[data-open]', 60);
  } else if (kind === 'review') {
    await header();
    await click('[data-rvo], [data-open], [data-peek]', 40);
    await hover();
  } else if (kind === 'admin') {
    await header();
    await click('[data-more], [data-rmore], [data-smore], [data-stopen], [data-treeopen], [data-tver], [data-tkind], [data-tmap]', 80, 30);
    await hover();
    await click('[data-goto], [data-gostep]', 10, 80);
    await click('[data-plancopy]', 1, 300);
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  } else if (kind === 'list' || kind === 'tree') {
    if (window.ovArm) { window.ovArm(2); await wait(600); }
    await click('[data-open], [data-peek]', 20);
    await hover();
  }
  await wait(400);
  return true;
})
'''

COLLECT = r'''(() => {
  const P = window.__probe || {csp: [], err: [], zz: [], links: [], inline: []};
  const app = document.querySelector('#app');
  if (document.body) { for (const m of (document.body.innerText || '').matchAll(/(?:__hit=|x-zz>|Ш)(\d+)/g)) (P.seen || new Set()).add(+m[1]); }
  return {hit: window.__hit === undefined ? null : String(window.__hit), csp: P.csp, err: P.err, zz: P.zz.slice(0, 20),
          seen: Array.from(P.seen || []), about: window.__about || null,
          zzN: P.zz.length, links: P.links.slice(0, 20), inline: P.inline.slice(0, 20), inlineN: P.inline.length,
          drawn: !!(app && app.children.length && !app.querySelector(':scope > .wait')),
          text: (document.body ? document.body.innerText.length : 0)};
})()'''


# --- DevTools по веб-сокету (стандартная библиотека, без сторонних пакетов) -----------------------------------

class Socket:
    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(('GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                           'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (u.path, u.hostname, u.port, key)).encode())
        self.buf = bytearray()
        while b'\r\n\r\n' not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('DevTools: нет ответа')
            self.buf += chunk
        head, _, rest = bytes(self.buf).partition(b'\r\n\r\n')
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise ConnectionError('DevTools: %r' % head[:80])
        self.buf = bytearray(rest)

    def send(self, text):
        data = text.encode('utf-8')
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack('>H', n)
        else:
            head.append(0x80 | 127)
            head += struct.pack('>Q', n)
        mask = os.urandom(4)
        body = bytearray(data)
        for i in range(n):
            body[i] ^= mask[i & 3]
        self.sock.sendall(bytes(head) + mask + bytes(body))

    def _take(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError('DevTools закрыл соединение')
            self.buf += chunk
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def recv(self):
        msg = bytearray()
        while True:
            b1, b2 = self._take(2)
            n = b2 & 0x7f
            if n == 126:
                n = struct.unpack('>H', self._take(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._take(8))[0]
            if b2 & 0x80:
                self._take(4)
            payload = self._take(n)
            op = b1 & 0x0f
            if op == 0x8:
                raise ConnectionError('DevTools закрыл соединение')
            if op in (0x9, 0xa):
                continue
            msg += payload
            if b1 & 0x80:
                return msg.decode('utf-8', 'replace')


class DevTools:
    def __init__(self, url):
        self.ws = Socket(url)
        self.n = 0
        self.events = []

    def call(self, method, timeout=60, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params}))
        end = time.time() + timeout
        while True:
            self.ws.sock.settimeout(max(0.05, end - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except socket.timeout:
                raise TimeoutError(method)
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise RuntimeError('%s: %s' % (method, msg['error']))
                return msg.get('result') or {}
            if 'method' in msg:
                self.events.append(msg)

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.ws.sock.settimeout(max(0.05, end - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except socket.timeout:
                return
            if 'method' in msg:
                self.events.append(msg)

    def js(self, expr, timeout=60):
        res = self.call('Runtime.evaluate', timeout=timeout, expression=expr, returnByValue=True, awaitPromise=True)
        if res.get('exceptionDetails'):
            raise RuntimeError('JS: %s' % json.dumps(res['exceptionDetails'], ensure_ascii=False)[:400])
        return (res.get('result') or {}).get('value')


# --- пробная папка, сервер, браузер ---------------------------------------------------------------------------

def free_port():
    for p in PORTS:
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', p))
            except OSError:
                continue
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/' % p, timeout=0.3)
        except Exception:
            return p
    raise SystemExit('нет свободного порта среди %d–%d' % (PORTS[0], PORTS[-1]))


def base_plan(project):
    """Маршрут, билд и группы плана проекта (первого в библиотеке), коды фильтров — вымышленные, названия — «Фильтр N»;
    нет планов — свой маленький план hostile.base()."""
    lib = planlib.scan(project / 'plans')
    if not lib:
        return hostile.base()
    import planfiles
    rec = lib[0]
    parts = planfiles.read_parts(rec['path'], rec['manifest'])
    route, build = parts['route'], parts['build']
    codes = {}
    for s in route.get('steps') or []:
        if s.get('filter') and s['filter'] != 'none':
            s['filter'] = codes.setdefault(s['filter'], 'TrialAa%d' % (len(codes) + 1))
        if 'filterName' in s:
            s['filterName'] = 'Фильтр %s' % s.get('filter', '')[-1:]
    return route, build, list(rec['manifest'].get('groups') or [])


def prepare(out, route, build, groups):
    """Пробная папка: библиотека с планом героя, лог с героем «Проба», фильтры, настройки игры, буфер."""
    for d in ('plans', 'runs', 'archive', 'OnlineFilters', 'logs'):
        (out / d).mkdir(parents=True, exist_ok=True)
    pid = planlib.add(out / 'plans', hostile.bundle(route, build, groups, title='План героя Проба', uid='0b0b0b0b'))
    man = out / 'plans' / pid / planlib.MANIFEST
    raw = json.loads(man.read_text(encoding='utf-8'))
    raw.pop('received', None)
    planlib.write_manifest(man, raw)
    codes = sorted({s['filter'] for s in route.get('steps') or [] if s.get('filter') and s['filter'] != 'none'})
    for i, code in enumerate(codes, 1):
        (out / 'OnlineFilters' / code).write_text('#name:Фильтр %d\n#type:filter\nShow\n' % i, encoding='utf-8')
    (out / 'config.ini').write_text('[UI]\nitem_filter=%s\nlanguage=ru\n' % (codes[0] if codes else 'None'),
                                    encoding='utf-8')
    t = time.time() - 600
    stamp = lambda x: time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(x))     # noqa: E731
    lines = [stamp(t) + ' 1 a [INFO Client 1] [HTTP2] User agent: PoE poe2_production/tags/0.5.5h Windows x64']
    zones = [(1, 'G1_1', 'Берег реки'), (2, 'G1_2', 'Клирфелл'), (3, 'G1_3', 'Грязевая нора'), (4, 'G1_4', 'Грельвуд')]
    for i, (lvl, code, name) in enumerate(zones):
        t += 60
        lines += [stamp(t) + ' 1 a [DEBUG Client 1] Generating level %d area "%s" with seed 1' % (lvl, code),
                  stamp(t + 1) + ' 1 a [INFO Client 1] [SCENE] Set Source [%s]' % name]
        lines.append(stamp(t + 30) + ' 1 a [INFO Client 1] : Проба (Чародейка) достигает %d уровня' % (i + 2))
    (out / 'logs' / 'Client.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return pid


def start_server(planner, out, port, project):
    cmd = [sys.executable, '-X', 'utf8', '-u', str(planner / 'server.py'), '--port', str(port),
           '--log', str(out / 'logs' / 'Client.txt'), '--plans', str(out / 'plans'), '--runs', str(out / 'runs'),
           '--archive', str(out / 'archive'), '--filters', str(out / 'OnlineFilters'), '--config', str(out / 'config.ini'),
           '--settings', str(out / 'settings.json'), '--clip-file', str(out / 'clip.txt'), '--lang', 'ru']
    if (project / 'catalog' / 'data').is_dir():
        cmd += ['--catalog', str(project / 'catalog' / 'data')]
    if (project / 'knowledge').is_dir():
        cmd += ['--knowledge', str(project / 'knowledge')]
    log = open(out / 'server.log', 'w', encoding='utf-8')
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(out))
    for _ in range(120):
        time.sleep(0.25)
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/api/plans' % port, timeout=1).read()
            return proc
        except Exception:
            if proc.poll() is not None:
                raise SystemExit('сервер не запустился: %s' % (out / 'server.log'))
    raise SystemExit('сервер не ответил: %s' % (out / 'server.log'))


def start_chrome(out):
    exe = next((c for c in CHROMES if Path(c).is_file()), None)
    if not exe:
        raise SystemExit('нет Chrome или Edge')
    prof = out / 'chrome'
    args = [exe, '--headless=new', '--remote-debugging-port=0', '--user-data-dir=%s' % prof, '--no-first-run',
            '--no-default-browser-check', '--disable-extensions', '--disable-background-networking', '--disable-sync',
            '--disable-component-update', '--disable-default-apps', '--disable-domain-reliability', '--no-pings',
            '--metrics-recording-only', '--window-size=1280,900', 'about:blank']
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        time.sleep(0.2)
        f = prof / 'DevToolsActivePort'
        if f.is_file() and f.read_text().strip():
            port = int(f.read_text().split()[0])
            targets = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/list' % port))
            page = next(t for t in targets if t.get('type') == 'page')
            return proc, page['webSocketDebuggerUrl']
    raise SystemExit('Chrome не открыл DevTools')


def post(port, path, body):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (port, path), method='POST',
                                 data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode('utf-8') or '{}')


# --- виды ----------------------------------------------------------------------------------------------------
TABS = ('build', 'tree', 'route', 'stages', 'items', 'gems', 'other')
VIEWS = ([('play', '/', 'play'), ('review', '/review', 'review')]
         + [('admin#' + t, '/admin#' + t, 'admin') for t in TABS]
         + [('ov=list', '/?ov=list', 'list'), ('ov=answer', '/?ov=answer', 'answer'), ('ov=tree', '/?ov=tree', 'tree')])
READY = r'''(() => { const a = document.querySelector('#app'); const b = document.body;
  return !!(b && ((a && a.children.length && !a.querySelector(':scope > .wait')) || (b.innerText || '').length > 40)); })()'''


def visit(dt, port, name, url, kind, item=None, out=None):
    dt.events.clear()
    if item is not None:
        (out / 'clip.txt').write_text(item, encoding='utf-8')
    dt.call('Page.navigate', url='about:blank')
    dt.pump(0.2)
    dt.events.clear()
    dt.call('Page.navigate', url='http://127.0.0.1:%d%s' % (port, url))
    ok = False
    ready = READY if kind in ('play', 'review', 'admin') else "document.readyState === 'complete' && !!document.querySelector('#app')"
    for _ in range(80):
        dt.pump(0.25)
        try:
            ok = bool(dt.js(ready, timeout=10))
        except Exception:
            ok = False
        if ok:
            break
    dt.pump(1.2)
    try:
        dt.js('(%s)(%s)' % (ACTIONS.strip(), json.dumps(kind)), timeout=120)
    except Exception as e:
        res = {'actionError': str(e)[:300]}
    else:
        res = {}
    dt.pump(0.6)
    res.update(dt.js(COLLECT) or {})
    res['ready'] = ok
    ex = []
    for ev in dt.events:
        m, p = ev['method'], ev.get('params') or {}
        if m == 'Runtime.exceptionThrown':
            d = p.get('exceptionDetails') or {}
            ex.append('exception: %s @%s:%s' % (((d.get('exception') or {}).get('description') or d.get('text') or '')[:300],
                                               d.get('lineNumber'), d.get('columnNumber')))
        elif m == 'Log.entryAdded':
            e = p.get('entry') or {}
            if e.get('level') == 'error':
                where = 'network' if e.get('source') == 'network' else 'log'
                ex.append('%s: %s %s' % (where, (e.get('text') or '')[:200], (e.get('url') or '')[-80:]))
    res['events'] = ex
    return res


def judge(res, csp_on):
    """Что в ответе вида — провал: (отметки, разметка/ссылки, нарушения политики, ошибки страницы)."""
    hits = [res['hit']] if res.get('hit') else []
    markup = list(res.get('zz') or []) + list(res.get('links') or [])
    inline = [x for x in res.get('inline') or [] if 'data-zz' in x or '__hit' in x]
    csp = list(res.get('csp') or [])
    # сообщения консоли о нарушении политики — уже в csp (с политикой) или их нет вовсе (без неё): ошибкой второй раз не считаются
    errors = [e for e in list(res.get('err') or []) + [e for e in res.get('events') or [] if not e.startswith('network:')]
              if 'Content Security Policy' not in e]
    if not res.get('ready') or not res.get('drawn', True) and res.get('text', 0) < 40:
        errors.append('страница не нарисовалась')
    if res.get('actionError'):
        errors.append('действия на странице: ' + res['actionError'])
    return hits, markup + inline, csp, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description='Проверка страниц враждебными планами')
    ap.add_argument('--port', type=int, help='порт пробного сервера (по умолчанию — первый свободный из 4771–4779)')
    ap.add_argument('--planner', default=str(HERE), help='папка planner, чей сервер и страницы проверяются')
    ap.add_argument('--project', default=str(HERE.parent), help='папка проекта: план героя, каталог, справочник')
    ap.add_argument('--no-csp', action='store_true', help='выключить Content-Security-Policy (проверка одних esc)')
    ap.add_argument('--families', help='только эти наборы (через запятую)')
    ap.add_argument('--views', help='только эти виды (через запятую)')
    ap.add_argument('--out', help='куда положить пробную папку и отчёт (по умолчанию — временная)')
    ap.add_argument('--keep', action='store_true', help='не удалять пробную папку')
    args = ap.parse_args(argv)

    project, planner = Path(args.project).resolve(), Path(args.planner).resolve()
    out = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix='hostile-'))
    out.mkdir(parents=True, exist_ok=True)
    route, build, groups = base_plan(project)
    route, build = hostile.enrich(route, build)
    prepare(out, route, build, groups)
    plans = hostile.text_plans(route, build, groups)
    if args.families:
        want = set(args.families.split(','))
        plans = [p for p in plans if p[0] in want]
    views = [v for v in VIEWS if not args.views or v[0] in args.views.split(',')]
    port = args.port or free_port()
    server = start_server(planner, out, port, project)
    chrome, ws = start_chrome(out)
    report = {'port': port, 'csp': not args.no_csp, 'planner': str(planner), 'plans': [], 'baseline': []}
    totals = {'hits': 0, 'markup': 0, 'csp': 0, 'errors': 0, 'visits': 0, 'placements': 0, 'fields': 0, 'network': 0}
    try:
        dt = DevTools(ws)
        for domain in ('Page', 'Runtime', 'Log', 'Network'):
            dt.call(domain + '.enable')
        dt.call('Network.setBlockedURLs', urls=['*/api/open*', '*/api/game*', 'https://*', 'http://localhost*', 'ws://*'])
        dt.call('Page.addScriptToEvaluateOnNewDocument', source=PROBE)
        if args.no_csp:
            dt.call('Page.setBypassCSP', enabled=True)
        dt.call('Emulation.setDeviceMetricsOverride', width=1280, height=900, deviceScaleFactor=1, mobile=False)
        # прежде враждебных — план героя как есть: ошибки, которые есть и без чужих данных, — не от плана
        n = 0
        for name, url, kind in views:
            n += 1
            res = visit(dt, port, name, url, kind, ITEM.format(n=40 + n), out)
            hits, markup, csp, errors = judge(res, not args.no_csp)
            report['baseline'].append({'view': name, 'csp': csp, 'errors': errors})
        base_errors = {(b['view'], e) for b in report['baseline'] for e in b['errors']}
        for family, data, file_name, tags in plans:
            res = post(port, '/api/plans', {'import': data, 'file': file_name})
            row = {'family': family, 'fields': len(tags), 'import': res, 'views': []}
            report['plans'].append(row)
            if not res.get('ok'):
                totals['errors'] += 1
                print('  %-9s план не принят: %s' % (family, res.get('problems')), flush=True)
                continue
            pid = res['plan']
            use = post(port, '/api/plans', {'use': pid})
            if not use.get('ok'):
                totals['errors'] += 1
                print('  %-9s план не выбран: %s' % (family, use), flush=True)
                continue
            totals['fields'] += len(tags)
            for name, url, kind in views:
                n += 1
                res = visit(dt, port, name, url, kind, ITEM.format(n=40 + n), out)
                hits, markup, csp, errors = judge(res, not args.no_csp)
                errors = [e for e in errors if (name, e) not in base_errors]
                net = sum(1 for e in res.get('events') or [] if e.startswith('network:'))
                totals['visits'] += 1
                totals['placements'] += len(tags)
                totals['hits'] += len(hits)
                totals['markup'] += len(markup)
                totals['csp'] += len(csp)
                totals['errors'] += len(errors)
                totals['network'] += net
                if res.get('about') is not None:
                    totals['about'] = totals.get('about', 0) + 1
                    totals['aboutFiles'] = sorted(set(totals.get('aboutFiles', [])) | set(res['about']))
                seen = {t for t in res.get('seen') or [] if t in tags}
                row.setdefault('seen', set()).update(seen)
                row['views'].append({'view': name, 'seen': len(seen), 'hit': [(h, tags.get(int(h)) if str(h).isdigit() else None) for h in hits],
                                     'markup': markup[:10], 'csp': csp[:10], 'errors': errors[:10], 'network': net})
                bad = hits or markup or csp or errors
                print('  %-9s %-14s %s' % (family, name, 'ПРОВАЛ ' + json.dumps({'hit': hits, 'markup': markup[:2], 'csp': csp[:2],
                                                                                    'errors': errors[:2]}, ensure_ascii=False)[:600]
                                            if bad else 'чисто'), flush=True)
    finally:
        try:
            chrome.terminate()
        except Exception:
            pass
        server.terminate()
        try:
            server.wait(10)
            chrome.wait(10)
        except Exception:
            pass
    for row in report['plans']:
        row['seen'] = len(row.get('seen') or ())
    totals['seenBest'] = max([row['seen'] for row in report['plans']] or [0])
    report['totals'] = totals
    path = out / 'hostile-report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    fails = totals['hits'] + totals['markup'] + totals['csp'] + totals['errors']
    print('Политика страниц: %s. Планов: %d, полей в плане: %s, видов: %d, открытий страниц: %d.' % (
        'включена' if not args.no_csp else 'ВЫКЛЮЧЕНА (--no-csp)', len(plans), '/'.join(sorted({str(p[3] and len(p[3])) for p in plans})),
        len(views), totals['visits']))
    print('%d срабатываний из %d (вставок, побывавших на страницах); разметка из плана: %d; нарушений политики: %d; '
          'ошибок страниц: %d; ошибок сети (картинки): %d.' % (totals['hits'], totals['placements'], totals['markup'],
                                                                totals['csp'], totals['errors'], totals['network']))
    print('Покрытие: на страницах текстом побывало до %d из %s полей плана (по наборам: %s).' % (
        totals['seenBest'], '/'.join(sorted({str(len(p[3])) for p in plans})),
        ', '.join('%s %d' % (row['family'], row['seen']) for row in report['plans'])))
    if totals.get('about'):
        print('Окно «О программе» открыто на %d видах, показаны файлы: %s.' % (totals['about'], ', '.join(totals['aboutFiles']) or '—'))
    print('Отчёт: %s' % path)
    if not args.keep and not args.out:
        shutil.rmtree(out / 'chrome', ignore_errors=True)
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
