# -*- coding: utf-8 -*-
"""Item texts for the trial hero in the game's own copy format (Ctrl+Alt+C) — in any language of the game client.

Every word in them is the game's: the labels of a copy, item classes, rarities, base names and the wording of stats
come from the catalogue of game data (catalog/data/<version>/lang-<code>.json), tiers and value ranges from mods.json.
The items themselves are made up for a level-10 hero. The affix names in the headers are stand-ins (the program does
not show them); a rare item's own name is made up too — in the game it is two random words."""
import json
from pathlib import Path

SEP = '\n--------\n'
LIFE, MANA, COLD, FIRE = 'base_maximum_life', 'base_maximum_mana', 'base_cold_damage_resistance_%', 'base_fire_damage_resistance_%'
INT, SPEED = 'additional_intelligence', 'base_movement_velocity_+%'

NAMES = {
    'ring': {'ru': 'Вихрь горя', 'en': 'Gale Whorl', 'de': 'Sturmwirbel', 'es': 'Espiral de vendaval', 'fr': 'Spirale de tempête',
             'ja': '疾風の渦', 'ko': '돌풍의 고리', 'pt': 'Espiral do Vendaval', 'th': 'วงพายุ'},
    'boots_worn': {'ru': 'Тихий след', 'en': 'Quiet Trail', 'de': 'Stille Spur', 'es': 'Rastro silencioso', 'fr': 'Trace discrète',
                   'ja': '静かな足跡', 'ko': '고요한 자취', 'pt': 'Rastro Silencioso', 'th': 'รอยเท้าเงียบ'},
    'boots_new': {'ru': 'Быстрый шаг', 'en': 'Swift Stride', 'de': 'Flinker Tritt', 'es': 'Paso veloz', 'fr': 'Pas vif',
                  'ja': '迅速の歩み', 'ko': '빠른 걸음', 'pt': 'Passo Veloz', 'th': 'ก้าวว่องไว'},
}
# class and base — by their names in the game data; a mod: prefix | suffix, tier, stat, the value as a copy writes it
ITEMS = {
    'wand': {'cls': 'Wand', 'rarity': 'normal', 'base': 'Withered Wand', 'ilvl': 4},
    'sceptre': {'cls': 'Sceptre', 'rarity': 'normal', 'base': 'Rattling Sceptre', 'props': [('spirit', '100')], 'ilvl': 6},
    'ring': {'cls': 'Ring', 'rarity': 'rare', 'base': 'Lazuli Ring', 'ilvl': 9, 'implicit': [(MANA, '+24(20-30)')],
             'mods': [('prefix', 7, LIFE, '+22(20-29)'), ('suffix', 8, COLD, '+9(6-10)'), ('suffix', 8, INT, '+6(5-8)')]},
    'boots_worn': {'cls': 'Boots', 'rarity': 'rare', 'base': 'Straw Sandals', 'props': [('energy_shield', '14')], 'ilvl': 7,
                   'mods': [('prefix', 6, SPEED, '10'), ('prefix', 9, MANA, '+12(10-14)'), ('suffix', 8, COLD, '+7(6-10)')]},
    'boots_new': {'cls': 'Boots', 'rarity': 'rare', 'base': 'Straw Sandals', 'props': [('energy_shield', '14')], 'ilvl': 10,
                  'mods': [('prefix', 6, SPEED, '10'), ('prefix', 8, LIFE, '+26(20-29)'), ('suffix', 8, FIRE, '+9(6-10)'),
                           ('suffix', 8, COLD, '+10(6-10)')]},
}


def texts(project, lang):
    """{item key: the text the game would put into the clipboard} in the language of the game client."""
    data = Path(project) / 'catalog' / 'data'
    cat = data / (data / 'current.txt').read_text(encoding='utf-8').strip()
    pack = json.loads((cat / ('lang-%s.json' % lang)).read_text(encoding='utf-8'))
    copy = pack['copy']
    colon = ' : ' if lang == 'fr' else ': '                    # «Classe d'objet : Bottes»
    cls = {v: k for k, v in pack['classes'].items()}
    rarity = {v: k for k, v in copy['rarities'].items()}
    prop = {v: k for k, v in pack['props'].items()}

    def line(stat, value):
        return pack['stats'][stat][0].replace('#', value, 1)

    def head(kind, tier):
        return '{ %s %s }' % (copy[kind].replace('{0}', 'A'), copy['tier'].replace('{0}', str(tier)))

    out = {}
    for key, item in ITEMS.items():
        first = [copy['class'] + colon + cls[item['cls']], copy['rarity'] + colon + rarity[item['rarity']]]
        if item['rarity'] == 'rare':
            first.append(NAMES[key][lang])
        first.append(pack['bases'][item['base']])
        sections = [first]
        if item.get('props'):
            sections.append([prop[k] + colon + v for k, v in item['props']])
        sections.append([copy['ilvl'] + colon + str(item['ilvl'])])
        if item.get('implicit'):
            sections.append(['{ %s }' % copy['implicit']] + [line(s, v) + ' (implicit)' for s, v in item['implicit']])
        if item.get('mods'):
            sections.append([row for kind, tier, stat, value in item['mods'] for row in (head(kind, tier), line(stat, value))])
        out[key] = SEP.join('\n'.join(s) for s in sections) + '\n'
    return out


if __name__ == '__main__':
    import sys
    for name, text in texts(sys.argv[1], sys.argv[2]).items():
        print('=== %s\n%s' % (name, text))
