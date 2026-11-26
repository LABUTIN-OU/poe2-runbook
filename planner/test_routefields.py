# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Поля маршрута, которые раньше правили только в файле: что цель шага даёт герою, чем она дана, название
маршрута. Запуск: python -m unittest planner.test_routefields"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import routeplan  # noqa: E402
import test_routeplan as tr  # noqa: E402

STATS = {'res_cold', 'spirit', 'life'}


def check(raw):
    problems = []
    return routeplan.check(raw, json.loads(tr.ROUTE), (), problems, stats=STATS), problems


def route():
    r = json.loads(tr.ROUTE)
    return {'steps': r['steps'], 'goals': r['goals']}


class FieldsTest(unittest.TestCase):
    def test_what_a_goal_gives_and_who_grants_it(self):
        raw = route()
        beira = raw['goals'][2]
        self.assertEqual(beira['id'], 'boss-beira')
        beira['gives'] = {'res_cold': 10, 'spirit': 30}
        raw['goals'][0]['grantedBy'] = 'boss-miller'
        raw['goals'][1]['gives'] = {}                                  # пусто — поля нет
        out, problems = check(raw)
        self.assertEqual((problems, out['goals'][2]['gives'], out['goals'][0]['grantedBy'], 'gives' in out['goals'][1]),
                         ([], {'res_cold': 10, 'spirit': 30}, 'boss-miller', False))
        for bad in ({'мана': 5}, {'spirit': 0}, {'spirit': '30'}, {'spirit': True}, ['spirit']):
            raw = route()
            raw['goals'][2]['gives'] = bad
            self.assertEqual(check(raw)[1], ['цель шага «Бейра (Beira): +10% к холоду»: «даёт герою» — статы из данных игры, у каждого число'])
        raw = route()
        raw['goals'][0]['grantedBy'] = ['boss-miller']
        self.assertEqual(check(raw)[1], ['цель шага «7 уровень героя»: «чем дано» — id цели'])

    def test_a_route_has_no_name_of_its_own(self):
        """Маршрут — часть плана, а план называется в билде: своего названия у маршрута нет. Название,
        присланное страницей прежнего вида, не берётся; строка названия в файле, записанном раньше, остаётся."""
        out, problems = check(dict(route(), title='Кампания 0.5'))
        self.assertEqual((problems, sorted(out)), ([], ['goals', 'steps']))
        self.assertEqual(routeplan.render(tr.ROUTE, out), tr.ROUTE)
        old = tr.ROUTE.replace('  "id": "r",\n', '  "id": "r",\n  "title": "Учебный маршрут",\n')
        self.assertEqual(routeplan.render(old, out), old)
        self.assertEqual(sorted(routeplan.describe(None, json.loads(old))['route']), ['goals', 'steps'])


if __name__ == '__main__':
    unittest.main()
