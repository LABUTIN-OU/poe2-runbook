# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка прогона предметов через фильтр. Запуск: python -m unittest planner.test_filtereval"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filtereval as fe  # noqa: E402

# Маленький фильтр по образцу настоящего: правило игрока, показ синих и жёлтых, белые до зоны 3.
FILTER = '''
Show # валюта при прокачке
	Class == "Stackable Currency"
	BaseType == "Orb of Transmutation" "Orb of Augmentation"
	AreaLevel <= 64

Hide # свитки
	Class == "Stackable Currency"
	BaseType == "Scroll of Wisdom"

Show # редкая экзотика
	TwiceCorrupted True
	Rarity Normal Magic Rare

Hide
	Rarity Normal Magic
	AreaLevel <= 15
	SetFontSize 18
	Class == "Wands" "Bows"

Show # украшение для больших синих
	Rarity Magic
	Height >= 3
	SetFontSize 40
	Continue

Show # жёлтое
	Rarity Rare
	AreaLevel <= 64

Show # синее в акте 1
	Rarity Magic
	Class == "Crossbows" "Sceptres" "Body Armours" "Wands"
	AreaLevel >= 3
	AreaLevel <= 16

#Show # выключено строгостью
#	Rarity Normal Magic
#	Class == "Crossbows"

Hide # старые базы
	DropLevel < 8
	Rarity Normal
	Class == "Crossbows"
	AreaLevel >= 22

Show # первые уровни
	Rarity Normal
	AreaLevel <= 3

Hide # последний слой
	Class == "Crossbows" "Sceptres" "Body Armours" "Wands" "Bows"
'''


def blocks():
    with tempfile.NamedTemporaryFile('w', suffix='.filter', delete=False, encoding='utf-8') as f:
        f.write(FILTER)
        path = f.name
    try:
        return fe.parse(path)
    finally:
        os.unlink(path)


class FilterEvalTest(unittest.TestCase):
    def setUp(self):
        self.b = blocks()

    def state(self, item):
        return fe.state(fe.verdict(self.b, item))

    def test_parse_skips_commented_blocks_and_styles(self):
        self.assertEqual(len(self.b), 10)
        custom = self.b[3]
        self.assertEqual(custom['action'], 'Hide')
        self.assertEqual(custom['conds'], ['Rarity Normal Magic', 'AreaLevel <= 15', 'Class == "Wands" "Bows"'])
        self.assertTrue(self.b[4]['cont'])

    def test_white_gear_hidden_after_first_zones(self):
        self.assertEqual(self.state(fe.gear('Crossbows', 'Normal', 2, 'Makeshift Crossbow', DropLevel=1)), 'show')
        self.assertEqual(self.state(fe.gear('Crossbows', 'Normal', 5, 'Makeshift Crossbow', DropLevel=1)), 'hide')
        self.assertEqual(self.state(fe.gear('Sceptres', 'Normal', 9, 'Rattling Sceptre', DropLevel=1)), 'hide')

    def test_magic_and_rare_follow_rules(self):
        self.assertEqual(self.state(fe.gear('Crossbows', 'Magic', 5, 'Makeshift Crossbow', DropLevel=1)), 'show')
        self.assertEqual(self.state(fe.gear('Sceptres', 'Magic', 9, 'Rattling Sceptre', DropLevel=1)), 'show')
        self.assertEqual(self.state(fe.gear('Wands', 'Magic', 9, 'Withered Wand', DropLevel=1)), 'hide')
        self.assertEqual(self.state(fe.gear('Wands', 'Rare', 9, 'Withered Wand', DropLevel=1)), 'show')
        self.assertEqual(self.state(fe.gear('Crossbows', 'Magic', 20, 'Makeshift Crossbow', DropLevel=1)), 'hide')

    def test_continue_block_does_not_decide(self):
        v = fe.verdict(self.b, fe.gear('Body Armours', 'Magic', 5, 'Feathered Robe', Height=3, DropLevel=5))
        self.assertEqual(v['action'], 'Show')
        self.assertTrue(v['sure'])

    def test_unknown_base_data_makes_answer_unsure(self):
        v = fe.verdict(self.b, fe.gear('Crossbows', 'Normal', 30, 'Makeshift Crossbow'))
        self.assertEqual(v['action'], 'Hide')
        self.assertTrue(v['sure'])  # сомнение и решение совпадают: оба прячут
        v = fe.verdict(self.b, fe.gear('Crossbows', 'Magic', 5))
        self.assertEqual(fe.state(v), 'show')

    def test_currency(self):
        self.assertEqual(self.state(fe.currency('Scroll of Wisdom', 5)), 'hide')
        self.assertEqual(self.state(fe.currency('Orb of Transmutation', 5)), 'show')
        self.assertEqual(self.state(fe.currency('Regal Shard', 5)), 'show')  # ни один блок не подошёл

    def test_diff(self):
        newer = [dict(b) for b in self.b]
        newer[3] = dict(newer[3], conds=['Rarity Normal Magic Rare'] + newer[3]['conds'][1:])
        gone, added = fe.diff(self.b, newer)
        self.assertEqual(len(gone), 1)
        self.assertEqual(added[0]['conds'][0], 'Rarity Normal Magic Rare')


if __name__ == '__main__':
    unittest.main()
