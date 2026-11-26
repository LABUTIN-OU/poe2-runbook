# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка счёта «чем герой был занят» (core.step_spans): разбор времени героя (planner/review.py, режим «Разбор»,
/api/review) и время шага на странице «Игра» (core.derive) — они считают одно и то же.

Запуск: python -X utf8 -m unittest planner.test_review
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import review  # noqa: E402
import server  # noqa: E402

T0 = 1800000000      # старт героя; дальше время — секунды от него


def zone(t, code, name=None, level=1, seed='1'):
    return {'type': 'zone', 'ts': T0 + t, 'code': code, 'level': level, 'name': name or code, 'seed': seed}


def leave(t):
    return {'type': 'leave', 'ts': T0 + t}


def plan_of(steps):
    plan, problems = core.norm_plan({'slots': [], 'steps': steps, 'goals': []})
    assert not problems, problems
    return plan


def run_of(events, moves=(), hold=()):
    run = core.Run('hero', T0)
    run.events = list(events)
    run.moves = [{'ts': T0 + t, 'step': step} for t, step in moves]
    run.hold = [{'ts': T0 + t, 'on': on} for t, on in hold]
    return run


def split(plan, run, now=None):
    """Разбор так, как его считает программа: страница («Игра») говорит, когда какой шаг был текущим."""
    end = review.end_of(run)[0]
    v = core.derive(plan, run, T0 + now if now is not None else end)
    return review.split(plan, run, v['posLog'], T0 + now if now is not None else None)


def rows(res):
    return {r['id']: r for r in res['steps']}


def kinds(row):
    return [p['kind'] for p in row['parts']]


AB = [{'id': 'a', 'zone': 'G1_1', 'name': 'А', 'target': '5:00'}, {'id': 'b', 'zone': 'G1_2', 'name': 'Б', 'target': '5:00'}]


class SplitTest(unittest.TestCase):
    def test_time_is_split_by_place_and_sums_to_clean_time(self):
        """Время шага делится по месту: его зоны, город, зоны вне маршрута. Время вне игры не идёт; сумма по шагам —
        чистое время героя."""
        run = run_of([zone(0, 'G1_1'), zone(300, 'G1_town'), zone(400, 'G1_1'), zone(460, 'Abyss_1'), zone(580, 'G1_2'),
                      leave(780), zone(1000, 'G1_2'), leave(1100)])
        res = split(plan_of(AB), run)
        r = rows(res)
        self.assertEqual((r['a']['zone'], r['a']['town'], r['a']['off'], r['a']['all']), (360, 100, 120, 580))
        self.assertEqual((r['b']['zone'], r['b']['town'], r['b']['off']), (300, 0, 0))
        self.assertEqual(res['total'], {'zone': 660, 'town': 100, 'off': 120, 'all': 880})
        self.assertEqual(res['clean'], 880)
        self.assertEqual(res['clean'], core.clean_time(run.events, run.started, T0 + 1100))
        self.assertEqual(kinds(r['a']), ['zone', 'town', 'zone', 'off'])
        self.assertEqual((r['a']['target'], r['a']['at'], r['b']['at'], r['b']['leaves']), (300, 0, 580, 2))
        # шаг, на котором время героя кончилось, не пройден (cut — сколько он длился); остальные пройдены
        self.assertEqual((r['a']['cut'], r['b']['cut'], res['dead']), (None, 300, False))

    def test_button_does_not_move_the_time(self):
        """Кнопка «Шаг пройден», нажатая до прихода на новую карту, время не переносит: остаток карты и город после
        неё остаются у шага этой карты. В ленте шага нажатие — метка."""
        run = run_of([zone(0, 'G1_1'), zone(300, 'G1_town'), zone(400, 'G1_2'), leave(700)], moves=[(200, 'b')])
        plan = plan_of(AB)
        res = split(plan, run)
        r = rows(res)
        self.assertEqual((r['a']['zone'], r['a']['town']), (300, 100))
        self.assertEqual((r['b']['zone'], r['b']['town'], r['b']['at']), (300, 0, 400))
        self.assertEqual([(p['kind'], p['t'], p['name']) for p in r['a']['parts'] if p['kind'] == 'button'], [('button', 200, 'Б')])
        # таймер страницы «Игра» при этом считает шаг «Б» с нажатия: с 200-й секунды
        v = core.derive(plan, run, T0 + 700)
        self.assertEqual([p for _, p in v['posLog']], [0, 1])
        self.assertEqual(v['posLog'][1][0], T0 + 200)

    def test_peek_and_the_town_after_it_stay_with_the_step(self):
        """Заглянул на карту следующего шага (открыть точку), ушёл в город и вернулся туда же: и заход, и город —
        у шага, которым герой был занят."""
        run = run_of([zone(0, 'G1_1'), zone(400, 'G1_2'), zone(418, 'G1_town'), zone(656, 'G1_2'), leave(1256)])
        r = rows(split(plan_of(AB), run))
        self.assertEqual((r['a']['zone'], r['a']['town']), (418, 238))
        self.assertEqual(kinds(r['a']), ['zone', 'peek', 'town'])
        self.assertEqual((r['b']['zone'], r['b']['town'], r['b']['at']), (600, 0, 656))

    def test_peek_and_back_to_the_step_zone(self):
        """Заглянул на следующую карту и вернулся в зону своего шага — шаг не менялся."""
        run = run_of([zone(0, 'G1_1'), zone(300, 'G1_2'), zone(318, 'G1_1'), zone(418, 'G1_2'), leave(918)])
        r = rows(split(plan_of(AB), run))
        self.assertEqual((r['a']['zone'], kinds(r['a'])), (418, ['zone', 'peek', 'zone']))
        self.assertEqual((r['b']['zone'], r['b']['at']), (500, 418))

    def test_short_step_passed_through_is_a_step(self):
        """Короткий заход на следующую карту, из которой герой пошёл дальше по маршруту, — это и был шаг."""
        steps = AB + [{'id': 'c', 'zone': 'G1_3', 'name': 'В'}]
        run = run_of([zone(0, 'G1_1'), zone(300, 'G1_2'), zone(320, 'G1_3'), leave(620)])
        r = rows(split(plan_of(steps), run))
        self.assertEqual((r['a']['zone'], r['b']['zone'], r['c']['zone']), (300, 20, 300))
        self.assertEqual(kinds(r['b']), ['zone'])

    def test_waypoint_of_the_step_is_a_peek(self):
        """Зона, записанная у шага точкой перехода, — короткий заход: шаг не меняется, хотя у маршрута есть шаг с
        этой зоной."""
        steps = [dict(AB[0], touch=[{'zone': 'G1_3'}]), AB[1], {'id': 'c', 'zone': 'G1_3', 'name': 'В'}]
        run = run_of([zone(0, 'G1_1'), zone(300, 'G1_3'), zone(310, 'G1_1'), zone(410, 'G1_2'), leave(610)])
        r = rows(split(plan_of(steps), run))
        self.assertEqual((r['a']['zone'], kinds(r['a'])), (410, ['zone', 'peek', 'zone']))
        self.assertNotIn('c', r)

    def test_town_step_and_step_without_a_zone(self):
        """Шаг-город и шаг по событию («После восхождения») — работа в городе: пока такой шаг текущий на странице,
        город идёт ему как его зона; город после обычной карты — её шагу."""
        steps = [AB[0], {'id': 'camp', 'zone': 'G1_town', 'name': 'Лагерь'}, AB[1],
                 {'id': 'after', 'event': 'ascend', 'name': 'После восхождения'}, {'id': 'c', 'zone': 'G1_3', 'name': 'В'}]
        run = run_of([zone(0, 'G1_1'), zone(100, 'G1_town'), zone(150, 'G1_2'), zone(350, 'G1_town'),
                      {'type': 'ascend', 'ts': T0 + 400, 'n': 1}, zone(430, 'G1_3'), leave(530)])
        res = split(plan_of(steps), run)
        r = rows(res)
        self.assertEqual((r['a']['zone'], r['camp']['zone'], r['camp']['town']), (100, 50, 0))
        self.assertEqual((r['b']['zone'], r['b']['town']), (200, 50))
        self.assertEqual((r['after']['zone'], r['after']['town'], r['c']['zone']), (30, 0, 100))
        self.assertEqual(res['total']['all'], res['clean'])

    def test_maps_stage(self):
        """Этап карт — шаг по уровню зоны: любая карта — его зона, убежище — город."""
        steps = [AB[0], {'id': 'm', 'level': 65, 'name': 'Карты 1–5'}]
        run = run_of([zone(0, 'G1_1'), zone(100, 'MapA', 'Карта', 66), zone(400, 'HideoutFelled', 'Убежище'),
                      zone(600, 'MapB', 'Другая карта', 67), leave(700)])
        res = split(plan_of(steps), run)
        r = rows(res)
        self.assertEqual((r['m']['zone'], r['m']['town'], r['m']['maps'], r['a']['maps']), (400, 200, True, False))
        self.assertTrue(review.page(res)['maps'])

    def test_death_ends_the_time(self):
        """Время героя кончается его гибелью: что лог писал потом — уже не эта игра. Чужая гибель не в счёт."""
        events = [zone(0, 'G1_1'), {'type': 'level', 'ts': T0 + 50, 'name': 'Герой', 'cls': 'Чародейка', 'level': 2},
                  zone(100, 'G1_2'), {'type': 'death', 'ts': T0 + 150, 'name': 'Прохожий'},
                  {'type': 'death', 'ts': T0 + 200, 'name': 'Герой'}, zone(210, 'G1_town'), zone(300, 'G1_2'), leave(400)]
        run = run_of(events, moves=[(350, 'a')])
        self.assertEqual(review.end_of(run), (T0 + 200, True))
        res = split(plan_of(AB), run)
        r = rows(res)
        self.assertEqual((res['dead'], res['clean'], res['end']), (True, 200, T0 + 200))
        self.assertEqual((r['a']['zone'], r['a']['cut'], r['b']['zone'], r['b']['cut']), (100, None, 100, 100))
        self.assertEqual(kinds(r['b']), ['zone', 'death'])

    def test_living_hero_is_counted_to_now(self):
        """Герой, которым играют: время — до «сейчас»; его шаг не пройден, но гибели нет."""
        run = run_of([zone(0, 'G1_1')])
        res = split(plan_of(AB), run, now=500)
        r = rows(res)
        self.assertEqual((res['clean'], res['dead'], r['a']['zone'], r['a']['cut']), (500, False, 500, 500))
        self.assertEqual(kinds(r['a']), ['zone'])

    def test_pause_and_time_out_of_game_are_not_counted(self):
        """Пауза игрока и время вне игры не идут ни одному шагу — как у таймера страницы."""
        run = run_of([zone(0, 'G1_1'), zone(100, 'G1_town'), zone(300, 'G1_1'), leave(400), zone(1000, 'G1_1'), leave(1100)],
                     hold=[(150, True), (250, False)])
        res = split(plan_of(AB), run)
        r = rows(res)
        self.assertEqual((r['a']['zone'], r['a']['town'], res['clean']), (300, 100, 400))
        self.assertEqual(res['clean'], core.clean_time(run.events, run.started, T0 + 1100, run.hold))

    def test_table_groups_follow_the_route(self):
        """Группа таблицы — акт по порядку маршрута: шаг-возврат в зону прошлого акта остаётся в группе, где стоит."""
        steps = [{'id': 'a', 'zone': 'G1_1'}, {'id': 'b', 'zone': 'G2_1'}, {'id': 'c', 'zone': 'G1_2'}, {'id': 'd', 'zone': 'G2_2'}]
        run = run_of([zone(0, 'G1_1'), zone(100, 'G2_1'), zone(200, 'G1_2'), zone(300, 'G2_2'), leave(400)])
        res = split(plan_of(steps), run)
        self.assertEqual([str(r['act']) for r in res['steps']], ['Акт 1', 'Акт 2', 'Акт 2', 'Акт 2'])

    def test_page_form(self):
        """Странице разбор уходит короткими ключами; вид записи ленты — номером (слова о нём говорит страница)."""
        run = run_of([zone(0, 'G1_1'), zone(300, 'G1_town'), zone(400, 'G1_2'), leave(700)], moves=[(200, 'b')])
        data = review.page(split(plan_of(AB), run))
        json.dumps(data)
        self.assertEqual((data['clean'], data['dead'], data['maps'], data['total']), (700, False, False, {'z': 600, 't': 100, 'o': 0}))
        a = data['steps'][0]
        self.assertEqual((a['id'], a['n'], a['g'], a['z'], a['t'], a['o'], a['c'], a['at']), ('a', 'А', 300, 300, 100, 0, None, 0))
        self.assertEqual([[t, review.KINDS[k], n, d] for t, k, n, d in a['p']],
                         [[0, 'zone', 'G1_1', 300], [200, 'button', 'Б', 0], [300, 'town', 'G1_town', 100]])
        self.assertEqual(data['steps'][1]['c'], 300)

    def test_empty(self):
        """Героя без зон или план без шагов разбор не роняют."""
        self.assertEqual(split(plan_of(AB), run_of([]))['steps'], [])
        self.assertEqual(review.split(plan_of([]), run_of([zone(0, 'G1_1'), leave(10)]), [])['steps'], [])


class AgainTest(unittest.TestCase):
    """Карта, начатая заново: герой вышел из игры на карте, а вернулся уже в новую её копию (core.map_copies) — так
    уходят с карты через выбор героя, когда оставаться опасно. Это попытка, прерванная выходом из игры."""

    def test_leaving_the_game_on_a_map_and_coming_back_to_a_new_copy(self):
        """Вышел из игры на карте, вошёл в город, вернулся — карта создана заново: попытка прервана. Время брошенной
        копии остаётся в зонах шага и названо отдельно; в ленте перед новой копией стоит метка."""
        run = run_of([zone(0, 'G1_1'), zone(100, 'G1_2', seed='A'), leave(400), zone(420, 'G1_town'),
                      zone(440, 'G1_2', seed='B'), leave(900)])
        res = split(plan_of(AB), run)
        a, b = rows(res)['a'], rows(res)['b']
        self.assertEqual((b['again'], b['lostZone'], b['lostOff'], b['zone'], b['town']), (1, 300, 0, 760, 20))
        self.assertEqual(kinds(b), ['zone', 'leave', 'town', 'again', 'zone', 'leave'])
        self.assertEqual([p['drop'] for p in b['parts'] if p['kind'] == 'zone'], [True, False])
        self.assertEqual((a['again'], a['lostZone']), (0, 0))
        page = review.page(res)['steps'][1]
        self.assertEqual((page['q'], page['qz'], page['qo']), (1, 300, 0))
        self.assertEqual([(review.KINDS[p[1]], p[4:]) for p in page['p'] if p[4:] or review.KINDS[p[1]] == 'again'],
                         [('zone', [1]), ('again', [])])

    def test_same_copy_or_no_exit_is_not_a_new_attempt(self):
        """Вышел и продолжил в той же копии — попытка та же. Новая копия без выхода из игры (вернулся на карту позже,
        прежняя копия истекла) — тоже не попытка. Выход из игры в городе карту не бросает."""
        same = run_of([zone(0, 'G1_1'), zone(100, 'G1_2', seed='A'), leave(400), zone(1000, 'G1_2', seed='A'), leave(1200)])
        self.assertEqual(rows(split(plan_of(AB), same))['b']['again'], 0)
        later = run_of([zone(0, 'G1_1'), zone(100, 'G1_2', seed='A'), zone(400, 'G1_town'), zone(2400, 'G1_2', seed='B'),
                        leave(2600)])
        r = rows(split(plan_of(AB), later))['b']
        self.assertEqual((r['again'], r['lostZone'], kinds(r)), (0, 0, ['zone', 'town', 'zone', 'leave']))
        town = run_of([zone(0, 'G1_1'), zone(100, 'G1_2', seed='A'), zone(400, 'G1_town'), leave(420), zone(500, 'G1_town'),
                       zone(520, 'G1_2', seed='B'), leave(700)])
        self.assertEqual(rows(split(plan_of(AB), town))['b']['again'], 0)

    def test_every_interrupted_attempt_counts(self):
        """Три захода на карту — две попытки прерваны; время в них складывается."""
        run = run_of([zone(0, 'G1_1'), zone(100, 'G1_2', seed='A'), leave(200), zone(210, 'G1_town'),
                      zone(220, 'G1_2', seed='B'), leave(320), zone(330, 'G1_town'), zone(340, 'G1_2', seed='C'), leave(640)])
        b = rows(split(plan_of(AB), run))['b']
        self.assertEqual((b['again'], b['lostZone'], kinds(b).count('again')), (2, 200, 2))

    def test_one_interrupted_attempt_counts_once(self):
        """Брошенная копия досталась двум шагам (в неё заглянули ещё с прошлого шага) — попытка одна: у шага, которым
        герой был занят, когда вышел из игры. Время в копии остаётся у каждого шага своё."""
        run = run_of([zone(0, 'G1_1'), zone(100, 'G1_2', seed='A'), zone(120, 'G1_1'), zone(200, 'G1_2', seed='A'), leave(500),
                      zone(520, 'G1_town'), zone(540, 'G1_2', seed='B'), leave(800)])
        r = rows(split(plan_of(AB), run))
        self.assertEqual([(r[k]['again'], r[k]['lostZone']) for k in 'ab'], [(0, 20), (1, 300)])
        view = core.derive(plan_of(AB), run, T0 + 800)
        self.assertEqual([(c['again'], c['lost']) for c in view['cards']], [(0, 20), (1, 300)])

    def test_maps_of_the_atlas_are_not_restarts(self):
        """На картах атласа новая копия — это новая карта, а не та же карта заново."""
        visits = core.zone_visits([zone(0, 'MapSteppe', seed='A'), leave(100), zone(200, 'MapSteppe', seed='B')], T0 + 300)[0]
        self.assertEqual(core.map_copies(visits), (set(), {}))
        visits = core.zone_visits([zone(0, 'G1_2', seed='A'), leave(100), zone(200, 'G1_2', seed='B')], T0 + 300)[0]
        self.assertEqual(core.map_copies(visits), ({('G1_2', 'B')}, {('G1_2', 'A'): 1}))

    def test_restarts_by_zone(self):
        """Счёт по зонам без плана: сколько раз зону начинали заново и сколько времени осталось в брошенных копиях."""
        run = run_of([zone(0, 'G1_1'), zone(100, 'G1_2', 'Клирфелл', seed='A'), leave(400), zone(420, 'G1_town'),
                      zone(440, 'G1_2', 'Клирфелл', seed='B'), leave(900)])
        self.assertEqual(core.restarts(run.events, run.hold, run.started, T0 + 900),
                         {'G1_1': {'name': 'G1_1', 'again': 0, 'lost': 0}, 'G1_2': {'name': 'Клирфелл', 'again': 1, 'lost': 300}})


class PageTimeTest(unittest.TestCase):
    """Время шага на странице «Игра» — тот же счёт, что в «Разборе»: core.derive раскладывает время через
    core.step_spans, а страница знает, какому шагу время идёт сейчас (busy), — он бывает не шагом страницы."""

    def view(self, steps, run, now):
        return core.derive(plan_of(steps), run, T0 + now)

    @staticmethod
    def took(view):
        return {c['id']: c['took'] for c in view['cards'] if c['took'] is not None}

    def test_page_times_equal_the_review(self):
        """Сколько шаг занял, «Игра» и «Разбор» говорят одинаково — и с городом, и с коротким заходом, и с кнопкой."""
        runs = [run_of([zone(0, 'G1_1'), zone(300, 'G1_town'), zone(400, 'G1_1'), zone(460, 'Abyss_1'), zone(580, 'G1_2'),
                        leave(780), zone(1000, 'G1_2'), leave(1100)]),
                run_of([zone(0, 'G1_1'), zone(400, 'G1_2'), zone(418, 'G1_town'), zone(656, 'G1_2'), leave(1256)]),
                run_of([zone(0, 'G1_1'), zone(300, 'G1_town'), zone(400, 'G1_2'), leave(700)], moves=[(200, 'b')])]
        for run in runs:
            end = max(e['ts'] for e in run.events) - T0
            view = self.view(AB, run, end)
            self.assertEqual(self.took(view), {r['id']: r['all'] for r in split(plan_of(AB), run)['steps']})
            self.assertEqual(sum(self.took(view).values()), view['run']['active'])

    def test_button_before_the_next_map_leaves_the_time_with_the_old_step(self):
        """«Шаг пройден» нажали, а на новую карту ещё не пришли: страница показывает новый шаг, но его время стоит —
        оно идёт прежнему шагу, пока герой не пришёл; плитка шага называет, какому."""
        events = [zone(0, 'G1_1')]
        view = self.view(AB, run_of(events, moves=[(200, 'b')]), 250)
        self.assertEqual(view['step']['id'], 'b')
        self.assertEqual(view['time']['step'], {'spent': 0, 'away': 0, 'target': 300, 'live': False, 'busy': 'А'})
        self.assertEqual(self.took(view), {'a': 250})
        self.assertEqual([(c['id'], c['busy']) for c in view['cards']], [('a', True), ('b', False)])
        self.assertEqual((view['time']['act']['spent'], view['time']['act']['live']), (250, True))
        # ушёл в город: время всё ещё прежнего шага
        events.append(zone(300, 'G1_town'))
        view = self.view(AB, run_of(events, moves=[(200, 'b')]), 350)
        self.assertEqual((self.took(view), view['time']['step']['live'], view['time']['step']['busy']), ({'a': 350}, False, 'А'))
        # пришёл на карту шага: его время пошло — с прихода, а не с нажатия
        events.append(zone(400, 'G1_2'))
        view = self.view(AB, run_of(events, moves=[(200, 'b')]), 410)
        self.assertEqual(view['time']['step'], {'spent': 10, 'away': 0, 'target': 300, 'live': True, 'busy': None})
        self.assertEqual(self.took(view), {'a': 400, 'b': 10})
        self.assertEqual([c['id'] for c in view['cards'] if c['busy']], ['b'])
        self.assertEqual((next(c['at'] for c in view['cards'] if c['id'] == 'b'), view['run']['active']), (400, 410))

    def test_arrival_after_the_button_counts_at_once(self):
        """Игрок нажал «Шаг пройден» и пришёл на карту шага — время идёт ему сразу, даже если эта карта записана у
        прежнего шага точкой перехода (без кнопки там ждут порог). Ушёл раньше порога — это был короткий заход."""
        steps = [dict(AB[0], touch=[{'zone': 'G1_2'}]), AB[1]]
        events = [zone(0, 'G1_1'), zone(120, 'G1_2')]
        # без кнопки: страница ждёт порог, время — прежнему шагу; программа пересчитает его сама, когда порог пройдёт
        view = self.view(steps, run_of(events), 130)
        self.assertEqual((view['step']['id'], view['time']['step']['live'], self.took(view)), ('a', True, {'a': 130}))
        self.assertEqual(view['recheckAt'], T0 + 160)
        # с кнопкой: страница на шаге «Б», герой на его карте — время его
        pressed = [(100, 'b')]
        view = self.view(steps, run_of(events, moves=pressed), 130)
        self.assertEqual((view['step']['id'], view['time']['step']['live'], self.took(view)), ('b', True, {'a': 120, 'b': 10}))
        # ушёл в город через 15 секунд: заход оказался коротким — он и город остались у прежнего шага
        view = self.view(steps, run_of(events + [zone(135, 'G1_town')], moves=pressed), 200)
        self.assertEqual((self.took(view), view['time']['step']['busy']), ({'a': 200}, 'А'))
        # остался дольше порога — шаг «Б» считается со входа на карту
        view = self.view(steps, run_of(events, moves=pressed), 200)
        self.assertEqual((self.took(view), view['recheckAt']), ({'a': 120, 'b': 80}, None))

    def test_return_to_an_earlier_map(self):
        """Вернулся на карту прежнего шага: раньше порога это короткий заход текущего шага (программа пересчитает,
        когда порог пройдёт), дольше — время идёт прежнему шагу, а время шага страницы стоит."""
        steps = AB + [{'id': 'c', 'zone': 'G1_3', 'name': 'В', 'target': '5:00'}]
        run = run_of([zone(0, 'G1_1'), zone(100, 'G1_2'), zone(300, 'G1_3'), zone(500, 'G1_1')])
        view = self.view(steps, run, 510)
        self.assertEqual((view['step']['id'], view['time']['step']['live'], view['recheckAt']), ('c', True, T0 + 540))
        self.assertEqual(self.took(view), {'a': 100, 'b': 200, 'c': 210})
        view = self.view(steps, run, 545)
        self.assertEqual(view['step']['id'], 'c')
        self.assertEqual(view['time']['step'], {'spent': 200, 'away': 0, 'target': 300, 'live': False, 'busy': 'А'})
        self.assertEqual((self.took(view), view['recheckAt']), ({'a': 145, 'b': 200, 'c': 200}, None))

    def test_groups_know_whether_their_time_runs(self):
        """Акт и отрезок страницы досчитываются сами, только если время идёт шагу из них."""
        steps = [AB[0], {'id': 'b', 'zone': 'G2_1', 'name': 'Б', 'target': '5:00'}]
        view = self.view(steps, run_of([zone(0, 'G1_1')], moves=[(100, 'b')]), 150)
        self.assertEqual((str(view['time']['act']['name']), view['time']['act']['spent'], view['time']['act']['live']), ('Акт 2', 0, False))
        self.assertEqual([(str(a['name']), a['spent'], a['live']) for a in view['acts']], [('Акт 1', 150, True), ('Акт 2', 0, False)])

    def test_page_knows_where_the_time_went(self):
        """Плитки времени знают, сколько времени прошло не в зонах шагов (в городе и вне маршрута) и там ли оно идёт
        сейчас; карточка шага — где шло его время и сколько попыток на нём прервано."""
        events = [zone(0, 'G1_1'), zone(300, 'G1_town'), zone(400, 'G1_1'), zone(460, 'Abyss_1'), zone(580, 'G1_2', seed='A'),
                  leave(700), zone(710, 'G1_town'), zone(730, 'G1_2', seed='B')]
        view = self.view(AB, run_of(events), 800)
        t = view['time']
        self.assertEqual((t['act']['spent'], t['act']['away'], t['out']), (790, 240, False))
        self.assertEqual((t['step']['spent'], t['step']['away']), (210, 20))
        cards = {c['id']: c for c in view['cards']}
        self.assertEqual([(cards[k]['took'], cards[k]['townTime'], cards[k]['offTime'], cards[k]['again'], cards[k]['lost']) for k in 'ab'],
                         [(580, 100, 120, 0, 0), (210, 20, 0, 1, 120)])
        # герой в городе: набегающее время идёт «не в зонах шагов»
        self.assertTrue(self.view(AB, run_of(events[:2]), 350)['time']['out'])

    def test_pause_asks_for_no_recheck(self):
        """На паузе время не идёт: короткий заход до порога не дотянет — пересчёта по часам не нужно."""
        steps = AB + [{'id': 'c', 'zone': 'G1_3', 'name': 'В'}]
        run = run_of([zone(0, 'G1_1'), zone(100, 'G1_2'), zone(300, 'G1_3'), zone(500, 'G1_1')], hold=[(505, True)])
        view = self.view(steps, run, 520)
        self.assertEqual((view['recheckAt'], view['run']['held'], self.took(view)['c']), (None, True, 205))


def ln(t, text):
    return '2026/11/11 %s 1 a [INFO Client 1] %s\n' % (t, text)


def area(t, level, code, name, seed=1):
    return ('2026/11/11 %s 1 a [DEBUG Client 1] Generating level %d area "%s" with seed %s\n' % (t, level, code, seed)
            + ln(t, '[SCENE] Set Source [%s]' % name))


CHAR_SCREEN = '[SCENE] Set Source [(unknown)]'
# Два героя: первый погиб на «Клирфелле» (20:20), второй дошёл до «Клирфелла» и вышел из игры
LOG = (area('20:00:00', 1, 'G1_1', 'Берег реки') + ln('20:01:00', ': Первый (Чародейка) достигает 2 уровня')
       + area('20:05:00', 2, 'G1_2', 'Клирфелл') + area('20:10:00', 15, 'G1_town', 'Лагерь Клирфелл')
       + area('20:12:00', 2, 'G1_2', 'Клирфелл') + ln('20:20:00', ': Первый был повержен.') + ln('20:21:00', CHAR_SCREEN)
       + area('21:00:00', 1, 'G1_1', 'Берег реки') + ln('21:02:00', ': Второй (Чародейка) достигает 2 уровня')
       + area('21:03:00', 2, 'G1_2', 'Клирфелл') + ln('21:09:00', CHAR_SCREEN))
PLAN = {'title': 'Проба', 'slots': [], 'goals': [],
        'steps': [{'id': 'riverbank', 'zone': 'G1_1', 'name': 'Берег реки', 'target': '4:00'},
                  {'id': 'clearfell', 'zone': 'G1_2', 'name': 'Клирфелл', 'target': '10:00'}]}
FIRST, SECOND = '20261111-200000', '20261111-210000'


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.log, self.plan, self.runs = root / 'Client.txt', root / 'plan.json', root / 'runs'
        self.log.write_text(LOG, encoding='utf-8')
        self.plan.write_text(json.dumps(PLAN, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def start(self):
        app = server.App(self.log, self.plan, self.runs)
        with app.cond:
            app.load_plan()
            app.poll_log(initial=True)
            app.attach_run()
        return app

    def test_review_of_a_dead_hero(self):
        """Разбор героя, которым уже не играют: его время — до гибели, шаг гибели не пройден."""
        app = self.start()
        self.assertEqual(app.review_view()['pick'], SECOND)      # сам открывается разбор героя, которым играют
        v = app.review_view(hero=FIRST)
        h = v['hero']
        self.assertEqual((v['pick'], v['error'], v['base'], v['plan']['title']), (FIRST, None, None, 'Проба'))
        self.assertEqual((h['id'], h['name'], h['level'], h['fate'], h['dead'], h['clean']), (FIRST, 'Первый', 2, 'dead', True, 1200))
        self.assertEqual(h['total'], {'z': 1080, 't': 120, 'o': 0})
        self.assertEqual([(s['id'], s['z'], s['t'], s['g'], s['c']) for s in h['steps']],
                         [('riverbank', 300, 0, 240, None), ('clearfell', 780, 120, 600, 900)])
        self.assertEqual(review.KINDS[h['steps'][1]['p'][-1][1]], 'death')
        # в списке героев время погибшего — то же: до гибели, а не до последней строки лога
        self.assertEqual([(r['id'], r['spent'], r['fate']) for r in v['runs']], [(FIRST, 1200, 'dead'), (SECOND, 540, 'alive')])
        self.assertEqual(v['plans']['list'][0]['title'], 'Проба')

    def test_second_hero_by_the_same_plan(self):
        """Сравнение: второй герой разобран по тому же плану. Героя, которым играют, разбор не меняет."""
        app = self.start()
        v = app.review_view(hero=SECOND, base=FIRST)
        self.assertEqual((v['pick'], v['hero']['fate'], v['hero']['dead'], v['hero']['clean']), (SECOND, 'now', False, 540))
        self.assertEqual([(s['id'], s['z'], s['c']) for s in v['hero']['steps']], [('riverbank', 180, None), ('clearfell', 360, 360)])
        self.assertEqual((v['base']['id'], v['base']['clean'], 'ownPlan' in v['base']), (FIRST, 1200, False))
        self.assertEqual(app.run.id, SECOND)
        self.assertIsNone(app.review_view(hero=SECOND, base=SECOND)['base'])      # с самим собой не сравнивают
        self.assertEqual(app.review_view(hero='нет такого')['pick'], SECOND)

    def test_who_is_shown(self):
        """Чей разбор показать: названный герой; иначе — герой, которым играют. Героя, выбранного в прошлый раз,
        страница держит, пока с тех пор никто не играл. Героя, которым играют, нет — тот, кем играли последним."""
        rows = [{'id': 'a', 'started': 10, 'last': 50, 'died': 50, 'current': False},
                {'id': 'b', 'started': 60, 'last': 90, 'died': 90, 'current': False},
                {'id': 'c', 'started': 100, 'last': 140, 'died': None, 'current': True}]
        pick = server.App.review_pick
        self.assertEqual(pick(rows, hero='a'), 'a')
        self.assertEqual(pick(rows), 'c')                              # раньше не открывали: герой, которым играют
        self.assertEqual(pick(rows, last='a', since=150), 'a')         # с тех пор не играли: выбранный остаётся
        self.assertEqual(pick(rows, last='a', since=120), 'c')         # играли: снова текущий
        self.assertEqual(pick(rows, last='a'), 'c')                    # когда показывали — неизвестно
        self.assertEqual(pick(rows, last='нет', since=150), 'c')
        self.assertEqual(pick([dict(r, current=False) for r in rows]), 'c')      # текущего нет: кем играли последним
        self.assertEqual(pick([dict(r, current=False) for r in rows[:2]]), 'b')
        self.assertIsNone(pick([]))

    def test_buttons_and_pauses_of_another_hero_come_from_his_file(self):
        """Нажатия «Шаг пройден» и паузы героя, которым сейчас не играют, берутся из его файла; файл только читается."""
        at = core.line_ts('2026/11/11 20:10:30 x')
        self.runs.mkdir()
        path = self.runs / ('%s.json' % FIRST)
        path.write_text(json.dumps({'id': FIRST, 'moves': [{'ts': at - 400, 'step': 'clearfell'}, {'step': 'riverbank'}],
                                    'hold': [{'ts': at, 'on': True}, {'ts': at + 60, 'on': False}, {'ts': 'плохо', 'on': True}]}),
                        encoding='utf-8')
        before = path.read_bytes()
        app = self.start()
        run = app.review_run(FIRST)
        self.assertEqual(([m['step'] for m in run.moves], [h['on'] for h in run.hold]), (['clearfell'], [True, False]))
        self.assertEqual((app.runs[FIRST].moves, app.runs[FIRST].hold), ([], []))
        h = app.review_view(hero=FIRST)['hero']
        self.assertEqual((h['clean'], h['total']), (1140, {'z': 1080, 't': 60, 'o': 0}))
        self.assertIn('button', [review.KINDS[p[1]] for p in h['steps'][0]['p']])
        self.assertEqual(app.run_list()[0]['spent'], 1140)
        self.assertEqual(path.read_bytes(), before)
        self.assertIs(app.review_run(SECOND), app.run)
        self.assertIsNone(app.review_run('нет такого'))

    def test_where_maps_were_started_again(self):
        """Где карты начинали заново — по всем героям лога: зона, сколько героев в ней было, сколько из них начинали
        её заново, сколько раз и сколько времени осталось в брошенных копиях. У героя это видно на его шаге."""
        third = (area('22:00:00', 1, 'G1_1', 'Берег реки') + ln('22:01:00', ': Третий (Чародейка) достигает 2 уровня')
                 + area('22:03:00', 2, 'G1_2', 'Клирфелл', seed=7) + ln('22:08:00', CHAR_SCREEN)
                 + area('22:08:10', 15, 'G1_town', 'Лагерь Клирфелл') + area('22:08:30', 2, 'G1_2', 'Клирфелл', seed=8)
                 + ln('22:20:00', CHAR_SCREEN))
        self.log.write_text(LOG + third, encoding='utf-8')
        v = self.start().review_view()
        self.assertEqual(v['again'], {'heroes': 3, 'rows': [{'n': 'Клирфелл', 'came': 3, 'who': 1, 'q': 1, 'lost': 300}]})
        step = v['hero']['steps'][1]
        self.assertEqual((v['pick'], step['id'], step['q'], step['qz']), ('20261111-220000', 'clearfell', 1, 300))

    def test_plan_without_steps_is_not_an_error(self):
        self.plan.write_text(json.dumps(dict(PLAN, steps=[]), ensure_ascii=False), encoding='utf-8')
        v = self.start().review_view()
        self.assertEqual((v['error'], v['hero']['steps'], v['hero']['clean']), (None, [], 0))

    def test_page_and_data_over_http(self):
        """Режим «Разбор» — та же страница, что «Игра», по адресу /review; данные — /api/review на языке страницы."""
        app = self.start()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), None)
        port = httpd.server_address[1]
        httpd.RequestHandlerClass = server.make_handler(app, port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            def get(path):
                with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path), timeout=10) as r:
                    return r.read().decode('utf-8')
            page = get('/review')
            self.assertIn('function reviewPage()', page)
            self.assertEqual(page, get('/'))
            data = json.loads(get('/api/review?hero=%s&base=%s&lang=en' % (SECOND, FIRST)))
            self.assertEqual((data['pick'], data['hero']['steps'][0]['a'], data['base']['id']), (SECOND, 'Act 1', FIRST))
            self.assertEqual(json.loads(get('/api/review?last=%s&since=0' % FIRST))['pick'], SECOND)
            self.assertEqual(json.loads(get('/api/review?last=%s&since=99999999999' % FIRST))['pick'], FIRST)
            self.assertEqual(json.loads(get('/api/review?last=%s&since=abc' % FIRST))['pick'], SECOND)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == '__main__':
    unittest.main()
