# -*- coding: utf-8 -*-
"""The site's pictures of the program, from the raw ones of make_shots.py. Nothing is resampled: a raw picture is
already twice as dense as it is shown at its largest; here it is saved as lossless WebP (smaller than lossy for flat
screens of text, and exact), and two pictures are put on a canvas of the program's own background.

    python -X utf8 pack_shots.py <raw dir> <out dir> <language code> [<language code> …]

The out dir is site/assets for a language that is on the site, work/site/shots for one that is not there yet (a trial
build takes them from there).

  list     the step list over the game                      1664 px wide   the first screen
  window   the program's window, the «Игра» page            2080 px wide   «Вы просто играете»
  late     the list with one goal late, first rows close up 1984 px wide   «Красная строка не уйдёт»
  answer   the answer to a copied item                      1120 px wide   «Надеть или выбросить»
  tiles    the three time tiles of the «Игра» page          2080 px wide   «В темпе автора»
  time     «Разбор»                                         1752 x 984     «Каждая минута на счету»
  plan     «Редактор», the route tab                        1040 x 584     «Знаете, как лучше?»"""
import sys
from pathlib import Path

from PIL import Image

raw, out = Path(sys.argv[1]), Path(sys.argv[2])
REVIEW, PLAN = (1752, 984), (1040, 584)
BG = (17, 19, 22)                    # the program's page background, --bg:#111316
WIDE = {'list': 1664, 'window': 2080, 'late': 1984, 'answer': 1120, 'tiles': 2080}
TILES_RATIO = 212 / 1772             # the strip of time tiles: height to width, as in the sample


def load(name, lang):
    return Image.open(raw / ('%s-%s.png' % (name, lang))).convert('RGB')


def centred(im, size):
    if im.width > size[0] or im.height > size[1]:
        raise SystemExit('a raw picture %s x %s does not fit its canvas %s x %s' % (im.size + size))
    c = Image.new('RGB', size, BG)
    c.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
    return c


def exact(im, size):
    """A full-width raw picture: already the canvas's size, give or take a pixel of rounding."""
    if abs(im.width - size[0]) > 2 or im.height < size[1] - 2:
        raise SystemExit('a full-width raw picture is %s x %s, its canvas is %s x %s' % (im.size + size))
    c = Image.new('RGB', size, BG)
    c.paste(im.crop((0, 0, min(im.width, size[0]), min(im.height, size[1]))), (0, 0))
    return c


def fade_bottom(im, rows=80):
    """The page goes on below the picture: the last rows melt into the background instead of being cut through."""
    px = im.load()
    for y in range(im.height - rows, im.height):
        k = (y - (im.height - rows)) / rows
        k = k * k
        for x in range(im.width):
            r, g, b = px[x, y]
            px[x, y] = (round(r + (BG[0] - r) * k), round(g + (BG[1] - g) * k), round(b + (BG[2] - b) * k))
    return im


def save(im, name):
    path = out / name
    im.save(path, 'WEBP', lossless=True, quality=100, method=6)
    print('%-18s %4d x %-4d %7d bytes' % (name, im.width, im.height, path.stat().st_size))


out.mkdir(parents=True, exist_ok=True)
for lang in sys.argv[3:]:
    for name, wide in WIDE.items():
        im = load(name, lang)
        if abs(im.width - wide) > 2:
            raise SystemExit('%s-%s is %d px wide, %d wanted' % (name, lang, im.width, wide))
        if name == 'tiles':
            # a raw strip taken with a wider margin above and below: the margin is trimmed equally to the sample's proportion
            tall = round(im.width * TILES_RATIO)
            if im.height > tall:
                top = (im.height - tall) // 2
                im = im.crop((0, top, im.width, top + tall))
        save(im, '%s-%s.webp' % (name, lang))
    save(centred(load('time', lang), REVIEW), 'time-%s.webp' % lang)
    save(fade_bottom(exact(load('plan', lang), PLAN)), 'plan-%s.webp' % lang)
