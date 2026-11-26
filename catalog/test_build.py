# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Проверка сборщика каталога на маленьких данных того же вида, что в выгрузках игры.
Запуск: python -m unittest catalog.test_build"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402
import fetch_icons  # noqa: E402


def mod(name, level, stats, on, gen='prefix', kind='IncreasedLife', domain='item', essence=False):
    return {'name': name, 'required_level': level, 'generation_type': gen, 'domain': domain, 'type': kind,
            'is_essence_only': essence, 'stats': [{'id': i, 'min': lo, 'max': hi} for i, lo, hi in stats],
            'spawn_weights': [{'tag': t, 'weight': w} for t, w in on]}


def text(ids, *variants):
    return {'ids': ids, 'English': [{'format': fmt, 'string': s} for fmt, s in variants]}


TEXTS = build.build_stat_texts([
    text(['base_maximum_life'], (['+#'], '{0} to maximum [Life]')),
    text(['local_armour'], (['+#'], '{0} to [Armour]')),
    text(['global_armour'], (['+#'], '{0} to [Armour]')),
    text(['min_fire', 'max_fire'], (['#', '#'], 'Adds {0} to {1} [Fire|Fire] Damage')),
    text(['speed'], (['#'], '{0}% increased Movement Speed'), (['#'], '{0}% reduced Movement Speed')),
])
MODS = {
    'Life1': mod('Hale', 1, [('base_maximum_life', 10, 19)], [('body_armour', 1), ('ring', 1), ('default', 0)]),
    'Life2': mod('Healthy', 6, [('base_maximum_life', 20, 29)], [('body_armour', 1), ('ring', 1), ('default', 0)]),
    'Life3': mod('Prime', 80, [('base_maximum_life', 200, 214)], [('body_armour', 1), ('default', 0)]),
    'Fire1': mod('Heated', 1, [('min_fire', 1, 2), ('max_fire', 3, 4)], [('crossbow', 1), ('default', 0)], kind='LocalFire'),
    'Hybrid1': mod('Oyster', 8, [('local_armour', 6, 13), ('base_maximum_life', 7, 10)], [('body_armour', 1)], kind='ArmourLife'),
    'ArmourBody': mod('Lacquered', 1, [('local_armour', 16, 27)], [('str_armour', 1), ('default', 0)], kind='Armour'),
    'ArmourBelt': mod('Lacquered', 1, [('global_armour', 12, 22)], [('belt', 1), ('default', 0)], kind='Armour'),
    'Essence': mod('Essences', 1, [('base_maximum_life', 30, 39)], [('ring', 1)], essence=True),
    'Monster': mod('x', 1, [('base_maximum_life', 1, 1)], [('default', 1)], domain='monster'),
    'Never': mod('y', 1, [('base_maximum_life', 1, 1)], [('default', 0)]),
    'Hidden': mod('z', 1, [('secret_stat', 1, 1)], [('ring', 1)], kind='Secret'),
}


class BuildTest(unittest.TestCase):
    def test_text_of_a_stat(self):
        self.assertEqual(build.shape('{0} to maximum [EnergyShield|Energy Shield]'.replace('{0}', '+#')),
                         '# to maximum Energy Shield')
        self.assertEqual(TEXTS['base_maximum_life'], ['# to maximum Life'])
        # одна строка текста — два свойства; у строки бывает и второе написание (уменьшение)
        self.assertEqual(TEXTS['min_fire max_fire'], ['Adds # to # Fire Damage'])
        self.assertEqual(TEXTS['speed'], ['#% increased Movement Speed', '#% reduced Movement Speed'])

    def test_families_and_their_lines(self):
        fams = build.build_mods(MODS, TEXTS)
        # не идут: аффиксы сущностей, чудовищ и те, что сами не выпадают нигде
        self.assertEqual(set(fams), {'Armour|prefix|global_armour', 'Armour|prefix|local_armour',
                                     'ArmourLife|prefix|local_armour base_maximum_life',
                                     'IncreasedLife|prefix|base_maximum_life', 'LocalFire|prefix|min_fire max_fire',
                                     'Secret|prefix|secret_stat'})
        life = fams['IncreasedLife|prefix|base_maximum_life']
        self.assertEqual([(m['id'], m['level'], m['vals']) for m in life['mods']],
                         [('Life1', 1, [[10, 19]]), ('Life2', 6, [[20, 29]]), ('Life3', 80, [[200, 214]])])
        # пара «от и до» — одна строка текста, гибрид — две, свойство без текста — строк нет
        self.assertEqual(life['lines'], ['base_maximum_life'])
        self.assertEqual(fams['LocalFire|prefix|min_fire max_fire']['lines'], ['min_fire max_fire'])
        self.assertEqual(fams['ArmourLife|prefix|local_armour base_maximum_life']['lines'],
                         ['local_armour', 'base_maximum_life'])
        self.assertIsNone(fams['Secret|prefix|secret_stat']['lines'])

    def test_tiers_depend_on_the_base(self):
        life = build.build_mods(MODS, TEXTS)['IncreasedLife|prefix|base_maximum_life']
        body = build.tiers(life, ['str_armour', 'body_armour', 'armour', 'default'])
        ring = build.tiers(life, ['ring', 'default'])
        # тир — как в игре: 1 — лучший из тех, что бывают на этой базе
        self.assertEqual([(m['id'], m['tier']) for m in body], [('Life1', 3), ('Life2', 2), ('Life3', 1)])
        self.assertEqual([(m['id'], m['tier']) for m in ring], [('Life1', 2), ('Life2', 1)])
        self.assertEqual(build.tiers(life, ['crossbow', 'default']), [])
        # решает первая метка аффикса, которая есть у базы
        m = {'on': [['no_life', 0], ['ring', 1], ['default', 0]]}
        self.assertTrue(build.fits(m, ['ring', 'default']))
        self.assertFalse(build.fits(m, ['ring', 'no_life', 'default']))

    def test_language_layer(self):
        items = '\n'.join(json.dumps(x, ensure_ascii=False) for x in (
            {'name': 'Полные латы', 'refName': 'Full Plate', 'namespace': 'ITEM'},
            {'name': 'Скелет-снайпер', 'refName': 'Skeletal Sniper', 'namespace': 'GEM'},
            {'name': 'Сфера', 'refName': 'Orb', 'namespace': 'CURRENCY'})) + '\n'
        stats = '\n'.join(json.dumps(x, ensure_ascii=False) for x in (
            {'ref': '# to Armour', 'matchers': [{'string': '# к броне'}], 'id': 'local_armour'},
            {'ref': 'Adds # to # Fire Damage', 'matchers': [{'string': 'Добавляет от # до # урона от огня'}]},
            {'ref': '#% increased Movement Speed', 'matchers': [{'string': '#% повышение скорости передвижения'},
                                                               {'string': '#% снижение скорости передвижения'}]}))
        ru = build.build_lang(items, stats, TEXTS)
        self.assertEqual(ru['bases'], {'Full Plate': 'Полные латы'})
        self.assertEqual(ru['gems'], {'Skeletal Sniper': 'Скелет-снайпер'})
        # один и тот же текст у двух свойств игры: перевод получают оба (броня доспеха и броня пояса)
        self.assertEqual((ru['stats']['local_armour'], ru['stats']['global_armour']), (['# к броне'], ['# к броне']))
        self.assertEqual(ru['stats']['min_fire max_fire'], ['Добавляет от # до # урона от огня'])
        self.assertEqual(len(ru['stats']['speed']), 2)
        self.assertNotIn('base_maximum_life', ru['stats'])       # перевода нет — строки нет

    def test_gems(self):
        gem = lambda name, kind, level, **more: dict({'base_item': {'display_name': name, 'release_state': 'released'},
                                                      'gem_type': kind, 'color': 'b', 'crafting_level': level}, **more)
        gems = build.build_gems({
            'Metadata/Items/Gems/SkillGemSkeletalSniper': gem(
                'Skeletal Sniper', 'active', 1, tags=['minion'], grants_skills=['SummonSkeletalSnipersPlayer'],
                requirement_weights={'dexterity': 0, 'intelligence': 100, 'strength': 0}),
            'Metadata/Items/Gem/SupportGemBidding': gem('Bidding I', 'support', 1,
                                                        icon_dds_file='Art/2DArt/SkillIcons/Support/4k/BiddingSupport.dds'),
            'Metadata/Items/Gems/SupportGemBidding': gem('Bidding (old)', 'support', 2),
            'Metadata/Items/Gems/Unreleased': {'base_item': {'display_name': 'x', 'release_state': 'unreleased'}},
            'Metadata/Items/Gems/Nameless': {'base_item': {}}})
        # id — последнее слово пути; одно слово у двух камней — второй назван путём целиком
        self.assertEqual(sorted(gems), ['Gems/SupportGemBidding', 'SkillGemSkeletalSniper', 'SupportGemBidding'])
        self.assertEqual(gems['SkillGemSkeletalSniper'], {
            'name': 'Skeletal Sniper', 'type': 'active', 'color': 'b', 'level': 1, 'req': {'int': 100},
            'tags': ['minion'], 'skills': ['SummonSkeletalSnipersPlayer']})
        self.assertEqual((gems['SupportGemBidding']['name'], gems['SupportGemBidding']['req']), ('Bidding I', {}))

    def test_gem_spirit(self):
        """Резерв духа камня по уровням — из данных умений (skills.json); камень восхождения помечен."""
        gem = lambda name, skills: {'base_item': {'display_name': name, 'release_state': 'released'},
                                    'gem_type': 'active', 'crafting_level': 1, 'grants_skills': skills}
        skills = {
            'SummonReaver': {'per_level': {'1': {'reservations': {'spirit': 90}}, '2': {'reservations': {'spirit': 65}},
                                           '4': {'reservations': {'spirit': 41}}}},
            'CommandReaver': {'per_level': {'1': {}}},
            'Spectre': {'static': {'reservations': {'spirit': 50}}},
            'Bomb': {'per_level': {'1': {}}, 'static': {}},
        }
        gems = build.build_gems({
            'Metadata/Items/Gems/SkillGemSkeletalReaver': gem('Skeletal Reaver', ['CommandReaver', 'SummonReaver']),
            'Metadata/Items/Gems/SkillGemSummonSpectre': gem('Spectre: {0}', ['Spectre']),
            'Metadata/Items/Gems/SkillGemFrostBomb': gem('Frost Bomb', ['Bomb']),
            'Metadata/Items/Gem/SkillGemAscendancySummonSandDjinn': gem('Kelari, the Tainted Sands', ['Djinn']),
        }, skills=skills)
        # пропущенный уровень — как предыдущий; без уровней — одно число на все; не резервирует — поля нет
        self.assertEqual(gems['SkillGemSkeletalReaver']['spirit'], [90, 65, 65, 41])
        self.assertEqual(gems['SkillGemSummonSpectre']['spirit'], [50])
        self.assertNotIn('spirit', gems['SkillGemFrostBomb'])
        self.assertEqual((gems['SkillGemAscendancySummonSandDjinn'].get('ascendancy'), gems['SkillGemFrostBomb'].get('ascendancy')),
                         (True, None))
        # правило гнёзд — своя таблица с источником: уровень героя у умения восхождения, сфера у камня умения
        game = json.loads((Path(build.__file__).resolve().parent / 'extra' / 'game.json').read_text(encoding='utf-8'))
        self.assertEqual(game['gemSockets'], {'level': {'3': 36, '4': 64, '5': 90},
                                              'orbs': {'3': "Lesser Jeweller's Orb", '4': "Greater Jeweller's Orb",
                                                       '5': "Perfect Jeweller's Orb"}})
        self.assertIn('Uncut_Skill_Gem', game['gemSocketsSource'])

    def test_gem_pictures(self):
        """У камня — его рисунок из данных игры и имя файла картинки: по ним картинки скачиваются все сразу."""
        gem = lambda name, kind, icon: {'base_item': {'display_name': name, 'release_state': 'released'},       # noqa: E731
                                        'gem_type': kind, 'icon_dds_file': icon}
        gems = build.build_gems({
            'Gems/SkillGemFrostBomb': gem('Frost Bomb', 'active', 'Art/2DArt/SkillIcons/4k/SorceressFrostBomb.dds'),
            'Gems/SkillGemBoon': gem("Alchemist's Boon", 'spirit', 'Art/2DArt/SkillIcons/4k/AlchemistsBoon.dds'),
            'Gems/SupportGemHeft': gem('Heft I', 'support', 'Art/2DArt/SkillIcons/Support/4k/HeftSupport.dds'),
            'Gems/SupportGemHeft2': gem('Heft II', 'support', 'Art/2DArt/SkillIcons/Support/4k/HeftSupport.dds'),
            'Gems/SkillGemAxe1': gem('Axe Slash', 'active', 'Art/2DArt/SkillIcons/4k/OneHandAxeDefaultSkill.dds'),
            'Gems/SkillGemAxe2': gem('Axe Slash', 'active', 'Art/2DArt/SkillIcons/4k/TwoHandAxeDefaultSkill.dds'),
            # без картинки: рисунка нет, рисунок — пустое имя в папке, служебные записи
            'Gems/SupportGemNoArt': gem('Infusion', 'support', ''),
            'Gems/SupportGemFolder': gem("Arbiter's Reach", 'support', '4k/'),
            'Gems/SkillGemRemoved': gem('Removed Skill', 'active', 'Art/2DArt/SkillIcons/4k/Removed.dds'),
            'Gems/SkillGemDnt': gem('[DNT-UNUSED] Axe Chop', 'active', 'Art/2DArt/SkillIcons/passives/4k/axedmg.dds'),
            # значка умения нет — рисунок самого камня-предмета; у заготовки «Coming Soon» картинки нет
            'Gems/SupportGemLineage': gem("Breachlord's Rift", 'support', '4k/'),
            'Gems/SkillGemSoon': gem('Coming Soon', 'active', '')},
            items={'Gems/SupportGemLineage': {'visual_identity': {'dds_file': 'Art/2DItems/Gems/Lineage/BreachlordsRemorse.dds'}},
                   'Gems/SkillGemSoon': {'visual_identity': {'dds_file': 'Art/2DItems/Gems/VaalGems/VaalSmite.dds'}},
                   'Gems/SupportGemHeft': {'visual_identity': {'dds_file': 'Art/2DItems/Gems/Support/Heft.dds'}}})
        self.assertEqual({k: (g.get('icon'), g.get('art')) for k, g in gems.items()}, {
            'SkillGemFrostBomb': ('skill-frost-bomb', 'Art/2DArt/SkillIcons/4k/SorceressFrostBomb'),
            'SkillGemBoon': ('skill-alchemist-s-boon', 'Art/2DArt/SkillIcons/4k/AlchemistsBoon'),
            'SupportGemHeft': ('sup-heft', 'Art/2DArt/SkillIcons/Support/4k/HeftSupport'),
            'SupportGemHeft2': ('sup-heft', 'Art/2DArt/SkillIcons/Support/4k/HeftSupport'),
            'SkillGemAxe1': ('skill-axe-slash', 'Art/2DArt/SkillIcons/4k/OneHandAxeDefaultSkill'),
            'SkillGemAxe2': ('skill-axe-slash', 'Art/2DArt/SkillIcons/4k/TwoHandAxeDefaultSkill'),
            'SupportGemNoArt': (None, None), 'SupportGemFolder': (None, None),
            'SkillGemRemoved': (None, None), 'SkillGemDnt': (None, None),
            'SupportGemLineage': ('sup-breachlord-s-rift', 'Art/2DItems/Gems/Lineage/BreachlordsRemorse'),
            'SkillGemSoon': (None, None)})
        # что скачивать: по картинке на имя файла — у рангов и у одноимённых умений она одна (первая)
        self.assertEqual(fetch_icons.wanted_gems(gems), {
            'skill-frost-bomb': 'Art/2DArt/SkillIcons/4k/SorceressFrostBomb',
            'skill-alchemist-s-boon': 'Art/2DArt/SkillIcons/4k/AlchemistsBoon',
            'sup-heft': 'Art/2DArt/SkillIcons/Support/4k/HeftSupport',
            'skill-axe-slash': 'Art/2DArt/SkillIcons/4k/OneHandAxeDefaultSkill',
            'sup-breachlord-s-rift': 'Art/2DItems/Gems/Lineage/BreachlordsRemorse'})
        # рисунки умений CDN хранит под путём строчными буквами, рисунки баз — как в данных игры
        self.assertEqual(fetch_icons.addresses('Art/2DArt/SkillIcons/4k/SorceressFrostBomb', lower=True), [
            'https://cdn.poe2db.tw/image/art/2dart/skillicons/4k/sorceressfrostbomb.webp',
            'https://cdn.poe2db.tw/image/Art/2DArt/SkillIcons/4k/SorceressFrostBomb.webp'])
        self.assertEqual(fetch_icons.addresses('Art/2DItems/Rings/Ring1')[0], 'https://cdn.poe2db.tw/image/Art/2DItems/Rings/Ring1.webp')
        self.assertEqual(fetch_icons.addresses('art/x', lower=True), ['https://cdn.poe2db.tw/image/art/x.webp'])

    def test_uncut_gem_rules(self):
        """С какой зоны падает неогранённый камень каждого уровня — из баз игры; остальное — своя таблица."""
        base = lambda name, drop: {'name': name, 'drop_level': drop}
        rules = build.build_rules({
            'Metadata/Items/Gems/SkillGemUncut9': base('Uncut Skill Gem (Level 9)', 32),
            'Metadata/Items/Gems/SkillGemUncut10': base('Uncut Skill Gem (Level 10)', 37),
            'Metadata/Items/Gems/SkillGemUncut11': base('Uncut Skill Gem (Level 11)', 42),
            'Metadata/Items/Gems/SkillGemUncut15': base('Uncut Skill Gem (Level 15)', 62),
            'Metadata/Items/Gems/SkillGemUncutQuest1': base('Uncut Skill Gem (Level 1)', 1),
            'Metadata/Items/Gems/SupportGemUncut2': base('Uncut Support Gem (Level 2)', 16),
            'Metadata/Items/Gems/SkillGemUncut': base('Uncut Skill Gem', 4),
        }, {'gemHero': [0, 3], 'mapGems': [[62, 15, 15], [70, 15, 17]]})
        self.assertEqual(rules['uncut'], {'skill': {'9': 32, '10': 37, '11': 42, '15': 62}, 'support': {'2': 16}})
        self.assertEqual(rules['gemHero'], [0, 3])
        import check_gem_levels as check
        # в зоне 40 с обычного чудовища падает только 10-й камень; с редкого (зона + 2) — уже 11-й
        self.assertEqual(check.level_at(rules['uncut']['skill'], 40), 10)
        self.assertEqual(check.gem_levels_in(rules, 40), {10, 11})
        self.assertEqual(check.gem_levels_in(rules, 36), {9, 10})
        self.assertEqual(check.gem_levels_in(rules, 20), set())          # ниже 9-го в этой таблице нет
        # с порога 15-го камня (зона 62) — только 15-й и выше, диапазоном по уровню зоны
        self.assertEqual((check.gem_levels_in(rules, 65), check.gem_levels_in(rules, 71)), ({15}, {15, 16, 17}))
        # зона под самым порогом: с обычных чудовищ ещё прежний уровень, с редких — уже 15-й, но не 20-й
        self.assertEqual((check.gem_levels_in(rules, 60), check.gem_levels_in(rules, 59)), ({11, 15}, {11}))

    def test_waystones(self):
        """Путевые камни: тир -> зона и сила аффиксов; у аффикса — видимые строки, плата и числа по силе."""
        way = lambda n, band, domain='area': {'name': 'Waystone (Tier %d)' % n, 'domain': domain,
                                              'tags': ['high_level_map', band, 'map', 'default']}
        items = {'Metadata/Items/Maps/MapKeyTier4': way(4, 'map_key_low'),
                 'Metadata/Items/Maps/MapKeyTier16': way(16, 'map_key_highest'),
                 'Metadata/Items/Maps/Copy': way(5, 'map_key_low', domain='item'),
                 'Metadata/Items/Armours/Plate': {'name': 'Full Plate', 'domain': 'item', 'tags': ['armour']}}
        formats = {}
        texts = build.build_stat_texts([
            text(['pen'], (['#'], 'Monster Damage Penetrates {0}% Elemental Resistances')),
            text(['crit'], (['#'], 'Monsters have {0}% increased [Critical|Critical Hit] Chance')),
            text(['multi'], (['+#'], 'Monsters have {0}% [Critical|Critical Damage Bonus]')),
            text(['chains'], (['ignore'], 'Players are periodically [Curse|Cursed] with [TemporalChains|Temporal Chains]')),
        ], formats)
        drop, rarity, pack = (
            'map_map_item_drop_chance_+%_final_from_map', 'map_item_drop_rarity_+%_final_from_map',
            'map_pack_size_+%_final_from_map')
        area = lambda *a, **k: mod(*a, domain='area', **k)
        mods = {
            'Pen1': area('Penetrating', 1, [('pen', 6, 8), (drop, 20, 20), (rarity, 16, 16)],
                         [('map_key_low', 1), ('default', 0)], kind='MapPen'),
            'Pen4': area('Penetrating', 1, [('pen', 14, 16), (drop, 20, 20), (rarity, 16, 16)],
                         [('map_key_highest', 1), ('default', 0)], kind='MapPen'),
            'Crit1': area('Destructive', 1, [('crit', 80, 120), ('multi', 11, 15), (drop, 15, 15), (pack, 9, 9)],
                          [('map_key_low', 1), ('default', 0)], kind='MapCrit'),
            'Chains': area('of Slowing', 1, [('chains', 1, 1), (drop, 20, 20), (pack, 8, 8)], [('default', 1)],
                           gen='suffix', kind='MapChains'),
            'Dead': area('x', 1, [('pen', 1, 1)], [('default', 0)], kind='MapDead'),
            'Gear': mod('Hale', 1, [('pen', 1, 1)], [('ring', 1)], kind='NotAMap'),
        }
        w = build.build_waystones(items, mods, texts, formats)
        self.assertEqual(w['tiers'], {
            '4': {'name': 'Waystone (Tier 4)', 'area': 68, 'band': 'map_key_low'},
            '16': {'name': 'Waystone (Tier 16)', 'area': 80, 'band': 'map_key_highest'}})
        # не идут: аффиксы вещей и те, что на камне сами не появляются
        self.assertEqual(set(w['mods']), {'MapPen', 'MapCrit', 'MapChains'})
        self.assertEqual(w['mods']['MapPen'], {
            'gen': 'prefix', 'stats': ['pen'], 'lines': ['pen'], 'fmt': ['#%'], 'pay': {'drop': 20, 'rarity': 16},
            'bands': {'map_key_low': [[6, 8]], 'map_key_highest': [[14, 16]]}})
        crit = w['mods']['MapCrit']
        # две строки одного аффикса; плата в видимые свойства не попадает
        self.assertEqual((crit['stats'], crit['lines'], crit['pay']), (['crit', 'multi'], ['crit', 'multi'],
                                                                         {'drop': 15, 'pack': 9}))
        self.assertEqual(crit['bands'], {'map_key_low': [[80, 120], [11, 15]]})
        # аффикс одной силы на все тиры
        self.assertEqual((w['mods']['MapChains']['gen'], w['mods']['MapChains']['bands']), ('suffix', {'any': [[1, 1]]}))

    def test_item_parts_for_the_stat_layer(self):
        """Свойства и собственные свойства баз, вставки в гнёзда, таблица статов героя, «написания наоборот»."""
        texts = build.build_stat_texts([
            text(['life'], (['+#'], '{0} to maximum [Life]')),
            text(['cold'], (['+#'], '{0}% to [Resistances|Cold Resistance]')),
            text(['min_cold', 'max_cold'], (['#', '#'], 'Adds {0} to {1} [Cold|Cold] Damage')),
            text(['speed'], (['#'], '{0}% increased Movement Speed'), (['#'], '{0}% reduced Movement Speed')),
        ])
        prop = lambda **more: dict({'armour': None, 'energy_shield': None, 'evasion': None, 'block': None,
                                    'movement_speed': None}, **more)
        items = {
            'Metadata/Items/Armours/Body/Plate': {
                'name': 'Full Plate', 'item_class': 'Body Armour', 'domain': 'item', 'release_state': 'released',
                'tags': ['str_armour', 'armour'], 'drop_level': 33, 'implicits': [],
                'properties': prop(armour={'min': 270, 'max': 270}, movement_speed=-500)},
            'Metadata/Items/Amulets/Blood': {
                'name': 'Bloodstone Amulet', 'item_class': 'Amulet', 'domain': 'item', 'release_state': 'released',
                'tags': ['amulet'], 'drop_level': 1, 'implicits': ['AmuletLife', 'Gone'], 'properties': prop(),
                'skills_granted': ['Metadata/Items/Gems/SkillGemBloodBoil']},
            'Metadata/Items/SoulCores/RuneCold': {'name': 'Glacial Rune', 'item_class': 'SoulCore', 'domain': 'undefined'},
        }
        bases = build.build_bases(items)
        self.assertEqual((bases['Armours/Body/Plate']['props'], bases['Armours/Body/Plate']['speed']), ({'armour': 270}, -5))
        self.assertNotIn('implicits', bases['Armours/Body/Plate'])
        self.assertEqual(bases['Amulets/Blood']['implicits'], ['AmuletLife', 'Gone'])
        self.assertNotIn('props', bases['Amulets/Blood'])
        # умения, которые база даёт сама, — ключами камней; у базы без них поля нет
        self.assertEqual(bases['Amulets/Blood']['grants'], ['SkillGemBloodBoil'])
        self.assertNotIn('grants', bases['Armours/Body/Plate'])
        mods = {'AmuletLife': mod('', 1, [('life', 30, 40)], [], gen='unique'), 'Other': mod('', 1, [('life', 1, 2)], [])}
        # собственные свойства — только те, что названы у баз и есть в данных
        self.assertEqual(build.build_implicits(items, mods, texts),
                         {'AmuletLife': {'stats': ['life'], 'vals': [[30, 40]], 'lines': ['life']}})
        aug = build.build_augments({'Metadata/Items/SoulCores/RuneCold': {
            'type_id': 'Rune', 'required_level': 15, 'categories': {
                'Armour': {'stat_text': ['+14% to [Resistances|Cold Resistance]'], 'stats': [{'id': 'cold', 'local': False}]},
                'Martial Weapon': {'stat_text': ['Adds 6 to 10 [Cold|Cold] Damage'],
                                   'stats': [{'id': 'min_cold', 'local': True}, {'id': 'max_cold', 'local': True}]},
                'Sceptre': {'stat_text': ['1% faster per 15 Spirit, up to 40%'], 'stats': [{'id': 'odd', 'local': False}]},
                'Wand or Staff': {'stat_text': [], 'stats': []}}}}, items, texts)
        rune = aug['RuneCold']
        self.assertEqual((rune['name'], rune['type'], rune['level'], sorted(rune['on'])),
                         ('Glacial Rune', 'Rune', 15, ['Armour', 'Martial Weapon', 'Sceptre']))
        self.assertEqual(rune['on']['Armour'], {'stats': ['cold'], 'vals': [14], 'lines': ['cold']})
        self.assertEqual(rune['on']['Martial Weapon'], {'stats': ['min_cold', 'max_cold'], 'vals': [6, 10], 'lines': ['min_cold max_cold']})
        # чисел в тексте не столько, сколько свойств — числа не берём; текста у свойства нет — строк нет
        self.assertEqual(rune['on']['Sceptre'], {'stats': ['odd'], 'vals': None, 'lines': None})
        stats = build.build_stats({'order': ['res_cold', 'nope'], 'stats': {
            'res_cold': {'ids': ['cold', 'renamed'], 'local': ['gone'], 'cap': 75}}}, texts)
        self.assertEqual(stats, {'stats': {'res_cold': {'ids': ['cold'], 'local': [], 'cap': 75}}, 'order': ['res_cold'],
                                 'missing': ['res_cold: renamed', 'res_cold: gone']})
        ru = build.build_lang('', json.dumps({'ref': '#% increased Movement Speed', 'matchers': [
            {'string': '#% повышение скорости передвижения'},
            {'string': '#% снижение скорости передвижения', 'negate': True}]}, ensure_ascii=False), texts)
        self.assertEqual(ru['less'], {'speed': ['#% снижение скорости передвижения']})

    def test_areas_and_bases(self):
        areas = build.build_areas({
            'NULL': {'name': 'NULL'},
            'G1_4': {'name': 'The Grelwood', 'act': 1, 'area_level': 4, 'has_waypoint': True, 'is_town': False,
                     'parent_town': 'G1_town', 'connections': ['G1_2', 'Gone'], 'bosses': ['Metadata/Monsters/Plant/Eater_']},
            'G1_2': {'name': 'Clearfell', 'act': 1, 'area_level': 2, 'connections': []}})
        self.assertEqual(sorted(areas), ['G1_2', 'G1_4'])
        self.assertEqual(areas['G1_4'], {'name': 'The Grelwood', 'act': 1, 'level': 4, 'town': False, 'waypoint': True,
                                         'parent': 'G1_town', 'links': ['G1_2'], 'bosses': ['Eater_']})
        bases = build.build_bases({
            'Metadata/Items/Weapons/Sceptres/S1': {'name': 'Rattling Sceptre', 'item_class': 'Sceptre', 'domain': 'item',
                                                   'release_state': 'released', 'tags': ['sceptre', 'onehand', 'default'],
                                                   'drop_level': 1, 'requirements': {'level': 1, 'strength': 0}},
            'Metadata/Items/X/Hidden': {'name': 'h', 'item_class': 'HiddenItem', 'domain': 'item', 'tags': []},
            'Metadata/Items/Flasks/F': {'name': 'f', 'item_class': 'LifeFlask', 'domain': 'flask', 'tags': []},
            'Metadata/Items/X/Old': {'name': 'o', 'item_class': 'Ring', 'domain': 'item', 'release_state': 'unreleased'}})
        self.assertEqual(bases, {'Weapons/Sceptres/S1': {'name': 'Rattling Sceptre', 'class': 'Sceptre',
                                                         'tags': ['sceptre', 'onehand', 'default'], 'level': 1,
                                                         'req': {'level': 1}}})

    def test_craft_part(self):
        """Часть о крафте: веса свойств страницы класса (выжимка poe2db) сведены с данными игры — у свойства
        его свойства с числами и строки текста; хэш вместо id находится по имени, уровню и стороне; названия
        валюты и сущностей сверены с таблицей предметов."""
        mods = {
            'Spirit1': {'domain': 'item', 'generation_type': 'prefix', 'name': "Lord's", 'required_level': 1,
                        'groups': ['Spirit'], 'stats': [{'id': 'spirit_pct', 'min': 10, 'max': 14}]},
            'Spirit2': {'domain': 'item', 'generation_type': 'prefix', 'name': "Baron's", 'required_level': 8,
                        'groups': ['Spirit'], 'stats': [{'id': 'spirit_pct', 'min': 15, 'max': 19}]},
            'Lich1': {'domain': 'desecrated', 'generation_type': 'suffix', 'name': 'of Amanamu', 'required_level': 65,
                      'groups': ['Gems'], 'stats': [{'id': 'minion_gems', 'min': 1, 'max': 2}]},
            'Ess1': {'domain': 'item', 'generation_type': 'prefix', 'name': 'Essence', 'required_level': 60,
                     'groups': ['Allies'], 'is_essence_only': True, 'stats': [{'id': 'ally_damage', 'min': 75, 'max': 89}]},
        }
        texts = {'spirit_pct': ['#% increased Spirit'], 'minion_gems': ['# to Level of all Minion Skills'],
                 'ally_damage': ['Allies deal #% increased Damage']}
        page = {'slug': 'Sceptres', 'class': 'Sceptre', 'attr': None,
                'normal': [{'id': 'Spirit1', 'name': "Lord's", 'lvl': 1, 'side': 'P', 'w': 1000, 'fams': ['Spirit'], 'text': 'x'},
                           {'id': 'a' * 64, 'name': "Baron's", 'lvl': 8, 'side': 'P', 'w': 800, 'fams': ['Spirit'], 'text': 'x'},
                           {'id': 'b' * 64, 'name': 'of Nowhere', 'lvl': 3, 'side': 'S', 'w': 50, 'fams': ['Odd'], 'text': 'odd text'},
                           {'id': 'Broken', 'lvl': 'x', 'side': 'P'}],
                'essence': [{'essence': 'Greater Essence of Command', 'id': 'Ess1', 'lvl': 60, 'side': 'P', 'fams': ['Allies'],
                             'removes': False, 'alloy': False},
                            {'essence': 'Essence of Nothing', 'id': 'Ess1', 'lvl': 60, 'side': 'P', 'fams': ['Allies']}],
                'desecrated': [{'id': 'Lich1', 'name': 'of Amanamu', 'lvl': 65, 'side': 'S', 'w': 1, 'fams': ['Gems'],
                                'lord': 'amanamu'}]}
        rules = {'grades': {'exalt': [['Exalted Orb', 0], ['Greater Exalted Orb', 35]]},
                 'bones': {'jaw': {'classes': ['Sceptre'], 'preserved': 'Preserved Jawbone'}},
                 'omens': {'echoes': 'Omen of Typo'}, 'slots': {'rare': 3}}
        names = {'Exalted Orb', 'Greater Exalted Orb', 'Preserved Jawbone', 'Greater Essence of Command'}
        craft = build.build_craft({'Sceptres': dict(page, attr=None), 'Helmets_int': dict(page, attr='Int', **{'class': 'Helmet'})},
                                  mods, texts, {'spirit_pct': '#%', 'minion_gems': '+#'}, rules, names)
        sc = craft['pages']['Sceptres']
        self.assertEqual((sc['class'], sc['attr'], craft['pages']['Helmets_int']['attr']), ('Sceptre', None, 'int'))
        self.assertEqual([(m['id'], m['w'], m['st'], m['lines'], m['fmt']) for m in sc['normal'][:2]],
                         [('Spirit1', 1000, [['spirit_pct', 10, 14]], ['spirit_pct'], ['#%']),
                          ('Spirit2', 800, [['spirit_pct', 15, 19]], ['spirit_pct'], ['#%'])])     # хэш найден по имени
        odd = sc['normal'][2]
        self.assertEqual((odd['id'], odd['w'], odd['st'], odd['text']), ('poe2db:bbbbbbbbbbbb', 50, [], 'odd text'))
        self.assertEqual(len(sc['normal']), 3)                                   # кривая запись не взята
        self.assertEqual([(m['id'], m['essence'], m['removes'], 'w' in m) for m in sc['essence']],
                         [('Ess1', 'Greater Essence of Command', False, False), ('Ess1', 'Essence of Nothing', False, False)])
        self.assertEqual([(m['id'], m['lord'], m['name'], m['fmt']) for m in sc['desecrated']],
                         [('Lich1', 'amanamu', 'of Amanamu', ['+#'])])
        self.assertEqual((sc['perfect_essence'], craft['matched'], craft['rules']), ([], 2, rules))
        self.assertEqual(craft['notes'], [
            'в правилах крафта предмет «Omen of Typo», которого нет в таблице предметов игры',
            'свойств, которых нет в данных игры: 2 (их вес учтён, что они дают — неизвестно)',
            'сущности «Essence of Nothing» нет в таблице предметов игры'])
        # выжимка лежит в папке источников отдельной папкой; нет её — части о крафте нет
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(build.read_digest(tmp), {})
            self.assertEqual(build.read_digest(None), {})
            (Path(tmp) / 'poe2db').mkdir()
            (Path(tmp) / 'poe2db' / 'Sceptres.json').write_text(json.dumps(page), encoding='utf-8')
            (Path(tmp) / 'poe2db' / 'broken.json').write_text('{', encoding='utf-8')
            (Path(tmp) / 'poe2db' / 'SOURCE.txt').write_text('откуда', encoding='utf-8')
            self.assertEqual(list(build.read_digest(tmp)), ['Sceptres'])

    def test_class_names_from_the_game_table(self):
        """Как игра называет класс предмета — из её таблицы классов; только классы, чьи базы есть в каталоге."""
        table = {'Shield': {'name': 'Shields', 'category': '[Shield]'}, 'Focus': {'name': 'Foci'},
                 'Warstaff': {'name': 'Quarterstaves'}, 'Currency': {'name': 'Stackable Currency'},
                 'Odd': {'name': ' '}, 'Bad': 'x'}
        bases = {'a': {'class': 'Shield'}, 'b': {'class': 'Focus'}, 'c': {'class': 'Warstaff'}, 'd': {'class': 'Odd'},
                 'e': {'class': 'Bad'}, 'f': {'class': 'Sceptre'}, 'g': {}}
        self.assertEqual(build.build_class_names(table, bases), {'Focus': 'Foci', 'Shield': 'Shields', 'Warstaff': 'Quarterstaves'})
        self.assertIn('item_classes.json', build.SOURCES)

    def test_base_knows_its_picture(self):
        """У базы — её рисунок из данных игры и имя файла картинки. Один рисунок у нескольких баз —
        одна картинка; одинаковое последнее слово пути у разных рисунков — имя вместе с папкой."""
        def item(name, dds):
            return {'name': name, 'item_class': 'Ring', 'domain': 'item', 'tags': ['ring'],
                    'visual_identity': {'dds_file': dds, 'id': name}}
        bases = build.build_bases({
            'Metadata/Items/Rings/A': item('Iron Ring', 'Art/2DItems/Rings/Basetypes/IronRing.dds'),
            'Metadata/Items/Rings/B': item('Runed Iron Ring', 'Art/2DItems/Rings/Basetypes/IronRing.dds'),
            'Metadata/Items/Rings/C': item('Gold Ring', 'Art/2DItems/Rings/Basetypes/Ring 02.dds'),
            'Metadata/Items/Rings/D': item('Other Ring', 'Art/2DItems/Amulets/Ring 02.dds'),
            'Metadata/Items/Rings/E': {'name': 'Plain', 'item_class': 'Ring', 'domain': 'item', 'tags': ['ring']}})
        self.assertEqual({b['name']: (b.get('art'), b.get('icon')) for b in bases.values()}, {
            'Iron Ring': ('Art/2DItems/Rings/Basetypes/IronRing', 'art-ironring'),
            'Runed Iron Ring': ('Art/2DItems/Rings/Basetypes/IronRing', 'art-ironring'),
            'Gold Ring': ('Art/2DItems/Rings/Basetypes/Ring 02', 'art-basetypes-ring-02'),
            'Other Ring': ('Art/2DItems/Amulets/Ring 02', 'art-amulets-ring-02'),
            'Plain': (None, None)})


    def test_unique_items_and_their_names(self):
        """Уникальные: английское имя (таблица игры), класс, свой рисунок и имя файла картинки (uniq-…), базы — из
        таблицы предметов Exiled Exchange 2, имена на языках — оттуда же. Переименованный в игре уникальный находится
        по рисунку; одно имя у двух уникальных на языке — список; у вариантов одного имени — рисунок первого;
        одинаковое последнее слово у разных рисунков — имя картинки по всему пути."""
        import base64

        def icon(f):
            raw = json.dumps([25, 14, {'f': f, 'w': 2, 'h': 1, 'scale': 1, 'realm': 'poe2'}]).encode()
            return 'https://web.poecdn.com/gen/image/%s/2feba3dafb/x.png' % base64.urlsafe_b64encode(raw).decode().rstrip('=')

        def uniq(name, cls, dds, alt=False):
            return {'id': name, 'name': name, 'item_class': cls, 'is_alternate_art': alt,
                    'visual_identity': {'dds_file': dds, 'id': name}}

        def rows(*items):
            return '\n'.join(json.dumps({'name': n, 'refName': ref, 'namespace': 'UNIQUE', 'unique': {'base': base},
                                         'icon': icon(f)}) for n, ref, base, f in items)
        table = {'1': uniq("Meginord's Girdle", 'Belt', 'Art/2DItems/Belts/Uniques/MeginordsGirdle.dds'),
                 '2': uniq('Byrnabas', 'Belt', 'Art/2DItems/Belts/Uniques/Byrnabas.dds'),
                 '3': uniq('Guiding Palm', 'Sceptre', 'Art/2DItems/Sceptres/Uniques/GuidingPalmFire.dds'),
                 '4': uniq('Guiding Palm', 'Sceptre', 'Art/2DItems/Sceptres/Uniques/GuidingPalmCold.dds'),
                 '5': uniq("Atziri's Disdain", 'Helmet', 'Art/2DItems/Helmets/Uniques/Disdain.dds'),
                 '6': uniq("Atziri's Contempt", 'Helmet', 'Art/2DItems/Helmets/Uniques/Contempt.dds'),
                 '7': uniq('Ring Girdle', 'Ring', 'Art/2DItems/Rings/Uniques/MeginordsGirdle.dds'),
                 '8': uniq('Old Art', 'Ring', 'Art/2DItems/Rings/Uniques/OldArt.dds', alt=True)}
        en = rows(("Meginord's Girdle", "Meginord's Girdle", 'Rawhide Belt', '2DItems/Belts/Uniques/MeginordsGirdle'),
                  ('Brynabas', 'Brynabas', 'Wide Belt', '2DItems/Belts/Uniques/Byrnabas'),
                  ('INCOMPLETE', 'INCOMPLETE', 'War Spear', '2DItems/Weapons/Spear'))
        de = rows(('Meginords Gurt', "Meginord's Girdle", 'Rawhide Belt', '2DItems/Belts/Uniques/MeginordsGirdle'),
                  ('Atziris Verachtung', "Atziri's Disdain", 'Helm A', '2DItems/Helmets/Uniques/Disdain'),
                  ('Atziris Verachtung', "Atziri's Contempt", 'Helm B', '2DItems/Helmets/Uniques/Contempt'))
        uniques, names = build.build_uniques(table, {'en': en, 'de': de})
        self.assertEqual(uniques["Meginord's Girdle"], {'class': 'Belt', 'art': 'Art/2DItems/Belts/Uniques/MeginordsGirdle',
                                                         'bases': ['Rawhide Belt'],
                                                         'icon': 'uniq-belts-uniques-meginordsgirdle'})
        self.assertEqual(uniques['Ring Girdle']['icon'], 'uniq-rings-uniques-meginordsgirdle')
        self.assertEqual((uniques['Byrnabas']['bases'], uniques['Byrnabas']['icon']), (['Wide Belt'], 'uniq-byrnabas'))
        self.assertEqual(uniques['Guiding Palm']['art'], 'Art/2DItems/Sceptres/Uniques/GuidingPalmFire')
        self.assertNotIn('Old Art', uniques)
        self.assertNotIn('INCOMPLETE', uniques)
        self.assertEqual(names, {'de': {'Meginords Gurt': "Meginord's Girdle",
                                        'Atziris Verachtung': ["Atziri's Disdain", "Atziri's Contempt"]}})
        self.assertEqual(build.ee2_art(icon('2DItems/Belts/Uniques/MeginordsGirdle')), 'Art/2DItems/Belts/Uniques/MeginordsGirdle')
        self.assertIsNone(build.ee2_art('%NOT_FOUND%'))
        # картинки уникальных качаются тем же загрузчиком; пробел в пути рисунка экранируется
        self.assertEqual(fetch_icons.wanted_uniques(uniques, {'Belt'}),
                         {'uniq-belts-uniques-meginordsgirdle': 'Art/2DItems/Belts/Uniques/MeginordsGirdle',
                          'uniq-byrnabas': 'Art/2DItems/Belts/Uniques/Byrnabas'})
        self.assertEqual(fetch_icons.addresses('Art/2DItems/Armours/Uniques/The Auspex')[0],
                         'https://cdn.poe2db.tw/image/Art/2DItems/Armours/Uniques/The%20Auspex.webp')


class GameTablesTest(unittest.TestCase):
    """Таблицы игры на языках клиента (catalog/dat_pack.py) -> тексты лога и названия зон."""

    def test_pack_and_log_text(self):
        import dat_pack
        import gzip
        by_lang = {
            'en': [{'Id': 'AsalaDone', 'Text': 'It is done.', 'NPCs': [0]}, {'Id': 'Mute', 'Text': '', 'NPCs': []}],
            'ru': [{'Id': 'AsalaDone', 'Text': 'Дело сделано.', 'NPCs': [0]}, {'Id': 'Mute', 'Text': '', 'NPCs': []}]}
        audio = dat_pack.pack_table('NPCTextAudio', by_lang, ['Id', 'Text', 'NPCs'])
        # код и говорящие — общие для всех языков, текст — по языкам
        self.assertEqual(audio['columns']['Id'], ['AsalaDone', 'Mute'])
        self.assertEqual(audio['columns']['Text']['ru'], ['Дело сделано.', ''])
        npcs = dat_pack.pack_table('NPCs', {'en': [{'Id': 'N/Asala', 'Name': 'Sekhema Asala'}],
                                            'ru': [{'Id': 'N/Asala', 'Name': 'Сехема Асала'}]}, ['Id', 'Name'])
        backend = dat_pack.pack_table('BackendErrors', {
            'en': [{'Id': 'LevelUp', 'Text': '{0} ({1}) is now level {2}'}, {'Id': 'Other', 'Text': 'x'}],
            'ru': [{'Id': 'LevelUp', 'Text': '{0} ({1}) достигает {2} уровня'}, {'Id': 'Other', 'Text': 'y'}]}, ['Id', 'Text'])
        areas = dat_pack.pack_table('WorldAreas', {'en': [{'Id': 'G1_1', 'Name': 'The Riverbank'}],
                                                   'ru': [{'Id': 'G1_1', 'Name': 'Берег реки'}]}, ['Id', 'Name'])
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'dat').mkdir()
            for name, tab in (('NPCTextAudio', audio), ('NPCs', npcs), ('BackendErrors', backend), ('WorldAreas', areas)):
                (Path(d) / 'dat' / (name + '.json.gz')).write_bytes(gzip.compress(json.dumps(tab).encode('utf-8')))
            log = build.build_log_text(d)
            names = build.build_area_names(d)
        self.assertEqual(sorted(log), ['en', 'ru'])
        self.assertEqual(log['ru'], {'npc': ['Сехема Асала'], 'say': {'AsalaDone': ['Дело сделано.', 0]},
                                     'msg': {'LevelUp': '{0} ({1}) достигает {2} уровня'}})
        self.assertEqual(names['ru'], {'G1_1': 'Берег реки'})
        # описания свойств игры: шаблоны по языкам, разметка снята, упрощённого китайского нет
        csd = ('description\r\n\t1 base_cold_damage_resistance_%\r\n\t1\r\n'
               '\t\t# "{0:+d}% to [Resistances|Cold Resistance]"\r\n'
               '\tlang "Simplified Chinese"\r\n\t1\r\n\t\t# "[Resistances|冰霜抗性] {0:+d}%"\r\n'
               '\tlang "Russian"\r\n\t2\r\n\t\t1|# "{0:+d}% к сопротивлению [Resistances|холоду]"\r\n'
               '\t\t#|-1 "{0}% к сопротивлению холоду" negate 1\r\n'
               'no_description dummy_stat\r\n')
        self.assertEqual(build.parse_csd(csd), [(('base_cold_damage_resistance_%',), {
            'en': ['{0:+d}% to Cold Resistance'],
            'ru': ['{0:+d}% к сопротивлению холоду', '{0}% к сопротивлению холоду']})])
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'dat').mkdir()
            (Path(d) / 'dat' / 'stat_descriptions.csd.gz').write_bytes(gzip.compress(csd.encode('utf-16')))
            self.assertEqual(build.build_stat_lines(d)['ru']['base_cold_damage_resistance_%'][0],
                             '{0:+d}% к сопротивлению холоду')
        # без папки dat частей нет — каталог собирается как раньше
        self.assertEqual((build.build_log_text(None), build.build_area_names(None)), ({}, {}))

    def test_names_for_pages(self):
        """Названия из игры для страницы на другом языке: по английскому названию, без разметки клиента; одно
        английское название с разными переводами — самый частый; узлы дерева — по id узла."""
        import dat_pack
        import gzip
        bases = dat_pack.pack_table('BaseItemTypes', {
            'en': [{'Id': 'A', 'Name': 'Rattling Sceptre'}, {'Id': 'B', 'Name': 'Frost Bomb'}, {'Id': 'C', 'Name': 'Same'}],
            'ru': [{'Id': 'A', 'Name': 'Гремящий скипетр'}, {'Id': 'B', 'Name': 'Морозная бомба'}, {'Id': 'C', 'Name': 'Same'}],
            'de': [{'Id': 'A', 'Name': 'Rasselndes Zepter'}, {'Id': 'B', 'Name': '<size:37>{Frostbombe}'}, {'Id': 'C', 'Name': 'Same'}]},
            ['Id', 'Name'])
        monsters = dat_pack.pack_table('MonsterVarieties', {
            'en': [{'Id': 'M1', 'Name': 'Zombie'}, {'Id': 'M2', 'Name': 'Zombie'}, {'Id': 'M3', 'Name': 'Zombie'}],
            'ru': [{'Id': 'M1', 'Name': 'Зомби'}, {'Id': 'M2', 'Name': 'Зомби'}, {'Id': 'M3', 'Name': 'Зомби'}],
            'de': [{'Id': 'M1', 'Name': 'Zombie'}, {'Id': 'M2', 'Name': 'Untoter'}, {'Id': 'M3', 'Name': 'Untoter'}]}, ['Id', 'Name'])
        passives = dat_pack.pack_table('PassiveSkills', {
            'en': [{'Id': 'fire37', 'Name': 'Volcanic Skin', 'PassiveSkillGraphId': 5}],
            'ru': [{'Id': 'fire37', 'Name': 'Вулканическая кожа', 'PassiveSkillGraphId': 5}],
            'de': [{'Id': 'fire37', 'Name': 'Vulkanische Haut', 'PassiveSkillGraphId': 5}]}, ['Id', 'Name', 'PassiveSkillGraphId'])
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'dat').mkdir()
            for name, tab in (('BaseItemTypes', bases), ('MonsterVarieties', monsters), ('PassiveSkills', passives)):
                (Path(d) / 'dat' / (name + '.json.gz')).write_bytes(gzip.compress(json.dumps(tab).encode('utf-8')))
            names = build.build_names(d)
        self.assertEqual(sorted(names), ['de'])          # английского и русского нет: их названия записаны в плане
        self.assertEqual(names['de']['names'], {'Rattling Sceptre': 'Rasselndes Zepter', 'Frost Bomb': 'Frostbombe',
                                                'Zombie': 'Untoter', 'Volcanic Skin': 'Vulkanische Haut'})
        self.assertEqual(names['de']['nodes'], {'fire37': 'Vulkanische Haut'})
        self.assertEqual(build.plain_name('<size:37>{ระเบิดน้ำแข็ง} '), 'ระเบิดน้ำแข็ง')
        self.assertEqual(build.plain_name('Lanzar al\xa0recibir daño'), 'Lanzar al recibir daño')


if __name__ == '__main__':
    unittest.main()
