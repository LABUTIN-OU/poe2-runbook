# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Значок программы (app.ico): тёмная плашка, золотая дорога-«S» от точки старта к цели. Свой рисунок, без картинок
игры. Рисуется по формулам — каждый размер (16…256) отдельно, со сглаживанием. Без сторонних библиотек.

Запуск: python packaging/make_icon.py  ->  packaging/app.ico (и app.png 256×256 — посмотреть глазами)
"""
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIZES = (256, 64, 48, 40, 32, 24, 20, 16)

BG = (29, 24, 19)          # плашка
EDGE = (88, 72, 46)        # её кромка
ROAD = (212, 166, 74)      # дорога
GOAL = (240, 200, 110)     # цель
START = (150, 132, 98)     # старт


def bezier(p0, p1, p2, p3, n=48):
    out = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


P0, P3 = (0.25, 0.77), (0.73, 0.27)
ROUTE = bezier(P0, (0.18, 0.40), (0.82, 0.62), P3)
SEGS = [(ROUTE[i], ROUTE[i + 1]) for i in range(len(ROUTE) - 1)]


def seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    qx, qy = ax + t * dx - px, ay + t * dy - py
    return (qx * qx + qy * qy) ** 0.5


def round_rect(px, py, r=0.2, m=0.03):
    """Расстояние со знаком до скруглённого квадрата [m, 1-m] (внутри < 0)."""
    cx, cy = abs(px - 0.5), abs(py - 0.5)
    h = 0.5 - m - r
    qx, qy = max(cx - h, 0.0), max(cy - h, 0.0)
    out = (qx * qx + qy * qy) ** 0.5 - r
    return out if (qx > 0 or qy > 0) else max(cx - h, cy - h) - r


def shade(px, py, size):
    """Цвет точки (r, g, b, a) — слоями снизу вверх."""
    d = round_rect(px, py)
    if d > 0:
        return None
    line = 1.6 / size                      # кромка — около полутора пикселей на любом размере
    col = EDGE if d > -line else BG
    w = max(0.075, 1.15 / size)            # на мелких значках дорога не тоньше пикселя
    if min(seg_dist(px, py, a, b) for a, b in SEGS) < w:
        col = ROAD
    if (px - P0[0]) ** 2 + (py - P0[1]) ** 2 < 0.085 ** 2:
        col = START
    g = (px - P3[0]) ** 2 + (py - P3[1]) ** 2
    if g < 0.13 ** 2:
        col = GOAL
        if g < 0.05 ** 2 and size >= 32:     # на крупных — кольцо цели
            col = BG
    return col


def render(size, ss=4):
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            acc = [0, 0, 0]
            hit = 0
            for sy in range(ss):
                for sx in range(ss):
                    c = shade((x + (sx + 0.5) / ss) / size, (y + (sy + 0.5) / ss) / size, size)
                    if c:
                        hit += 1
                        acc[0] += c[0]
                        acc[1] += c[1]
                        acc[2] += c[2]
            if hit:
                row += bytes((acc[0] // hit, acc[1] // hit, acc[2] // hit, 255 * hit // (ss * ss)))
            else:
                row += b'\0\0\0\0'
        rows.append(bytes(row))
    return rows


def png(size, rows):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b''.join(b'\0' + r for r in rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def main():
    images = []
    for size in SIZES:
        images.append((size, png(size, render(size, 3 if size >= 128 else 5))))
    head = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b'', b''
    for size, data in images:
        entries += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    (HERE / 'app.ico').write_bytes(head + entries + blobs)
    (HERE / 'app.png').write_bytes(images[0][1])
    print('app.ico: %d sizes, %d bytes' % (len(images), len(head + entries + blobs)))


if __name__ == '__main__':
    main()
