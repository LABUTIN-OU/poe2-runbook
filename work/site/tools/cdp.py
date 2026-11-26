# -*- coding: utf-8 -*-
"""A headless Chrome driven over the DevTools protocol — standard library only (own small WebSocket client).
Used for screenshots at an exact viewport and pixel density, and for reading what a page requested."""
import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'


class WS:
    def __init__(self, url):
        assert url.startswith('ws://')
        host, _, path = url[5:].partition('/')
        name, _, port = host.partition(':')
        self.s = socket.create_connection((name, int(port or 80)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(('GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                        'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (path, host, key)).encode())
        head = b''
        while b'\r\n\r\n' not in head:
            head += self.s.recv(1)
        if b' 101 ' not in head.split(b'\r\n', 1)[0]:
            raise OSError('websocket refused: %r' % head[:200])

    def _read(self, n):
        buf = b''
        while len(buf) < n:
            part = self.s.recv(n - len(buf))
            if not part:
                raise OSError('websocket closed')
            buf += part
        return buf

    def send(self, text):
        data = text.encode('utf-8')
        mask = os.urandom(4)
        n = len(data)
        head = b'\x81' + (bytes([0x80 | n]) if n < 126 else b'\xfe' + struct.pack('>H', n) if n < 65536
                          else b'\xff' + struct.pack('>Q', n))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        out = b''
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7f
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            data = self._read(n)
            op = b1 & 0x0f
            if op == 8:
                raise OSError('websocket closed by the browser')
            if op == 9:                                   # ping -> pong
                self.s.sendall(b'\x8a\x80' + os.urandom(4))
                continue
            if op in (0, 1, 2):
                out += data
                if b1 & 0x80:
                    return out.decode('utf-8', 'replace')


class Tab:
    def __init__(self, ws_url):
        self.ws, self.n, self.events = WS(ws_url), 0, []

    def call(self, method, **params):
        self.n += 1
        mine = self.n
        self.ws.send(json.dumps({'id': mine, 'method': method, 'params': params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == mine:
                if 'error' in msg:
                    raise RuntimeError('%s: %s' % (method, msg['error']))
                return msg.get('result') or {}
            self.events.append(msg)

    def pump(self, seconds):
        """Collect events for a while (the socket has a timeout of its own)."""
        end = time.time() + seconds
        self.ws.s.settimeout(0.2)
        try:
            while time.time() < end:
                try:
                    self.events.append(json.loads(self.ws.recv()))
                except (socket.timeout, TimeoutError):
                    pass
        finally:
            self.ws.s.settimeout(60)

    def js(self, expr):
        r = self.call('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        if r.get('exceptionDetails'):
            raise RuntimeError('js: %s' % json.dumps(r['exceptionDetails'])[:400])
        return (r.get('result') or {}).get('value')

    def wait(self, expr, seconds=30, every=0.25):
        end = time.time() + seconds
        while time.time() < end:
            try:
                got = self.js('!!(%s)' % expr)       # a DOM element comes back as {} — empty, so ask for yes / no
            except RuntimeError:
                got = None
            if got:
                return got
            time.sleep(every)
        raise TimeoutError('page never reached: %s' % expr)

    def size(self, width, height, scale=2, mobile=False, dark=None):
        self.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=scale, mobile=mobile)
        if dark is not None:
            self.call('Emulation.setEmulatedMedia',
                      features=[{'name': 'prefers-color-scheme', 'value': 'dark' if dark else 'light'}])

    def go(self, url):
        self.call('Page.navigate', url=url)

    def shot(self, path, clip=None, full=False):
        params = {'format': 'png', 'captureBeyondViewport': bool(clip or full)}
        if clip:
            params['clip'] = dict(clip, scale=1)
        elif full:
            m = self.call('Page.getLayoutMetrics')['cssContentSize']
            params['clip'] = {'x': 0, 'y': 0, 'width': m['width'], 'height': m['height'], 'scale': 1}
        data = base64.b64decode(self.call('Page.captureScreenshot', **params)['data'])
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)
        return len(data)

    def rect(self, selector, pad=0):
        r = self.js('(function(){var e=document.querySelector(%s);if(!e)return null;var r=e.getBoundingClientRect();'
                    'return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height}})()' % json.dumps(selector))
        if not r:
            return None
        return {'x': max(0, r['x'] - pad), 'y': max(0, r['y'] - pad), 'width': r['width'] + 2 * pad, 'height': r['height'] + 2 * pad}


class Chrome:
    """One headless Chrome with a profile of its own inside the scratchpad; stop() ends exactly this process."""

    def __init__(self, profile, port):
        self.port = port
        Path(profile).mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen([CHROME, '--headless=new', '--remote-debugging-port=%d' % port,
                                      '--user-data-dir=%s' % profile, '--no-first-run', '--no-default-browser-check',
                                      '--disable-extensions', '--disable-background-networking', '--disable-sync',
                                      '--disable-component-update', '--hide-scrollbars', '--mute-audio',
                                      '--lang=en-US', 'about:blank'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                self._get('/json/version')
                return
            except OSError:
                time.sleep(0.25)
        raise OSError('Chrome did not start')

    def _get(self, path, method='GET'):
        req = urllib.request.Request('http://127.0.0.1:%d%s' % (self.port, path), method=method)
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode('utf-8'))

    def tab(self):
        t = self._get('/json/new?about:blank', 'PUT')
        tab = Tab(t['webSocketDebuggerUrl'])
        tab.call('Page.enable')
        tab.call('Runtime.enable')
        tab.call('Network.enable')
        return tab

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
