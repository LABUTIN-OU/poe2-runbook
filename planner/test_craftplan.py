# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка помощника крафта (craftplan.py): точный счёт шансов, набор свойств, десять примеров на настоящем
каталоге, форма предмета из статов этапа, предмет из копии и строка «КРАФТ» в карточке копии.

Запуск: python -X utf8 -m unittest planner.test_craftplan"""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import craftplan  # noqa: E402
import gamedata  # noqa: E402
import herostats  # noqa: E402
import i18n  # noqa: E402
import itemcopy  # noqa: E402
import server  # noqa: E402
import test_server  # noqa: E402

VERSION = '0.5.5.10'      # ответы примеров посчитаны по каталогу этой версии и выжимке весов poe2db
PAIR = re.compile(r' \([A-Z][^()]*\)')      # «Сфера царей (Regal Orb)»: английская половина названия
# Примеры подсессии крафта (work/craft/examples.json) с ответами её прототипа. Четыре числа прототип получал
# случайными пробами (1,4%, 40%, 40%, 8,8%); здесь стоят точные (1,3%, 39%, 39%, 8,7%).
EXAMPLES = json.loads('[{"title": "Ваш скипетр сейчас («Кровавая песнь», ур. 33), цель периода «Карты 6–10»: от +3", "item": {"base": "Rattling Sceptre", "ilvl": 33, "rarity": "rare", "mods": [{"id": "NearbyAlliesAddedPhysicalDamage2"}, {"id": "NearbyAlliesAddedColdDamage2"}, {"id": "LocalIncreasedSpiritPercent2"}, {"id": "GlobalMinionSpellSkillGemLevelWeapon2"}, {"id": "NearbyAlliesCriticalMultiplier1"}, {"id": "NearbyAlliesIncreasedCastSpeed2"}]}, "form": [{"stat": "minion_level", "role": "key", "min": 3}, {"stat": "spirit", "role": "max"}, {"stat": "ally_damage", "role": "max"}, {"stat": "ally_crit", "role": "fill"}], "hero": 33, "kind": "ceiling", "line": "у потолка: «уровень умений приспешников от +3» здесь не будет — ур. предмета 33, нужно 55 · не вкладывать, нужна новая база", "tree": []}, {"title": "Тот же скипетр, цель периода «После вознесения»: от +1", "item": {"base": "Rattling Sceptre", "ilvl": 33, "rarity": "rare", "mods": [{"id": "NearbyAlliesAddedPhysicalDamage2"}, {"id": "NearbyAlliesAddedColdDamage2"}, {"id": "LocalIncreasedSpiritPercent2"}, {"id": "GlobalMinionSpellSkillGemLevelWeapon2"}, {"id": "NearbyAlliesCriticalMultiplier1"}, {"id": "NearbyAlliesIncreasedCastSpeed2"}]}, "form": [{"stat": "minion_level", "role": "key", "min": 1}, {"stat": "spirit", "role": "max"}, {"stat": "ally_damage", "role": "max"}, {"stat": "ally_crit", "role": "fill"}], "hero": 33, "kind": "ceiling", "line": "у потолка мест: «27–32% увеличение духа», лучшее здесь «39–44% увеличение духа»; «урон союзников в присутствии»: префиксы заняты · поднять — только удалив свойство (риск задеть нужное)", "tree": []}, {"title": "Белый Гремящий скипетр, ур. 55", "item": {"base": "Rattling Sceptre", "ilvl": 55, "rarity": "normal", "mods": []}, "form": [{"stat": "minion_level", "role": "key", "min": 3}, {"stat": "spirit", "role": "max"}, {"stat": "ally_damage", "role": "max"}, {"stat": "ally_crit", "role": "fill"}], "hero": null, "kind": "catch", "line": "ловля «уровень умений приспешников от +3»: Большая сфера превращения (1,3%), легло на другую сторону — Большая сфера усиления (2,2%) · 2,2% на базу, в среднем ≈46 баз · не выпало — на верстак 3 → 1", "tree": ["Сфера превращения 0,3%, легло на другую сторону — Сфера усиления 0,5% → 0,5% на базу, в среднем ≈195 баз", "Большая сфера превращения 1,3%, легло на другую сторону — Большая сфера усиления 2,2% → 2,2% на базу, в среднем ≈46 баз", "Совершенная сфера превращения 1,7%, легло на другую сторону — Совершенная сфера усиления 2,4% → 2,4% на базу, в среднем ≈42 базы"]}, {"title": "Синий скипетр ур. 55: суффикс занят не тем, ключа нет", "item": {"base": "Rattling Sceptre", "ilvl": 55, "rarity": "magic", "mods": [{"id": "NearbyAlliesIncreasedCastSpeed3"}]}, "form": [{"stat": "minion_level", "role": "key", "min": 3}, {"stat": "spirit", "role": "max"}, {"stat": "ally_damage", "role": "max"}, {"stat": "ally_crit", "role": "fill"}], "hero": null, "kind": "waste", "line": "брак ловли: суффикс занят не тем · на верстак 3 → 1 (план Б: Сфера алхимии — ключ среди 4 свойств 1,3%)", "tree": []}, {"title": "Синий скипетр ур. 55 с «+3», герой 45", "item": {"base": "Rattling Sceptre", "ilvl": 55, "rarity": "magic", "mods": [{"id": "GlobalMinionSpellSkillGemLevelWeapon3"}]}, "form": [{"stat": "minion_level", "role": "key", "min": 3}, {"stat": "spirit", "role": "max"}, {"stat": "ally_damage", "role": "max"}, {"stat": "ally_crit", "role": "fill"}], "hero": 45, "kind": "next", "line": "дальше: Большая сущность повеления → Союзники в вашем присутствии наносят увеличенный на 75–89% урон (наверняка) · потребует 48 ур. героя (сейчас 45) · нет её — 3 × Сущность повеления на верстаке", "tree": []}, {"title": "Жёлтый скипетр ур. 55: «+3» и сущность повеления", "item": {"base": "Rattling Sceptre", "ilvl": 55, "rarity": "rare", "mods": [{"id": "GlobalMinionSpellSkillGemLevelWeapon3"}, {"id": "NearbyAlliesAllDamage6", "how": "crafted"}]}, "form": [{"stat": "minion_level", "role": "key", "min": 3}, {"stat": "spirit", "role": "max"}, {"stat": "ally_damage", "role": "max"}, {"stat": "ally_crit", "role": "fill"}], "hero": null, "kind": "next", "line": "дальше: Древняя челюсть + Предзнаменование некромантии левши → «дух от 40%» среди 3: 21% (любой: 39%); + Предзнаменование отголосков Бездны: 38% · промах — Предзнаменование света + Сфера отмены · план Б: Большая сфера возвышения + Предзнаменование возвышения левши → «дух от 40%» 4,8% (любой: 17%)", "tree": ["Древняя челюсть + Предзнаменование некромантии левши → «дух от 40%» среди 3: 21% (любой: 39%); + Предзнаменование отголосков Бездны: 38% · промах — Предзнаменование света + Сфера отмены", "Совершенная сфера возвышения + Предзнаменование возвышения левши → «дух от 40%» 11% (любой: 21%)", "Большая сфера возвышения + Предзнаменование возвышения левши → «дух от 40%» 4,8% (любой: 17%)", "Сохранившаяся челюсть + Предзнаменование некромантии левши → «дух от 40%» среди 3: 4,5% (любой: 74%); + Предзнаменование отголосков Бездны: 8,7% · промах — Предзнаменование света + Сфера отмены", "Сфера возвышения + Предзнаменование возвышения левши → «дух от 40%» 1,4% (любой: 29%)"]}, {"title": "Тот же, но очернение уже ушло в ненужный префикс", "item": {"base": "Rattling Sceptre", "ilvl": 55, "rarity": "rare", "mods": [{"id": "GlobalMinionSpellSkillGemLevelWeapon3"}, {"id": "NearbyAlliesAllDamage6", "how": "crafted"}, {"id": "IncreasedMana7", "how": "desecrated"}]}, "form": [{"stat": "minion_level", "role": "key", "min": 3}, {"stat": "spirit", "role": "max"}, {"stat": "ally_damage", "role": "max"}, {"stat": "ally_crit", "role": "fill"}], "hero": null, "kind": "next", "line": "дальше: Предзнаменование света + Сфера отмены — снять «+80–89 к максимуму маны», потом Древняя челюсть + Предзнаменование некромантии левши → «дух от 40%» среди 3: 21%; + Предзнаменование отголосков Бездны: 38% · план Б: Большая сфера возвышения + Предзнаменование возвышения левши → «дух от 40%» 7,4% (любой: 26%)", "tree": ["Предзнаменование света + Сфера отмены — снять «+80–89 к максимуму маны», потом Древняя челюсть + Предзнаменование некромантии левши → «дух от 40%» среди 3: 21%; + Предзнаменование отголосков Бездны: 38%", "Совершенная сфера возвышения + Предзнаменование возвышения левши → «дух от 40%» 14% (любой: 29%)", "Большая сфера возвышения + Предзнаменование возвышения левши → «дух от 40%» 7,4% (любой: 26%)", "Предзнаменование света + Сфера отмены — снять «+80–89 к максимуму маны», потом Сохранившаяся челюсть + Предзнаменование некромантии левши → «дух от 40%» среди 3: 4,5%; + Предзнаменование отголосков Бездны: 8,7%", "Сфера возвышения + Предзнаменование возвышения левши → «дух от 40%» 2,0% (любой: 40%)"]}, {"title": "Белый шлем на интеллект, ур. 45 (Венец из вермеля)", "item": {"base": "Vermeil Circlet", "ilvl": 45, "rarity": "normal", "mods": []}, "form": [{"stat": "minion_level", "role": "key", "min": 2}, {"stat": "es", "role": "max"}], "hero": null, "kind": "catch", "line": "ловля «уровень умений приспешников от +2»: Большая сфера превращения (1,5%), легло на другую сторону — Большая сфера усиления (2,8%) · 2,8% на базу, в среднем ≈35 баз · не выпало — на верстак 3 → 1", "tree": ["Сфера превращения 0,4%, легло на другую сторону — Сфера усиления 0,7% → 0,7% на базу, в среднем ≈146 баз", "Большая сфера превращения 1,5%, легло на другую сторону — Большая сфера усиления 2,8% → 2,8% на базу, в среднем ≈35 баз", "Совершенная сфера превращения 1,5%, легло на другую сторону — Совершенная сфера усиления 2,8% → 2,8% на базу, в среднем ≈35 баз"]}, {"title": "Белый шлем на интеллект, ур. 65 (Тиара небес)", "item": {"base": "Skycrown Tiara", "ilvl": 65, "rarity": "normal", "mods": []}, "form": [{"stat": "minion_level", "role": "key", "min": 2}, {"stat": "es", "role": "max"}], "hero": null, "kind": "catch", "line": "ловля «уровень умений приспешников от +2»: Большая сфера превращения (0,7%), легло на другую сторону — Большая сфера усиления (1,6%) · 1,6% на базу, в среднем ≈64 базы · не выпало — на верстак 3 → 1", "tree": ["Сфера превращения 0,2%, легло на другую сторону — Сфера усиления 0,5% → 0,5% на базу, в среднем ≈194 базы", "Большая сфера превращения 0,7%, легло на другую сторону — Большая сфера усиления 1,6% → 1,6% на базу, в среднем ≈64 базы", "Совершенная сфера превращения 1,4%, легло на другую сторону — Совершенная сфера усиления 2,6% → 2,6% на базу, в среднем ≈38 баз"]}, {"title": "Жёлтый фокус ур. 66: два префикса энергощита, два суффикса сопротивлений", "item": {"base": "Druidic Focus", "ilvl": 66, "rarity": "rare", "mods": [{"id": "LocalIncreasedEnergyShield9"}, {"id": "LocalIncreasedEnergyShieldPercent7_"}, {"id": "FireResist6"}, {"id": "ColdResist6"}]}, "form": [{"stat": "minion_level", "role": "key", "min": 1}, {"stat": "es", "role": "max"}], "hero": null, "kind": "next", "line": "дальше: Сохранившееся ребро + Предзнаменование некромантии правши (+ Предзнаменование отголосков Бездны) → «уровень умений приспешников от +1» (of Amanamu) среди 3 — шанс неизвестен: веса очернённых свойств не опубликованы · Обглоданное ребро не годится: только до ур. предмета 64", "tree": []}]')


# Скипетр, который пользователь скопировал в игре 2026-11-21 (русский клиент, Ctrl+Alt+C): синий Гремящий скипетр
# 65-го уровня с префиксом «Графский» (45–50% увеличение духа) и свободным суффиксом.
THEIR_SCEPTRE = ('Класс предмета: Скипетры\nРедкость: Волшебный\nГрафский Гремящий скипетр\n--------\nДух: 146 (augmented)\n'
                 '--------\nТребуется: Уровень 36\n--------\nУровень предмета: 65\n--------\n'
                 'Дарует умение: Приспешник скелет-воин 14 уровня\n--------\n{ Префикс "Графский" (Уровень: 4) }\n'
                 '46(45-50)% увеличение духа\n')


def mod(mid, lvl, side, w, fams):
    return {'id': mid, 'lvl': lvl, 'side': side, 'w': w, 'fams': list(fams)}


def brute(mods, pred, draws, cap=None, used=None):
    """Тот же шанс «все не те» в лоб: перебором самих свойств, как их тянула бы игра."""
    used = used or {'P': 0, 'S': 0}
    live = [m for m in mods if cap is None or used[m['side']] < cap]
    total = sum(m['w'] for m in live)
    if draws == 0 or not live or total <= 0:
        return 1.0
    acc = 0.0
    for m in live:
        if pred(m):
            continue
        rest = [x for x in mods if not set(x['fams']) & set(m['fams'])]
        acc += m['w'] / total * brute(rest, pred, draws - 1, cap, dict(used, **{m['side']: used[m['side']] + 1}))
    return acc


class MathTest(unittest.TestCase):
    def test_chance_of_all_misses_is_exact(self):
        """«Хотя бы одно нужное среди нескольких» считается точно: выпавшее свойство убирает из набора всю свою
        группу, у сферы алхимии — не больше трёх свойств на сторону. Сверено с перебором в лоб."""
        mods = [mod('a1', 1, 'P', 1000, ['A']), mod('a2', 30, 'P', 400, ['A']), mod('a3', 60, 'P', 100, ['A']),
                mod('b1', 1, 'P', 800, ['B']), mod('c1', 1, 'P', 500, ['C']), mod('d1', 1, 'P', 300, ['D']),
                mod('ab', 20, 'P', 250, ['A', 'B']),                                   # гибрид: убирает обе группы
                mod('e1', 1, 'S', 900, ['E']), mod('e2', 40, 'S', 200, ['E']), mod('f1', 1, 'S', 700, ['F']),
                mod('g1', 1, 'S', 50, ['G']), mod('x', 1, 'S', 120, [])]               # без группы: не убирает и себя
        for name, pred in (('a3', lambda m: m['id'] == 'a3'), ('e', lambda m: m['id'] in ('e2', 'g1')),
                           ('нет', lambda m: False), ('все', lambda m: True)):
            for draws in (1, 2, 3, 4):
                for cap in (None, 3, 2, 1):
                    self.assertAlmostEqual(craftplan.all_miss(mods, pred, draws, cap), brute(mods, pred, draws, cap),
                                           places=12, msg='%s, свойств %d, на сторону %s' % (name, draws, cap))
        self.assertEqual(craftplan.all_miss([], lambda m: True, 3), 1.0)
        self.assertEqual(craftplan.all_miss(mods, lambda m: True, 0), 1.0)
        # одно свойство из набора: шанс — доля веса
        self.assertAlmostEqual(craftplan.chance(mods, lambda m: m['side'] == 'S'), 1970 / 5320)

    def test_pool_and_the_threshold_of_greater_orbs(self):
        """Набор: не выше уровня предмета, на своей стороне, без занятых групп и без нулевого веса. Сфера с порогом
        убирает ступени ниже порога, а у семейства, которое всё ниже, оставляет высшую."""
        page = {'normal': [mod('a1', 1, 'P', 1000, ['A']), mod('a2', 30, 'P', 400, ['A']), mod('a3', 60, 'P', 100, ['A']),
                           mod('b1', 10, 'P', 800, ['B']), mod('b2', 50, 'P', 300, ['B']),
                           mod('e1', 1, 'S', 900, ['E']), mod('e2', 40, 'S', 200, ['E']), mod('z', 1, 'S', 0, ['Z'])]}
        ids = lambda mods: sorted(m['id'] for m in mods)        # noqa: E731
        self.assertEqual(ids(craftplan.pool(page, 55)), ['a1', 'a2', 'b1', 'b2', 'e1', 'e2'])
        self.assertEqual(ids(craftplan.pool(page, 55, 'S')), ['e1', 'e2'])
        self.assertEqual(ids(craftplan.pool(page, 55, None, frozenset(['A', 'E']))), ['b1', 'b2'])
        # порог 44: у A все доступные ступени ниже — остаётся высшая из них; у B — только 50-я; у E — высшая
        self.assertEqual(ids(craftplan.pool(page, 55, None, frozenset(), 44)), ['a2', 'b2', 'e2'])
        self.assertEqual(ids(craftplan.pool(page, 65, None, frozenset(), 44)), ['a3', 'b2', 'e2'])

    def test_each_line_of_one_group_keeps_its_top_tier(self):
        """Высшая ступень ниже порога остаётся у каждой строки свойства, даже когда строки — одна группа игры: у амулета
        «+# к уровню умений приспешников» и «… чар» вместе не бывают, но ступени у каждой свои. Раньше из группы
        оставалась одна строка — у «+2 приспешников» на амулете Большие сферы показывали «—»."""
        line = lambda mid, lvl, w, stat: dict(mod(mid, lvl, 'S', w, ['GemLevel']), st=[[stat, 1, 1]])     # noqa: E731
        page = {'normal': [line('m1', 5, 500, 'minion'), line('m2', 41, 250, 'minion'),
                           line('s1', 10, 500, 'spell'), line('s2', 41, 250, 'spell'), mod('e1', 1, 'S', 900, ['E'])]}
        ids = lambda mods: sorted(m['id'] for m in mods)        # noqa: E731
        self.assertEqual(ids(craftplan.pool(page, 50, None, frozenset(), 44)), ['e1', 'm2', 's2'])
        self.assertEqual(ids(craftplan.pool(page, 50, None, frozenset(['GemLevel']), 44)), ['e1'])

    def test_level_window_is_where_the_key_is_caught_best(self):
        """Окно уровня предмета: с уровня, где ключ уже бывает, и пока шанс поймать его на белой базе не падает. Шанс на
        базу — вес ключа к весу его стороны: превращение мимо стороны добирают усилением. Новая ступень на стороне ключа
        (b2 с 15-го) шанс снижает — окно кончается перед ней; ступень на другой стороне (a2) шанс не меняет."""
        # только обычные сферы: Большая ниже своего порога (44) оставила бы у семейства одну высшую ступень, и шанс
        # с ростом уровня не падал бы — так и есть в игре, но окно здесь проверяется на обычных
        cat = {'craft': {'rules': {'grades': {'transmute': [['T', 0]], 'augment': [['U', 0]]}}}}
        page = {'class': 'X', 'attr': None,
                'normal': [mod('k', 10, 'S', 100, ['K']), mod('a1', 1, 'P', 1000, ['A']), mod('a2', 20, 'P', 1000, ['A']),
                           mod('b1', 1, 'S', 500, ['B']), mod('b2', 15, 'S', 500, ['B'])]}
        key = lambda m: m['id'] == 'k'        # noqa: E731
        lo, hi, p, open_end = craftplan.window(cat, page, key, 'S', 1)
        self.assertEqual((lo, hi, open_end), (10, 14, False))
        self.assertAlmostEqual(p, 100 / 600)
        self.assertEqual(craftplan.window(cat, page, key, 'S', 12)[:2], (12, 14))      # база не ниже 12-го уровня
        # больше на стороне ключа ничего не появляется — окно открыто вверх
        other = dict(page, **{'class': 'Y', 'normal': [m for m in page['normal'] if m['id'] != 'b2']})
        lo, hi, _p, open_end = craftplan.window(cat, other, key, 'S', 1)
        self.assertEqual((lo, hi, open_end), (10, 20, True))
        self.assertIsNone(craftplan.window(cat, page, lambda m: False, 'S', 1))
        self.assertEqual([craftplan.span_text(*x) for x in ((55, 57, False), (65, 65, False), (41, 82, True))],
                         ['55–57', '65', '41+'])


def real():
    cat = gamedata.load(server.ROOT / 'catalog' / 'data')
    return cat if cat and (cat.get('craft') or {}).get('pages') and cat.get('version') == VERSION else None


class ExamplesTest(unittest.TestCase):
    def setUp(self):
        self.cat = real()
        if self.cat is None:
            self.skipTest('нет каталога версии %s с частью о крафте' % VERSION)

    def test_ten_examples_of_the_craft_session(self):
        """Скипетр игрока у потолка, ловля ключа на белой базе, брак синего, сущность, очернение и возвышение,
        шлем на двух уровнях, фокус с очернённым свойством «владыки» — ответы прототипа, строка в строку. Кроме
        примера 7 (очернение ушло в ненужный префикс): с 2026-11-23 — снять промах светом и отменой, потом снова кость
        (21%; возвышение 7,4% — план Б), как и обещает строка промаха кости."""
        for ex in EXAMPLES:
            t = time.perf_counter()
            res = craftplan.plan(self.cat, ex['item'], ex['form'], ex.get('hero'), 'ru')
            took = time.perf_counter() - t
            self.assertEqual((res['kind'], PAIR.sub('', str(res['line'])), [PAIR.sub('', str(x)) for x in res['tree']]),
                             (ex['kind'], ex['line'], ex['tree']), ex['title'])
            self.assertEqual(str(res['line']), ' · '.join(str(p) for p in res['parts']))
            self.assertLess(took, 0.5, ex['title'])            # карточка копии ждать не должна

    def test_names_come_with_the_english_one_and_the_answer_reads_in_english(self):
        ex = EXAMPLES[2]                                       # белый Гремящий скипетр, ур. 55
        res = craftplan.plan(self.cat, ex['item'], ex['form'], None, 'ru')
        self.assertIn('Большая сфера превращения (Greater Orb of Transmutation) (1,3%)', str(res['parts'][0]))
        names = i18n.Names('en', self.cat)
        for ex in EXAMPLES:
            res = craftplan.plan(self.cat, ex['item'], ex['form'], ex.get('hero'), 'en')
            shown = i18n.render({'craft': res}, 'en', names, plain=True)['craft']
            text = ' '.join([shown['line']] + shown['tree'])
            self.assertFalse(i18n.CYR.search(text), '%s: %s' % (ex['title'], text))
        white = i18n.render(craftplan.plan(self.cat, EXAMPLES[2]['item'], EXAMPLES[2]['form'], None, 'en'), 'en', names, plain=True)
        self.assertEqual(white['parts'][1:], ['2.2% per base, ≈46 bases on average', 'no hit — to the bench, 3 → 1'])

    def test_a_miss_is_fixed_only_when_the_item_holds_something_rarer(self):
        """Промах снимают Сферой отмены с предзнаменованием стороны, только если на предмете уже есть то, что реже
        самого шага: у жёлтого скипетра с «+3» (1 из 46 белых баз; очернённое — кости больше нельзя) возвышение на дух
        идёт с шансом 7,4% — промах снимают и повторяют. У синего скипетра с духом (1 из 21) ловля «+3» (1 из 58) —
        промах на верстак."""
        ex = EXAMPLES[6]
        item = dict(ex['item'], mods=[{'id': 'GlobalMinionSpellSkillGemLevelWeapon3', 'how': 'desecrated'},
                                      {'id': 'NearbyAlliesAllDamage6', 'how': 'crafted'}])
        card = craftplan.recipe(self.cat, item, ex['form'], {'minion_level', 'spirit', 'ally_damage'}, None, None, 'ru')
        self.assertEqual(PAIR.sub('', str(card['now']['tool'])), 'Большая сфера возвышения + Предзнаменование возвышения левши')
        self.assertEqual(PAIR.sub('', str(card['now']['miss'])),
                         'промах — Сфера отмены + Предзнаменование очищения левши: снять и повторить')
        blue = {'base': 'Rattling Sceptre', 'ilvl': 65, 'rarity': 'magic', 'mods': [{'id': 'LocalIncreasedSpiritPercent5'}]}
        card = craftplan.recipe(self.cat, blue, ex['form'], {'minion_level', 'spirit', 'ally_damage'}, None, None, 'ru')
        self.assertEqual(str(card['now']['miss']), 'промах — на верстак 3 → 1')

    def test_side_omen_only_when_the_other_side_has_room(self):
        """Предзнаменование стороны — только когда без него действие задело бы другую сторону. Амулет, скопированный
        2026-11-23 (ур. 50: три префикса, два суффикса): кость и возвышение и так дают суффикс — «Древняя ключица» без
        правши; «1 из 16» — нужное среди трёх вариантов Колодца душ (одно — 1 из 47). Места на обеих сторонах — с
        правшой. Снять промах со стороны, когда на другой нечего снимать, — Сфера отмены без предзнаменования; на
        предмете ничего, кроме очернённого, — без света."""
        game = craftplan.Game(self.cat)
        P = ['IncreasedPhysicalDamageReductionRatingPercent2', 'IncreasedLife5', 'MaximumLifeIncrease1']
        S = ['FireResist5', 'ColdResist3']
        form, wanted = [{'stat': 'minion_level', 'role': 'key', 'min': 2}], {'minion_level': 2}

        def item(*ids):
            return {'base': 'Stellar Amulet', 'ilvl': 50, 'rarity': 'rare', 'mods': [{'id': x} for x in ids]}

        def step(*ids):
            """Шаг и план Б: (что берут, чем снимают промах) — английскими названиями игры."""
            s = craftplan.plan(self.cat, item(*ids), form, None, 'ru')['step']
            return [(x['act'], x['uses'], x['miss']) for x in (s, s['alt'])]
        # три префикса заняты: правша лишняя и у кости, и у возвышения
        card = craftplan.recipe(self.cat, item(*P + S), form, wanted, None, None, 'ru')
        self.assertEqual((PAIR.sub('', str(card['now']['tool'])), card['now']['odds']), ('Древняя ключица', '1 из 16'))
        self.assertEqual(step(*P + S), [('bone', ['Ancient Collarbone', None], ['Omen of Light', 'Orb of Annulment']),
                                        ('exalt', ['Greater Exalted Orb', None], ['Orb of Annulment', 'Omen of Dextral Annulment'])])
        tree = craftplan.plan(self.cat, item(*P + S), form, None, 'ru')['tree']
        self.assertFalse([x for x in tree if 'правши' in str(x)], tree)
        # одно свойство из набора — 1 из 47; «1 из 16» — среди трёх вариантов
        page = craftplan.page_of(self.cat, game.base('Stellar Amulet'))
        taken = craftplan.state(game, item(*P + S), page)['taken']
        one = craftplan.chance(craftplan.pool(page, 50, 'S', taken, 40), lambda m: game.gives(m, 'minion_level', 2))
        self.assertEqual(craftplan.one_in(one), '1 из 47')
        # префиксов два — кость может лечь и в префикс: с правшой
        card = craftplan.recipe(self.cat, item(*P[:2] + S), form, wanted, None, None, 'ru')
        self.assertEqual(PAIR.sub('', str(card['now']['tool'])), 'Древняя ключица + Предзнаменование некромантии правши')
        # префиксов нет: добавить — с правшой (префиксы свободны), снять промах — без неё (в префиксах снимать нечего)
        self.assertEqual(step(*S), [('bone', ['Ancient Collarbone', 'Omen of Dextral Necromancy'], ['Omen of Light', 'Orb of Annulment']),
                                    ('exalt', ['Greater Exalted Orb', 'Omen of Dextral Exaltation'], ['Orb of Annulment', None])])
        self.assertEqual(PAIR.sub('', str(craftplan._miss(game, self.cat, {'act': 'exalt', 'p': 0.5, 'side': 'S',
                                                                           'miss': ['Orb of Annulment', None]}, 0.01))),
                         'промах — Сфера отмены: снять и повторить')
        # на предмете ничего: промах кости — одна Сфера отмены, без света
        self.assertEqual(step()[0][2], [None, 'Orb of Annulment'])

    def test_echoes_advice_next_to_a_desecration(self):
        """Рядом с шагом очернения — совет: Предзнаменование отголосков Бездны, две попытки по три варианта (их слова
        2026-11-23: «реролл использовать тогда будет 2 попытки по 3»). Цена места — без него: есть ли оно у игрока,
        помощник не знает. У свойства «владыки» — без шанса; у возвышения совета нет."""
        mods = ['IncreasedPhysicalDamageReductionRatingPercent2', 'IncreasedLife5', 'MaximumLifeIncrease1', 'FireResist5', 'ColdResist3']
        amulet = {'base': 'Stellar Amulet', 'ilvl': 50, 'rarity': 'rare', 'mods': [{'id': x} for x in mods]}
        form = [{'stat': 'minion_level', 'role': 'key', 'min': 2}]
        card = craftplan.recipe(self.cat, amulet, form, {'minion_level': 2}, None, None, 'ru')
        self.assertEqual(PAIR.sub('', str(card['now']['echo'])), 'Предзнаменование отголосков Бездны: 2 попытки по 3 — 1 из 8')
        self.assertEqual(card['places']['S'][2]['price'], '1 из 16')
        shown = i18n.render(craftplan.recipe(self.cat, amulet, form, {'minion_level': 2}, None, None, 'en'), 'en',
                            i18n.Names('en', self.cat), plain=True)
        self.assertEqual(shown['now']['echo'], 'Omen of Abyssal Echoes: 2 tries of 3 — 1 in 8')
        focus = EXAMPLES[9]
        card = craftplan.recipe(self.cat, focus['item'], focus['form'], {'minion_level'}, None, None, 'ru')
        self.assertEqual(PAIR.sub('', str(card['now']['echo'])), 'Предзнаменование отголосков Бездны: 2 попытки по 3')
        sceptre = dict(EXAMPLES[6]['item'], mods=[{'id': 'GlobalMinionSpellSkillGemLevelWeapon3', 'how': 'desecrated'},
                                                  {'id': 'NearbyAlliesAllDamage6', 'how': 'crafted'}])
        card = craftplan.recipe(self.cat, sceptre, EXAMPLES[6]['form'], {'minion_level', 'spirit', 'ally_damage'}, None, None, 'ru')
        self.assertIn('возвышения', str(card['now']['tool']))
        self.assertIsNone(card['now']['echo'])

    def test_after_a_bone_miss_the_card_clears_it_and_bones_again(self):
        """Их амулет 2026-11-23: кость легла в суффикс «+17–20 к силе» (очернённое). Карточка не «у потолка мест», а
        дальше по своей же строке промаха: шаг 1 — Предзнаменование света + Сфера отмены снимают именно очернённое,
        шаг 2 — снова кость на «+2» (1 из 16, место — там, где была сила). Очернённое с нужным статом не снимается."""
        mods = ['IncreasedPhysicalDamageReductionRatingPercent2', 'IncreasedLife5', 'MaximumLifeIncrease1', 'FireResist5', 'ColdResist3']
        form, wanted = [{'stat': 'minion_level', 'role': 'key', 'min': 2}], {'minion_level': 2}

        def card(last):
            item = {'base': 'Stellar Amulet', 'ilvl': 50, 'rarity': 'rare', 'mods': [{'id': x} for x in mods] + [last]}
            return craftplan.recipe(self.cat, item, form, wanted, None, None, 'ru')
        c = card({'id': 'Strength4', 'how': 'desecrated'})
        self.assertEqual(c['kind'], 'next')
        self.assertEqual(PAIR.sub('', str(c['now']['tool'])), 'Предзнаменование света + Сфера отмены — снять «+17–20 к силе»')
        self.assertEqual((c['now']['miss'], c['now']['echo']), (None, None))
        self.assertEqual([(x['kind'], x.get('n'), str(x.get('text')), x.get('price')) for x in c['places']['S']],
                         [('other', None, '+26–30% к сопротивлению огню', None), ('other', None, '+16–20% к сопротивлению холоду', None),
                          ('step', 2, 'уровень умений приспешников от +2', '1 из 16')])
        self.assertEqual([(s['n'], PAIR.sub('', str(s['tool'])), str(s['aim'])) for s in c['next']],
                         [(2, 'Древняя ключица', 'уровень умений приспешников от +2')])
        # та же сила, но не очернённая: снять её наверняка нечем — у потолка
        self.assertEqual(card({'id': 'Strength4'})['kind'], 'ceiling')
        # очернение попало: «+2» на месте — снимать нечего
        self.assertEqual(card({'id': 'GlobalMinionSpellSkillGemLevel2', 'how': 'desecrated'})['kind'], 'done')

    def test_greater_orbs_catch_minion_levels_on_an_amulet(self):
        """«Где искать базу» у «+2 к уровню умений приспешников» на амулете: Большие и Совершенные сферы дают шанс (раньше
        «—»: из группы уровней умений оставалась одна строка — «… чар»)."""
        game = craftplan.Game(self.cat)
        page = craftplan.page_of(self.cat, game.base('Stellar Amulet'))
        pred = lambda m: game.gives(m, 'minion_level', 2)        # noqa: E731
        self.assertEqual([craftplan.one_in(r[4]) for r in craftplan.catch(self.cat, page, 41, pred, 'S')],
                         ['1 из 208', '1 из 59', '1 из 59'])

    def test_below_the_goal_is_not_green(self):
        """Свойство стата с целью автора, но ниже неё, — не зелёное: урон союзников 35–44% при цели «от 75%». Цель про
        сумму на предмете («дух от 120») одним свойством не меряется — свойство духа зелёное."""
        wanted = {'minion_level': 3, 'ally_damage': 75, 'spirit': 120}
        item = {'base': 'Rattling Sceptre', 'ilvl': 65, 'rarity': 'magic',
                'mods': [{'id': 'NearbyAlliesAllDamage2'}, {'id': 'GlobalMinionSpellSkillGemLevelWeapon3'}]}
        card = craftplan.recipe(self.cat, item, EXAMPLES[2]['form'], wanted, None, None, 'ru')
        self.assertEqual([c['kind'] for c in (card['places']['P'][0], card['places']['S'][0])], ['low', 'have'])
        spirit = dict(item, mods=[{'id': 'LocalIncreasedSpiritPercent2'}])
        card = craftplan.recipe(self.cat, spirit, EXAMPLES[2]['form'], wanted, None, None, 'ru')
        self.assertEqual(card['places']['P'][0]['kind'], 'have')

    def test_what_has_no_answer(self):
        item = dict(EXAMPLES[2]['item'])
        form = EXAMPLES[2]['form']
        self.assertEqual(craftplan.plan(self.cat, dict(item, corrupted=True), form)['kind'], 'stop')
        self.assertEqual(craftplan.plan(self.cat, dict(item, base='Нет такой базы'), form)['kind'], 'none')
        self.assertEqual(craftplan.plan(self.cat, item, [])['kind'], 'none')
        # стат, которого на этом классе не бывает вовсе: ловить нечего
        self.assertEqual(craftplan.plan(self.cat, item, [{'stat': 'speed', 'role': 'key'}])['kind'], 'none')
        # порог про сумму на предмете («дух от 120» — база и процент вместе) одному свойству не ставится
        res = craftplan.plan(self.cat, item, [{'stat': 'spirit', 'role': 'key', 'min': 120}])
        self.assertEqual(res['kind'], 'catch')
        self.assertIn('ловля «дух»', str(res['parts'][0]))


SLOTS = [('weapon', 'Оружие', 'Sceptre'), ('helmet', 'Шлем', 'Helmet int_armour'), ('body', 'Доспех', 'Body Armour int_armour'),
         ('gloves', 'Перчатки', 'Gloves int_armour'), ('boots', 'Сапоги', 'Boots int_armour'), ('belt', 'Пояс', 'Belt'),
         ('amulet', 'Амулет', 'Amulet'), ('ring', 'Кольцо', 'Ring')]
AT = {'slots': [{'id': a, 'name': b, 'gear': c} for a, b, c in SLOTS],
      'stats': [{'id': s} for s in ('minion_level', 'spirit', 'ally_damage', 'res_fire', 'es')]}
FLOORS = [{'stat': 'minion_level', 'min': 1, 'goal': 'm1'}, {'stat': 'minion_level', 'min': 3, 'goal': 'm3'},
          {'stat': 'spirit', 'min': 120, 'goal': 'sp'}]


class FormTest(unittest.TestCase):
    def setUp(self):
        self.cat = real()
        if self.cat is None:
            self.skipTest('нет каталога версии %s с частью о крафте' % VERSION)

    def test_form_comes_from_the_stats_of_the_stage(self):
        """Форму автор не пишет: редкие статы этапа, которые бывают на предмете, — ключ и «к максимуму», остальные —
        наполнитель. Ключ — первый редкий стат с целью на этом слоте; его порог — ближайшая недостигнутая цель."""
        form = craftplan.default_form(self.cat, AT, 'weapon', 'Sceptre', FLOORS, {'m3'})
        self.assertEqual(form[0], {'stat': 'minion_level', 'role': 'key', 'min': 3})
        self.assertEqual([(e['stat'], e['role']) for e in form[1:]], [('spirit', 'max'), ('ally_damage', 'max')])
        # цель «от +1» ещё не достигнута — ловят её; все достигнуты — держат старшую
        self.assertEqual(craftplan.default_form(self.cat, AT, 'weapon', 'Sceptre', FLOORS, {'m1', 'm3'})[0]['min'], 1)
        self.assertEqual(craftplan.default_form(self.cat, AT, 'weapon', 'Sceptre', FLOORS, set())[0]['min'], 3)
        # цели у редкого стата нет — ключ первый редкий, без порога
        self.assertEqual(craftplan.default_form(self.cat, AT, 'weapon', 'Sceptre')[0], {'stat': 'minion_level', 'role': 'key'})
        # шлем: уровень приспешников бывает и на нём; обычные статы — наполнитель
        helmet = craftplan.default_form(self.cat, AT, 'helmet', 'Helmet')
        self.assertEqual(helmet[0], {'stat': 'minion_level', 'role': 'key'})
        self.assertIn({'stat': 'res_fire', 'role': 'fill'}, helmet)
        # у слота без редких статов ключа нет — формы нет
        self.assertEqual(craftplan.default_form(self.cat, AT, 'boots', 'Boots'), [])

    def test_stats_with_goals_on_the_slot_come_right_after_the_key(self):
        """После ключа — статы, у которых на этом слоте есть цели автора: сущность на синем шлеме пойдёт на энергощит
        (цель «от 300»), а не на сопротивление огню, которое в списке этапа стоит раньше."""
        floors = [{'stat': 'minion_level', 'min': 2, 'goal': 'h2'}, {'stat': 'es', 'min': 300, 'goal': 'hes'}]
        helmet = craftplan.default_form(self.cat, AT, 'helmet', 'Helmet', floors, {'h2'})
        self.assertEqual([(e['stat'], e['role']) for e in helmet[:3]], [('minion_level', 'key'), ('es', 'fill'), ('res_fire', 'fill')])
        blue = {'base': 'Skycrown Tiara', 'ilvl': 66, 'rarity': 'magic', 'mods': [{'id': 'GlobalMinionSpellSkillGemLevel2'}]}
        res = craftplan.plan(self.cat, blue, helmet, None, 'ru')
        self.assertEqual(res['step']['act'], 'essence')
        self.assertEqual(PAIR.sub('', str(res['parts'][0])), 'дальше: Большая сущность улучшения → 68–79% увеличение энергетического щита (наверняка)')
        # запасная сущность — ступенью ниже, а не та же самая (у одной сущности бывают свойства на броню, уклонение, энергощит)
        self.assertEqual(PAIR.sub('', str(res['parts'][1])), 'нет её — 3 × Сущность улучшения на верстаке')


def sceptre_text(cat, rarity, *mods, ilvl=55, base='Rattling Sceptre', cls='Sceptre'):
    """Копия предмета (без base и cls — Гремящего скипетра) из русского клиента (Ctrl+Alt+C): слова клиента — из
    слоя языка каталога. mods — (заголовок, строка свойства)."""
    ru = cat['lang']['ru']
    cls = next(w for w, cid in ru['classes'].items() if cid == cls)
    base = ru['bases'][base]
    head = ['Класс предмета: %s' % cls, 'Редкость: %s' % rarity] + (['Кровавая песнь', base] if rarity == 'Редкий' else [base])
    rows = ['--------', 'Уровень предмета: %d' % ilvl]
    if mods:
        rows.append('--------')
        for title, line in mods:
            rows += ['{ %s }' % title, line]
    return '\n'.join(head + rows) + '\n'


def line_of(cat, stat, value):
    """Строка свойства, как её пишет русский клиент: «+3 к уровню всех умений приспешников»."""
    shape = cat['lang']['ru']['stats'][stat][0]
    return ('+' if not shape.startswith('#%') else '') + shape.replace('#', str(value), 1)


class CopyTest(unittest.TestCase):
    def setUp(self):
        self.cat = real()
        if self.cat is None:
            self.skipTest('нет каталога версии %s с частью о крафте' % VERSION)

    def read(self, text):
        return itemcopy.identify(self.cat, itemcopy.parse(text))

    def test_item_from_the_copy(self):
        """Свойство копии находит свою ступень в игре: по диапазону чисел, у свойства с одним числом — по числу.
        Пометки «ремесленное» и «очернённое» доходят до помощника."""
        plus3 = line_of(self.cat, 'minion_skill_gem_level_+', 3)
        item = self.read(sceptre_text(self.cat, 'Волшебный', ('Суффикс "Надзирателя" (Уровень: 2) — Приспешник', plus3)))
        thing = craftplan.copied_item(self.cat, item)
        self.assertEqual((thing['base'], thing['ilvl'], thing['rarity'], thing['corrupted']), ('Rattling Sceptre', 55, 'magic', False))
        self.assertEqual([(m['id'], m['side'], m['how']) for m in thing['mods']],
                         [('GlobalMinionSpellSkillGemLevelWeapon3', 'S', None)])
        spirit = line_of(self.cat, 'local_spirit_+%', '28(27-32)')
        item = self.read(sceptre_text(self.cat, 'Редкий', ('Очернённый префикс "Маркиза" (Уровень: 5) — Дух', spirit),
                                      ('Суффикс "Надзирателя" (Уровень: 2) — Приспешник', plus3 + ' (crafted)')))
        thing = craftplan.copied_item(self.cat, item)
        self.assertEqual([(m['id'], m['side'], m['how']) for m in thing['mods']],
                         [('LocalIncreasedSpiritPercent2', 'P', 'desecrated'),
                          ('GlobalMinionSpellSkillGemLevelWeapon3', 'S', 'crafted')])
        # неопознанный и уникальный предмет помощнику не идут
        self.assertIsNone(craftplan.copied_item(self.cat, dict(item, identified=False)))
        self.assertIsNone(craftplan.copied_item(self.cat, dict(item, rarity='unique')))
        self.assertIsNone(craftplan.copied_item(self.cat, None))


class CardTest(unittest.TestCase):
    """Строка «КРАФТ» в карточке копии: программа с планом, где скипетру к шагу «Клирфелл» нужен уровень умений
    приспешников от +3."""

    def setUp(self):
        self.cat = real()
        if self.cat is None:
            self.skipTest('нет каталога версии %s с частью о крафте' % VERSION)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.log, self.plan, self.runs = root / 'Client.txt', root / 'plan.json', root / 'runs'
        self.log.write_text(test_server.LOG, encoding='utf-8')
        ru = self.cat['lang']['ru']
        word = next(w for w, cid in ru['classes'].items() if cid == 'Sceptre')
        slots = [{'id': a, 'name': b, 'classes': [c.split(' ')[0] if a != 'body' else 'Body Armour'], 'gear': c} for a, b, c in SLOTS]
        slots[0]['classes'] = ['Sceptre', word]
        plan = dict(test_server.PLAN, slots=slots,
                    stages=[{'id': 'start', 'name': 'Старт', 'stats': ['minion_level', 'spirit', 'ally_damage', 'res_fire']}],
                    goals=[{'id': 'weapon-any', 'slot': 'weapon', 'title': 'любой', 'any': True},
                           {'id': 'weapon-minion', 'slot': 'weapon', 'part': 'minion', 'label': 'уровень умений приспешников',
                            'stat': 'minion_level', 'min': 3, 'title': 'от +3', 'need': 'clearfell'}])
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        self.app = server.App(self.log, self.plan, self.runs)
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        if getattr(self, 'tmp', None):
            self.tmp.cleanup()

    def craft(self, text, lang='ru'):
        self.assertTrue(self.app.take_copy(text, ts=100.0))
        v = self.app.view(lang)
        self.assertEqual(self.app.plan_problems, [])
        return v['copy']['rows'][0].get('craft')

    def test_card_in_the_copy_card(self):
        """Карточка рецепта в карточке копии. Белый скипетр: шаг сейчас — ловля «+3» (план к «Клирфеллу» требует «+3»),
        он же — суффикс на первом месте; промах — на верстак. База 33-го уровня: «база мала», шагов нет. Синий с «+3»:
        всё, что ловит план (у этого плана — только ключ), на месте — «готово по плану». На английском — ни слова
        по-русски."""
        white = self.craft(sceptre_text(self.cat, 'Обычный'))
        card = white['recipe']
        self.assertEqual((white['kind'], str(card['rarity']), card['ilvl']), ('catch', 'белый', 55))
        self.assertEqual([c['kind'] for c in card['places']['S']], ['now', 'free', 'free'])
        self.assertEqual(str(card['places']['S'][0]['text']), 'уровень умений приспешников от +3')
        self.assertEqual(PAIR.sub('', str(card['now']['tool'])),
                         'Большая сфера превращения, легло на другую сторону — Большая сфера усиления')
        self.assertEqual(str(card['now']['miss']), 'промах — на верстак 3 → 1')
        small = self.craft(sceptre_text(self.cat, 'Обычный', ilvl=33))['recipe']
        self.assertEqual((small['kind'], str(small['now']['line'])),
                         ('small', 'база мала: «уровень умений приспешников от +3» бывает с ур. предмета 55'))
        self.assertFalse([c for side in small['places'].values() for c in side if c['kind'] in ('now', 'step')])
        blue = self.craft(sceptre_text(self.cat, 'Волшебный', ('Суффикс "Надзирателя" (Уровень: 2) — Приспешник',
                                                                 line_of(self.cat, 'minion_skill_gem_level_+', 3))))['recipe']
        self.assertEqual((blue['kind'], str(blue['now']['line']), blue['places']['S'][0]['kind']), ('done', 'готово по плану', 'have'))
        en = self.craft(sceptre_text(self.cat, 'Обычный'), 'en')
        shown = i18n.render(en, 'en', i18n.Names('en', self.cat), plain=True)
        self.assertFalse(i18n.CYR.search(json.dumps(shown, ensure_ascii=False)), shown)
        self.assertEqual(shown['recipe']['now']['miss'], 'miss — to the bench, 3 → 1')


def mod_line(cat, mod_id, pick=0.5):
    """Строка свойства, как её пишет русский клиент: число с диапазоном ступени («30(27-32)% увеличение духа»), у
    свойства с одним числом — без диапазона («+2 к уровню…»)."""
    fam, tier = next((f, m) for f in cat['mods'].values() for m in f['mods'] if m['id'] == mod_id)
    vals = dict(zip(fam['stats'], tier['vals']))
    key = fam['lines'][0]
    shape = cat['lang']['ru']['stats'][key]
    text = shape[0] if isinstance(shape, list) else shape
    for sid in key.split():
        lo, hi = vals[sid]
        text = text.replace('#', str(lo) if lo == hi else '%d(%d-%d)' % (round(lo + (hi - lo) * pick), lo, hi), 1)
    return ('+' + text) if str((fam.get('fmt') or [''])[0]).startswith('+') and not text.startswith('+') else text


# План для пути крафта и сроков на удачу: на шаге «Клирфелл» (он сейчас) скипетру нужен «+3» (а «+1» — уже с прошлого
# шага), дух от 120 (сумма на предмете) и урон союзников от 75% (его наверняка даёт сущность); шлему — «+2» и энергощит
# от 300; у сапог целей нет — их ключ (скорость передвижения) без порога. В логе после «Клирфелла» — карта 72-го уровня
# и 70-й уровень героя.
PATH_LOG = test_server.LOG + (
    '2026/11/11 21:00:00 1 a [DEBUG Client 1] Generating level 72 area "MapTrialRuins" with seed 9\n'
    '2026/11/11 21:00:01 1 a [INFO Client 1] [SCENE] Set Source [Пробные руины]\n'
    '2026/11/11 21:05:00 1 a [INFO Client 1] : Проба (Чародейка) достигает 70 уровня\n')
PATH_GOALS = [
    {'id': 'w-sceptre', 'slot': 'weapon', 'title': 'Гремящий скипетр (Rattling Sceptre)', 'need': 'clearfell'},
    {'id': 'w-minion-1', 'slot': 'weapon', 'part': 'minion', 'label': 'уровень умений приспешников', 'stat': 'minion_level',
     'min': 1, 'title': 'от +1', 'need': 'riverbank'},
    {'id': 'w-minion-3', 'slot': 'weapon', 'part': 'minion', 'stat': 'minion_level', 'min': 3, 'title': 'от +3', 'need': 'clearfell'},
    {'id': 'w-spirit', 'slot': 'weapon', 'part': 'spirit', 'label': 'дух скипетра', 'stat': 'spirit', 'min': 120,
     'title': 'от 120', 'need': 'clearfell'},
    {'id': 'w-ally', 'slot': 'weapon', 'part': 'ally', 'label': 'урон союзников', 'stat': 'ally_damage', 'min': 75,
     'title': 'от 75%', 'need': 'clearfell'},
    {'id': 'h-minion-2', 'slot': 'helmet', 'part': 'minion', 'label': 'уровень умений приспешников', 'stat': 'minion_level',
     'min': 2, 'title': 'от +2', 'need': 'clearfell'},
    {'id': 'h-es', 'slot': 'helmet', 'part': 'es', 'label': 'энергощит шлема', 'stat': 'es', 'min': 300, 'title': 'от 300',
     'need': 'clearfell'},
    {'id': 'h-minion-free', 'slot': 'helmet', 'part': 'minion2', 'label': 'уровень умений приспешников', 'stat': 'minion_level',
     'min': 2, 'title': 'от +2 без срока'},
    # у сапог цель по стату, которого в списке этапа нет: строка слота есть, а ключ — скорость передвижения, без цели
    {'id': 'b-life', 'slot': 'boots', 'part': 'life', 'label': 'здоровье сапог', 'stat': 'life', 'min': 50, 'title': 'от 50',
     'need': 'clearfell'},
]


class SlotPathTest(unittest.TestCase):
    """Блок «Как сделать» в карточке слота (craftplan.slot_card через server._stats_view: карточка рецепта и где
    искать базу), карточка копии с теми же частями и срок на удачу на «Билд»."""

    def setUp(self):
        self.cat = real()
        if self.cat is None:
            self.skipTest('нет каталога версии %s с частью о крафте' % VERSION)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.log, self.plan, self.runs = root / 'Client.txt', root / 'plan.json', root / 'runs'
        self.log.write_text(PATH_LOG, encoding='utf-8')
        ru = self.cat['lang']['ru']
        word = next(w for w, cid in ru['classes'].items() if cid == 'Sceptre')
        slots = [{'id': 'weapon', 'name': 'Оружие', 'classes': ['Sceptre', word], 'gear': 'Sceptre'},
                 {'id': 'helmet', 'name': 'Шлем', 'classes': ['Helmet'], 'gear': 'Helmet int_armour'},
                 {'id': 'boots', 'name': 'Сапоги', 'classes': ['Boots'], 'gear': 'Boots int_armour'}]
        plan = dict(test_server.PLAN, slots=slots, goals=PATH_GOALS,
                    stages=[{'id': 'start', 'name': 'Старт', 'kind': 'int_armour',
                             'stats': ['minion_level', 'spirit', 'ally_damage', 'ally_crit', 'speed', 'res_fire']}])
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        self.app = server.App(self.log, self.plan, self.runs)
        with self.app.cond:
            self.app.load_plan()
            self.app.poll_log(initial=True)
            self.app.attach_run()

    def tearDown(self):
        if getattr(self, 'tmp', None):
            self.tmp.cleanup()

    def rows(self, lang='ru'):
        v = self.app.view(lang)
        self.assertEqual(self.app.plan_problems, [])
        rows = [r for r in v.get('holders') or [] if r.get('slot')]
        return {r['slot']: r for r in rows}

    def wear(self, text):
        self.assertTrue(self.app.take_copy(text, ts=100.0))
        row = self.app.view()['copy']['rows'][0]
        self.assertTrue(self.app.wear({'row': row['row']}))

    def test_card_of_an_empty_slot(self):
        """Ничего не надето: карточка рецепта — белая база в окне, где «+3» ловится лучше всего, и шаги только к тому,
        что нужно плану: ловля «+3», сущность на урон союзников, очернение на дух (цели по всем трём); у крита союзников
        цели нет — шага нет. Где искать базу: «+3» уже падает (карта 72-го уровня), «+4» — с T14; у каждой ступени —
        база, окно уровня, шанс на белую базу для трёх ступеней сфер."""
        how = self.rows()['weapon']['howto']
        card, found = how['recipe'], how['hunt']
        self.assertEqual((PAIR.sub('', str(card['base'])), card['ilvl'], card['worn']), ('Гремящий скипетр', 55, False))
        self.assertEqual([(c['kind'], c.get('n'), str(c.get('text', '')), str(c.get('price', ''))) for c in card['places']['S']],
                         [('now', 1, 'уровень умений приспешников от +3', '1 из 46'), ('free', None, '', ''), ('free', None, '', '')])
        self.assertEqual([(c.get('n'), str(c.get('text', ''))) for c in card['places']['P']],
                         [(2, 'урон союзников в присутствии 75–89%'), (3, 'дух от 40%'), (None, '')])
        self.assertEqual(PAIR.sub('', str(card['now']['tool'])),
                         'Большая сфера превращения, легло на другую сторону — Большая сфера усиления')
        self.assertEqual([PAIR.sub('', str(s['tool'])) for s in card['next']],
                         ['Большая сущность повеления', 'Древняя челюсть + Предзнаменование некромантии левши'])
        self.assertEqual(str(found['answer']), 'Выбивать +3 сейчас — +4 только с T14')
        m3, m4 = found['marks']
        self.assertEqual((m3['value'], PAIR.sub('', str(m3['base'])), [str(o['odds']) for o in m3['odds']], str(m3['now'])),
                         ('+3', 'белая база: Гремящий скипетр, ур. 55–57', ['1 из 195', '1 из 46', '1 из 42'], '1 из 71'))
        self.assertEqual((m4['value'], str(m4['where']), [str(o['odds']) for o in m4['odds']], m4['now']),
                         ('+4', 'T14', ['1 из 594', '1 из 202', '1 из 96'], None))
        # герой ниже требования свойства сущности — шаг это говорит; герою 70-го уровня — ни слова
        import herostats
        at = herostats.at_step(self.app.catalog, self.app.plan, 1)
        low = craftplan.slot_card(self.app.catalog, at, self.rows()['weapon'], None, 40, 72)
        self.assertEqual(str(low['recipe']['next'][0]['need']), 'потребует 48 ур. героя (сейчас 40)')
        self.assertIsNone(card['next'][0]['need'])

    def test_card_of_the_worn_item(self):
        """Надет скипетр 33-го уровня: «+3» на нём не бывает — у потолка, шагов нет; на местах — что на нём стоит, с ценой
        в белых базах, «+2» — ниже цели. Где искать базу — «+3» уже падает. Надет синий с «+3»: шаг сейчас — сущность на
        урон союзников (наверняка, промаха нет); дальше по ключу — только «+4» с T14."""
        ru = 'Очернённое Префикс "Маркиза" (Уровень: 7)'
        self.wear(sceptre_text(self.cat, 'Редкий', (ru, mod_line(self.cat, 'LocalIncreasedSpiritPercent2')),
                               ('Суффикс "Надзирателя" (Уровень: 3)', mod_line(self.cat, 'GlobalMinionSpellSkillGemLevelWeapon2')),
                               ilvl=33))
        how = self.rows()['weapon']['howto']
        card = how['recipe']
        self.assertEqual((card['kind'], card['worn'], card['next']), ('ceiling', True, []))
        self.assertTrue(str(card['now']['line']).startswith('у потолка: «уровень умений приспешников от +3» здесь не будет — '
                                                            'ур. предмета 33, нужно 55'), card['now']['line'])
        self.assertEqual([(c['kind'], str(c.get('price', ''))) for c in (card['places']['P'][0], card['places']['S'][0])],
                         [('have', '1 из 9'), ('low', '1 из 24')])
        self.assertEqual(str(how['hunt']['answer']), 'Выбивать +3 сейчас — +4 только с T14')
        self.wear(sceptre_text(self.cat, 'Волшебный', ('Суффикс "Надзирателя" (Уровень: 2)',
                                                       mod_line(self.cat, 'GlobalMinionSpellSkillGemLevelWeapon3')), ilvl=56))
        how = self.rows()['weapon']['howto']
        card = how['recipe']
        self.assertEqual((card['places']['S'][0]['kind'], PAIR.sub('', str(card['now']['tool'])), str(card['now']['odds'])),
                         ('have', 'Большая сущность повеления', 'наверняка'))
        self.assertIsNone(card['now']['miss'])
        self.assertEqual(str(how['hunt']['answer']), '+4 — только с T14')

    def test_worn_on_another_base(self):
        """Надет скипетр не той базы, что называет план (Скипетр предвестия): на местах — что на нём стоит, шагов нет,
        вместо них — «другая база». Карточка копии такого предмета говорит то же."""
        self.wear(sceptre_text(self.cat, 'Волшебный', ('Суффикс "Надзирателя" (Уровень: 2)',
                                                       mod_line(self.cat, 'GlobalMinionSpellSkillGemLevelWeapon3')),
                               ilvl=56, base='Omen Sceptre'))
        card = self.rows()['weapon']['howto']['recipe']
        self.assertEqual((card['kind'], PAIR.sub('', str(card['now']['line']))),
                         ('other', 'другая база — Скипетр предвестия: путь начинается с новой белой'))
        self.assertFalse([c for side in card['places'].values() for c in side if c['kind'] in ('now', 'step')])
        self.assertTrue(self.app.take_copy(sceptre_text(self.cat, 'Волшебный', ('Суффикс "Надзирателя" (Уровень: 2)',
                                                                                  mod_line(self.cat, 'GlobalMinionSpellSkillGemLevelWeapon3')),
                                                        ilvl=60, base='Omen Sceptre'), ts=200.0))
        craft = self.app.view()['copy']['rows'][0]['craft']
        self.assertEqual((craft['kind'], PAIR.sub('', str(craft['recipe']['now']['line']))),
                         ('other', 'другая база — Скипетр предвестия: путь начинается с новой белой'))

    def test_a_twin_base_is_the_named_base(self):
        """План называет шлему «Тиару небес»; «Тиара волшебника» по данным игры та же (ур. 65, энергощит 90, интеллект
        91). Где искать базу называет обе; скопированная «Тиара волшебника» — база плана: «Надеть» закрывает ступень
        «Тиара небес», в карточке надетой — шаг дальше, а не «другая база»."""
        plan = json.loads(self.plan.read_text(encoding='utf-8'))
        plan['goals'] = PATH_GOALS + [{'id': 'h-tiara', 'slot': 'helmet', 'title': 'Тиара небес (Skycrown Tiara)', 'need': 'clearfell'}]
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        with self.app.cond:
            self.app.load_plan()
        found = self.rows()['helmet']['howto']['hunt']
        self.assertIn('Тиара небес или Тиара волшебника', PAIR.sub('', str(found['marks'][0]['base'])))
        text = sceptre_text(self.cat, 'Волшебный', ('Суффикс "Надзирателя" (Уровень: 1)', mod_line(self.cat, 'GlobalMinionSpellSkillGemLevel2')),
                            ilvl=66, base='Magus Tiara', cls='Helmet')
        self.assertTrue(self.app.take_copy(text, ts=300.0))
        row = self.app.view()['copy']['rows'][0]
        self.assertEqual((row['slot'], row['base']['to'], row['craft']['kind']), ('helmet', 'h-tiara', 'next'))
        self.assertTrue(self.app.wear({'row': row['row']}))
        helmet = self.rows()['helmet']
        self.assertEqual(helmet['base']['have']['id'], 'h-tiara')
        card = helmet['howto']['recipe']
        self.assertEqual((card['kind'], PAIR.sub('', str(card['now']['tool']))), ('next', 'Большая сущность улучшения'))

    def test_helmet_and_a_key_without_a_goal(self):
        """Шлем: базу план не называет — белая база любая на энергощит в окне «+2»; шаги — ловля «+2» и сущность на
        энергощит (у шлема цель «от 300»); очернения на сопротивление огню нет — у него нет цели. Сапоги: у ключа
        (скорость передвижения) цели нет — рецепт ведёт его к лучшей ступени того, что падает сейчас."""
        rows = self.rows()
        helmet = rows['helmet']['howto']
        self.assertEqual(str(helmet['recipe']['now']['aim']), 'уровень умений приспешников от +2')
        self.assertEqual([PAIR.sub('', str(s['tool'])) for s in helmet['recipe']['next']], ['Большая сущность улучшения'])
        self.assertEqual(PAIR.sub('', str(helmet['hunt']['marks'][0]['base'])), 'белая база: любая — Шлемы · Энергощит, ур. 44–47')
        boots = rows['boots']['howto']['recipe']
        self.assertTrue(str(boots['now']['aim']).startswith('скорость передвижения от '), boots['now']['aim'])

    def test_copy_card_aims_at_what_the_plan_requires_now(self):
        """Карточка копии целится туда же, куда «Как сделать»: в ступень, которую план требует сейчас. Ничего не надето,
        срок «+1» прошёл, «+3» — к этому шагу: белый скипетр ловят на «+3»."""
        self.assertTrue(self.app.take_copy(sceptre_text(self.cat, 'Обычный', ilvl=72), ts=100.0))
        craft = self.app.view()['copy']['rows'][0]['craft']
        self.assertEqual(str(craft['recipe']['now']['aim']), 'уровень умений приспешников от +3')

    def test_their_sceptre(self):
        """Скипетр из копии пользователя: синий Гремящий скипетр 65-го уровня с префиксом духа 45–50%; надет — 33-го
        уровня с «+2». Дух на месте и стоит дёшево (1 из 21 белой базы); «+3» — шаг сейчас: Большая сфера усиления,
        1 из 58; попал — лучше надетого; промах — на верстак: чинить Сферой отмены незачем, дух встаёт втрое чаще «+3»."""
        self.wear(sceptre_text(self.cat, 'Редкий', ('Очернённое Префикс "Маркиза" (Уровень: 7)', mod_line(self.cat, 'LocalIncreasedSpiritPercent2')),
                               ('Суффикс "Надзирателя" (Уровень: 3)', mod_line(self.cat, 'GlobalMinionSpellSkillGemLevelWeapon2')),
                               ilvl=33))
        self.assertTrue(self.app.take_copy(THEIR_SCEPTRE, ts=500.0))
        craft = self.app.view()['copy']['rows'][0]['craft']
        card = craft['recipe']
        self.assertEqual([(c['kind'], str(c.get('text', '')), str(c.get('price', ''))) for c in card['places']['P'][:2]],
                         [('have', '45–50% увеличение духа', '1 из 21'), ('step', 'урон союзников в присутствии 75–89%', 'наверняка')])
        self.assertEqual((card['places']['S'][0]['kind'], str(card['places']['S'][0]['price'])), ('now', '1 из 58'))
        now = card['now']
        self.assertEqual((PAIR.sub('', str(now['tool'])), str(now['hit']), str(now['miss'])),
                         ('Большая сфера усиления', 'попал — лучше надетого: +3 против +2', 'промах — на верстак 3 → 1'))
        self.assertEqual(str(craft['hunt']['answer']), 'Выбивать +3 сейчас — +4 только с T14')

    def test_the_block_in_english(self):
        names = i18n.Names('en', self.cat)
        for slot, row in self.rows('en').items():
            shown = i18n.render({'h': row.get('howto')}, 'en', names, plain=True)['h']
            if shown:
                self.assertFalse(i18n.CYR.search(json.dumps(shown, ensure_ascii=False)), '%s: %s' % (slot, shown))
        how = i18n.render(self.rows('en')['weapon']['howto'], 'en', names, plain=True)
        self.assertEqual((how['hunt']['answer'], how['recipe']['places']['S'][0]['price']),
                         ('Farm +3 now — +4 only from T14', '1 in 46'))

    def test_zone_names_in_the_page_language(self):
        """Зоны в «Где искать базу» — на языке страницы: по-русски — как шаг маршрута назван в плане (название из
        игры), по-английски — название зоны из данных игры, а не русское из плана."""
        steps = [{'id': 'a', 'zone': 'P1_3', 'name': 'Чернолесье'}, {'id': 'b', 'zone': 'P1_5', 'name': 'Волчья крепость'}]
        self.assertEqual(str(craftplan._where(self.cat, 55, 57, {}, steps, 'ru')), 'Чернолесье, Волчья крепость')
        self.assertEqual(str(craftplan._where(self.cat, 55, 57, {}, steps, 'en')), 'The Blackwood, Wolvenhold')

    def test_deadline_on_luck(self):
        """Срок на удачу: «+3» к «Клирфеллу» — в среднем ≈46 белых скипетров ур. 55–57 и столько же Больших сфер
        превращения; шлем «+2» — ≈35. Не замечание: «+1» (≈6 баз в окне 2–4), дух от 120 (сумма на предмете), урон
        союзников от 75% (его даёт сущность), цель без срока."""
        import buildcheck
        found = buildcheck.luck_findings(self.app.catalog, self.app.plan, 'ru')
        self.assertEqual([f['goal'] for f in found], ['w-minion-3', 'h-minion-2'])
        f = found[0]
        self.assertEqual((f['kind'], f['level'], f['tab'], f['what'], str(f['where'])),
                         ('luck', 'bad', 'items', 'уровень умений приспешников от +3', 'не позже «Клирфелл»'))
        self.assertEqual(PAIR.sub('', str(f['text'])), 'Срок на удачу: в среднем ≈46 баз и ≈46 × Большая сфера превращения')
        self.assertEqual(PAIR.sub('', str(f['detail'])),
                         '2,2% на базу · база: Гремящий скипетр, ур. предмета 55–57 · Большая сфера превращения, легло на '
                         'другую сторону — Большая сфера усиления · на удачу — больше 10 баз в среднем')
        self.assertIn('≈35 баз', str(found[1]['text']))
        # то же — в проверке страницы «Билд» и в её ответе на правку
        page = [x for x in self.app.build_view('ru')['findings'] if x['kind'] == 'luck']
        self.assertEqual([x['goal'] for x in page], ['w-minion-3', 'h-minion-2'])
        # срок программа не меняет
        self.assertEqual({g['id']: g.get('need') for g in self.app.plan['goals']}['w-minion-3'], 'clearfell')


if __name__ == '__main__':
    unittest.main()
