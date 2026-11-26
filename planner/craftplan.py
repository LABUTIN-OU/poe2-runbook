# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Помощник крафта: следующий шаг для предмета — по желаемой форме, данным игры и весам свойств.

Откуда что берётся.
  * Веса свойств по классам предметов, свойства сущностей, очернённые свойства «владык» и правила валюты —
    часть каталога craft (catalog/build.py: выжимка страниц poe2db и catalog/extra/craft.json). Веса — оценка
    poe2db: в файлах игры их нет, поэтому шанс — «около», а не точное число.
  * Форма предмета — к чему на нём стремиться: статы билда по порядку с ролью. key — ключ: ловить первым, без
    него предмет брак; у ключа может быть порог min («+3»). max — к лучшей ступени, что бывает на этом уровне
    предмета. fill — любое свойство стата на оставшиеся места. Автор форму не пишет: её выводит default_form
    из статов этапа.
  * Шанс шага = вес нужных ступеней / вес всех ступеней, что могут выпасть: не выше уровня предмета, на нужной
    стороне, без групп, которые на предмете уже есть. Сфера с порогом (Большая, Совершенная) убирает ступени
    ниже порога; у свойства, все ступени которого ниже, остаётся высшая (у каждой строки свойства — своя).
  * Очернение — три разных варианта со стороны, заданной предзнаменованием, по тем же весам (допущение: веса
    вариантов не опубликованы). У очернённых свойств «владык» весов нет — шанс не считается.
  * Предзнаменование стороны (левши, правши) — только когда без него действие задело бы другую сторону: добавить —
    там есть свободное место, снять — там есть что снять. Три префикса заняты — кость и возвышение и так дают суффикс.
    Предзнаменование света — только когда Сфере отмены есть что снять, кроме очернённого.

«Хотя бы одно нужное среди нескольких свойств» считается точно, перебором групп свойств, а не случайными
пробами: ответ не зависит от случая и готов сразу.

Ответ plan — данные: kind (что это за ответ), parts — части строки для карточки копии (первая — главная),
tree — варианты с шансами, step — тот же шаг числами (что за действие, шанс, чем платят, какое свойство даёт
удача). Тексты — тексты программы (tr), названия из игры — на языке страницы.

Карточка рецепта (recipe; в карточке копии — for_row, в карточке слота — slot_card) — шаги plan подряд от самого
предмета, будто каждый удался: в неё идут только шаги к тому, что нужно плану (ключ слота и статы с целями автора),
у каждого места предмета — цена: как часто такое свойство встаёт на белую базу. Где искать базу (hunt) — две
следующие ступени ключа после надетой: лучшее окно уровня белой базы (window: Большие сферы сильнее на низком краю
окна, где в наборе меньше чужих ступеней), шанс для трёх ступеней сфер и зоны маршрута такого уровня. Тот же расчёт
говорит, какой срок цели по стату — на удачу (odds: в среднем больше LUCK баз до её порога).
"""
import gamedata
import herostats
import i18n
from i18n import tr

PARTS = ('normal', 'essence', 'perfect_essence', 'desecrated')
SIDES = ('P', 'S')
EPS = 1e-9
# Срок цели — на удачу, когда до её порога в среднем нужно больше стольких белых баз (шанс на базу ниже 10%).
# Это порог помощника, а не правило игры: так понято правило «срок не должен требовать удачи» — дешёвые попытки,
# какие средний забег делает по пути, срок держат; десятки баз и Больших сфер — уже нет.
LUCK = 10
MAX_STEPS = 12          # больше шагов пути не бывает: на редком предмете шесть мест, у каждого шага одно свойство


def rules(cat):
    """Правила валюты из каталога (catalog/extra/craft.json)."""
    return ((cat or {}).get('craft') or {}).get('rules') or {}


def page_of(cat, base):
    """Страница весов для базы: по классу предмета, а у доспеха — ещё и по роду («int_armour» — страница «int»)."""
    pages = ((cat or {}).get('craft') or {}).get('pages') or {}
    kind = next((t[:-len('_armour')] for t in (base or {}).get('tags') or () if t in gamedata.ARMOUR_KINDS), None)
    for page in pages.values():
        if page.get('class') == (base or {}).get('class') and (page.get('attr') is None or page['attr'] == kind):
            return page
    return None


class Game:
    """Каталог глазами помощника: названия и тексты на языке страницы, что даёт свойство."""

    def __init__(self, cat, lang=i18n.SOURCE):
        self.cat, self.lang = cat, lang
        self.stats = (cat.get('stats') or {}).get('stats') or {}
        self.pack = (cat.get('lang') or {}).get(lang) or {}
        self._ids = {}
        self._tier = None

    def base(self, name):
        return next((b for b in self.cat['bases'].values() if b['name'] == name), None)

    def name(self, en):
        """Название предмета из игры на языке страницы: «Сфера царей (Regal Orb)»."""
        return i18n.game_name((self.pack.get('bases') or {}).get(en), en, self.lang)

    def stat_name(self, sid):
        return (herostats._names(self.cat, self.lang).get(sid) or [sid])[0]

    def ids(self, sid):
        if sid not in self._ids:
            st = self.stats.get(sid) or {}
            self._ids[sid] = set(st.get('ids') or ()) | set(st.get('local') or ())
        return self._ids[sid]

    def span(self, rec, sid):
        """(от, до) первого свойства записи, которое идёт в стат билда; None — не идёт."""
        ids = self.ids(sid)
        return next(((lo, hi) for s, lo, hi in rec.get('st') or () if s in ids), None)

    def gives(self, rec, sid, minimum=None):
        """Даёт ли свойство стат билда (и не ниже порога, если он задан)."""
        r = self.span(rec, sid)
        return r is not None and (minimum is None or (r[0] is not None and r[0] >= minimum))

    def tier(self, mod_id):
        """Ступень обычного свойства в каталоге: (семейство, ступень) или None."""
        if self._tier is None:
            self._tier = {m['id']: (fam, m) for fam in self.cat['mods'].values() for m in fam['mods']}
        return self._tier.get(mod_id)

    def text(self, rec):
        """Строка свойства на языке страницы с числами ступени: «27–32% увеличение духа»."""
        spell_of = self.pack.get('stats') or {}
        vals = {s: (lo, hi) for s, lo, hi in rec.get('st') or ()}
        fmts, out = rec.get('fmt') or [], []
        for n, key in enumerate(rec.get('lines') or []):
            spell = spell_of.get(key)
            spell = spell[0] if isinstance(spell, list) and spell else spell
            if not isinstance(spell, str) or not spell:
                return rec.get('text') or rec.get('id') or ''
            nums = [vals[s] for s in key.split() if s in vals]
            pieces = spell.split('#')
            line = pieces[0]
            for k, piece in enumerate(pieces[1:]):
                if nums:
                    lo, hi = nums.pop(0)
                    sign = '+' if k == 0 and n < len(fmts) and str(fmts[n]).startswith('+') else ''
                    line += sign + (str(lo) if lo == hi else '%s–%s' % (lo, hi))
                else:
                    line += '#'
                line += piece
            out.append(line)
        return ' / '.join(out) if out else (rec.get('text') or rec.get('id') or '')


# --- шансы -------------------------------------------------------------------------------------------------------

def pool(page, ilvl, side=None, taken=frozenset(), min_lvl=0):
    """Ступени, которые могут выпасть: не выше уровня предмета, на стороне side, без занятых групп.
    Порог min_lvl убирает ступени ниже, но у свойства целиком ниже порога остаётся высшая ступень. Ступени — у каждой
    строки свойства свои: у амулета «+# к уровню умений приспешников» и «… чар» — одна группа игры (вместе на предмете
    не бывают), но высшая ступень остаётся у каждой."""
    lines = {}
    for m in page['normal']:
        if m['lvl'] > ilvl or m['w'] <= 0 or (side and m['side'] != side) or taken & set(m['fams']):
            continue
        lines.setdefault((tuple(m['fams']), m['side'], tuple(s[0] for s in m.get('st') or ())), []).append(m)
    out = []
    for tiers in lines.values():
        keep = [m for m in tiers if m['lvl'] >= min_lvl]
        out += keep or [max(tiers, key=lambda m: m['lvl'])]
    return out


def chance(mods, pred):
    total = sum(m['w'] for m in mods)
    return sum(m['w'] for m in mods if pred(m)) / total if total else 0.0


def all_miss(mods, pred, draws, cap=None):
    """Вероятность, что draws свойств, выпавших подряд, все не те. Свойства выпадают по весам; выпавшее убирает
    из набора всю свою группу (два свойства одной группы вместе не бывают). cap — не больше стольких свойств на
    сторону (сфера алхимии). Набор кончился раньше — дальше ничего не выпадает.
    Считается точно, перебором групп: свойства одной группы и стороны для набора неразличимы."""
    order, groups = {}, []
    for m in mods:
        key = (tuple(m['fams']), m['side'])
        i = order.get(key)
        if i is None:
            i = order[key] = len(groups)
            groups.append([0.0, 0.0, 0 if m['side'] == 'P' else 1, frozenset(m['fams'])])
        groups[i][0] += m['w']
        if not pred(m):
            groups[i][1] += m['w']
    n = len(groups)
    w, ms, sd = [g[0] for g in groups], [g[1] for g in groups], [g[2] for g in groups]
    # кого убирает из набора свойство группы: все группы, у которых с ней есть общее семейство
    out_of = [[j for j, h in enumerate(groups) if g[3] & h[3]] for g in groups]
    mask = [sum(1 << j for j in js) for js in out_of]

    def last(tot, mis, used):
        """Последнее свойство: шанс, что и оно не то."""
        open_p, open_s = cap is None or used[0] < cap, cap is None or used[1] < cap
        total = (tot[0] if open_p else 0.0) + (tot[1] if open_s else 0.0)
        if total <= EPS:
            return 1.0
        return ((mis[0] if open_p else 0.0) + (mis[1] if open_s else 0.0)) / total

    def go(alive, left, tot, mis, used):
        if left == 1:
            return last(tot, mis, used)
        open_side = [cap is None or used[0] < cap, cap is None or used[1] < cap]
        total = (tot[0] if open_side[0] else 0.0) + (tot[1] if open_side[1] else 0.0)
        if total <= EPS:
            return 1.0
        acc = 0.0
        for i in range(n):
            if not alive >> i & 1 or ms[i] <= 0 or not open_side[sd[i]]:
                continue
            t2, m2 = [tot[0], tot[1]], [mis[0], mis[1]]
            for j in out_of[i]:
                if alive >> j & 1:
                    t2[sd[j]] -= w[j]
                    m2[sd[j]] -= ms[j]
            u2 = [used[0], used[1]]
            u2[sd[i]] += 1
            acc += ms[i] / total * go(alive & ~mask[i], left - 1, t2, m2, u2)
        return acc

    tot = [sum(w[i] for i in range(n) if sd[i] == s) for s in (0, 1)]
    mis = [sum(ms[i] for i in range(n) if sd[i] == s) for s in (0, 1)]
    return go((1 << n) - 1, draws, tot, mis, [0, 0]) if n and draws > 0 else 1.0


def reveal(cat, page, ilvl, side, taken, pred, min_lvl=0, rerolls=0):
    """Очернение: хотя бы одно нужное среди трёх разных вариантов (rerolls — отголоски Бездны: ещё три)."""
    miss = all_miss(pool(page, ilvl, side, taken, min_lvl), pred, rules(cat).get('reveal') or 3)
    return 1.0 - miss ** (rerolls + 1)


def alchemy(cat, page, ilvl, pred):
    """Сфера алхимии: хотя бы одно нужное среди четырёх случайных свойств, не больше трёх на сторону."""
    rule = rules(cat).get('alchemy') or {}
    return 1.0 - all_miss(pool(page, ilvl), pred, rule.get('mods') or 4, rule.get('perSide') or 3)


def catch(cat, page, ilvl, pred, side):
    """Белая база → синий с нужным свойством: превращение, а если оно легло на другую сторону — усиление.
    По каждой ступени сфер: (сфера превращения, сфера усиления, шанс за превращение, шанс за усиление, итог на базу,
    доля превращений, легших на другую сторону, — столько в среднем на базу уходит сфер усиления)."""
    grades = rules(cat).get('grades') or {}
    out = []
    for (t_name, lvl), (a_name, _) in zip(grades.get('transmute') or (), grades.get('augment') or ()):
        mods = pool(page, ilvl, None, frozenset(), lvl)
        p_t = chance(mods, pred)
        other = chance(mods, lambda m: m['side'] != side)
        p_a = chance(pool(page, ilvl, side, frozenset(), lvl), pred)
        out.append((t_name, a_name, p_t, p_a, p_t + other * p_a, other))
    return out


def best_catch(rows):
    """Ступень сфер, которой ловят ключ: лучшая по шансу на базу из обычных и Больших. Совершенные — только среди
    вариантов: они редкие, а цену валюты помощник не знает. При равном шансе — обычные."""
    return max(rows[:2], key=lambda r: r[4]) if rows else None


def likely(mods, pred):
    """Свойство, которое шаг даёт при удаче: высшая по уровню ступень среди нужных (у «к максимуму» — лучшая),
    при равном уровне — с большим весом. None — нужного в наборе нет."""
    hits = [m for m in mods if pred(m)]
    return max(hits, key=lambda m: (m['lvl'], m['w'])) if hits else None


def window(cat, page, pred, side, lo, cap=None):
    """Окно уровня предмета для ловли ключа: (от, до, шанс на базу, последний ли это уровень данных). От — самый
    низкий уровень не ниже lo, где шанс на базу лучший; до — последний уровень подряд с тем же шансом. Ступени выше
    самой старшей на странице ничего не меняют — поэтому окно, дошедшее до неё, открыто вверх («55+»).
    cap — выше этого уровня не искать (предметы выше маршрута не падают): окно, дошедшее до cap, не открыто вверх.
    None — ключ здесь не ловится вовсе. Считается один раз на страницу весов и ключ."""
    data_top = max((m['lvl'] for m in page['normal']), default=0)
    top = min(data_top, cap) if cap else data_top
    key = (page.get('class'), page.get('attr'), side, lo, cap, tuple(sorted(m['id'] for m in page['normal'] if pred(m))))
    cache = cat.setdefault('_craftwin', {})
    if key in cache:
        return cache[key]
    best = None
    for lv in range(max(1, lo), max(top, lo) + 1):
        hit = best_catch(catch(cat, page, lv, pred, side))
        p = hit[4] if hit else 0.0
        if p <= EPS:
            continue
        if best is None or p > best[2] + EPS:
            best = [lv, lv, p]
        elif abs(p - best[2]) <= EPS and best[1] == lv - 1:
            best[1] = lv
    out = (best[0], best[1], best[2], best[1] >= data_top) if best else None
    if len(cache) > 256:
        cache.clear()
    cache[key] = out
    return out


# --- предмет ---------------------------------------------------------------------------------------------------------

def state(game, item, page):
    """Что на предмете: свойства записями страницы весов, стороны, занятые группы, ремесленное и очернённое места.
    Свойство, которого на странице нет, занимает место на своей стороне, а из набора ничего не исключает."""
    by_id = {}
    for part in PARTS:
        for r in page.get(part) or ():
            by_id.setdefault(r['id'], r)
    mods = []
    for m in item.get('mods') or []:
        rec = by_id.get(m.get('id')) if m.get('id') else None
        if rec is None:
            got = game.tier(m.get('id')) if m.get('id') else None
            side = m.get('side') or ('P' if got and got[0]['gen'] == 'prefix' else 'S')
            rec = {'id': m.get('id'), 'side': side, 'fams': [], 'lvl': got[1]['level'] if got else 0,
                   'st': [[s, v[0], v[1]] for s, v in zip(got[0]['stats'], got[1]['vals'])] if got else [],
                   'lines': got[0].get('lines') or [] if got else [], 'fmt': got[0].get('fmt') or [] if got else [],
                   'text': m.get('text')}
        mods.append(dict(rec, how=m.get('how')))
    return {'mods': mods, 'taken': frozenset(f for m in mods for f in m['fams']),
            'used': {s: sum(1 for m in mods if m['side'] == s) for s in SIDES},
            # что Сфера отмены может снять на стороне: расколотое не снимается
            'loose': {s: sum(1 for m in mods if m['side'] == s and m['how'] != 'fractured') for s in SIDES},
            'crafted': any(m['how'] == 'crafted' for m in mods),
            'desecrated': any(m['how'] == 'desecrated' for m in mods)}


def other_side(side):
    return 'S' if side == 'P' else 'P'


def side_omen(cat, kind, side, room):
    """Предзнаменование стороны (kind: exalt, bone, annul) для стороны side — только когда без него действие задело бы
    другую сторону: room — сколько там свободных мест (добавить) или свойств, которые можно снять (снять). 0 — оно
    лишнее: свойство и так встанет (снимется) только на side. None — не нужно."""
    return ((rules(cat).get('omens') or {}).get(kind) or {}).get(side) if room > 0 else None


def light_omen(cat, st):
    """Предзнаменование света к Сфере отмены — только когда на предмете есть что снять, кроме очернённого."""
    if any(m['how'] not in ('desecrated', 'fractured') for m in st['mods']):
        return (rules(cat).get('omens') or {}).get('light')
    return None


def joined(game, names):
    """Чем делают шаг — названиями игры через «+»; лишнего (None) нет."""
    return i18n.join(' + ', [game.name(x) for x in names if x])


def pct(x):
    """Шанс словами: «2,2%», «21%»."""
    if x <= 0:
        return '0%'
    if x < 0.1:
        whole, frac = ('%.1f' % (x * 100)).split('.')
        return tr('{0},{1}%##д').format(whole, frac)
    return '%d%%' % round(x * 100)


def per_base(x):
    if x <= 0:
        return tr('не выпадет')
    n = round(1 / x)
    return tr('в среднем ≈%d %s') % (n, i18n.plural(n, 'база|базы|баз'))


def answer(kind, parts, tree=(), step=None):
    """Ответ помощника: kind — что это (next — следующий шаг, catch — ловля ключа, waste — брак, ceiling — предмет
    у потолка, small — база мала, other — не та база, что у пути (off_path), done — готово, stop — менять нельзя,
    none — сказать нечего), parts — части
    строки (первая — главная), tree — варианты с шансами, line — строка целиком. step — тот же шаг числами (есть,
    когда ответ — действие с предметом):
      act   — catch (ловля ключа на белой базе), augment, essence, regal, bone (очернение), exalt, lich (очернённое
              свойство «владыки»: шанс неизвестен), clear (снять очернённый промах светом и отменой — наверняка;
              следом снова кость);
      stat, role, side — на какой стат формы и на какую сторону он идёт; p — шанс (у сущности 1), у кости p2 — с
              отголосками; any — шанс любого свойства этого стата (у «к максимуму»);
      uses  — чем платят за попытку (английские названия предметов игры; предзнаменования стороны — только когда
              без него задело бы другую сторону, иначе None); у ловли other — доля баз, которым нужна ещё и сфера
              усиления; echo — предзнаменование переброса, miss — чем снимают промах (тоже с None на месте лишнего);
      mod   — свойство, которое даёт удача (запись страницы весов), how — каким оно встаёт (crafted, desecrated);
      req   — уровень героя, которого потребует свойство сущности; spare — запасная сущность (три — на верстак);
      alt   — план Б (то же, без alt)."""
    parts = [p for p in parts if p]
    out = {'kind': kind, 'parts': parts, 'tree': list(tree), 'line': i18n.join(' · ', parts)}
    if step:
        out['step'] = step
    return out


def fit_form(game, page, form):
    """Порог цели — про одно свойство («+3»), только если хоть одна его ступень на этом классе до него дотягивает.
    Иначе он про сумму на предмете («дух от 120»: база и процент вместе) — тогда свойству порог не ставится."""
    reach = page['normal'] + page['desecrated']
    return [e if e.get('min') is None or any(game.gives(m, e['stat'], e['min']) for m in reach)
            else {k: v for k, v in e.items() if k != 'min'} for e in form]


def plan(cat, item, form, hero=None, lang=i18n.SOURCE):
    """Следующий шаг крафта предмета. item — base (английское название базы), ilvl, rarity (normal, magic, rare),
    corrupted и mods — свойства: id свойства в игре, how (crafted, desecrated, fractured), side — если id не известен.
    form — желаемая форма, hero — уровень героя (для требования свойства сущности)."""
    game = Game(cat, lang)
    base = game.base(item.get('base'))
    page = page_of(cat, base)
    ilvl, rarity = item.get('ilvl') or 0, item.get('rarity')
    if page is None or not form:
        return answer('none', [tr('нет весов для этого класса')])
    if item.get('corrupted'):
        return answer('stop', [tr('осквернён — изменить нельзя')])
    rule = rules(cat)
    grades, omens, things = rule.get('grades') or {}, rule.get('omens') or {}, rule.get('items') or {}
    bone = next((b for b in (rule.get('bones') or {}).values() if base['class'] in (b.get('classes') or ())), None)
    limits = rule.get('boneLimits') or {}
    st = state(game, item, page)
    tree = []
    form = fit_form(game, page, form)

    def want(entry):
        return lambda m: game.gives(m, entry['stat'], entry.get('min'))

    def side_of(entry):
        sides = {m['side'] for m in page['normal'] if game.gives(m, entry['stat'], entry.get('min'))}
        return sides.pop() if len(sides) == 1 else None

    def present(entry):
        return next((m for m in st['mods'] if game.gives(m, entry['stat'])), None)

    def value(m, sid):
        r = game.span(m, sid)
        return (r[1] or 0) if r else 0

    def ceiling(entry):
        """Лучшее свойство стата на этом уровне предмета — по самому стату, а не по уровню свойства: гибрид «дух +
        мана» бывает старше чистого духа, но духа даёт меньше."""
        mods = [m for m in page['normal'] if m['lvl'] <= ilvl and game.gives(m, entry['stat'])]
        return max(mods, key=lambda m: (value(m, entry['stat']), m['lvl'], m['w'])) if mods else None

    def label(entry):
        txt = game.stat_name(entry['stat']).lower()
        if entry.get('min') is None:
            return txt
        unit = (game.stats.get(entry['stat']) or {}).get('unit')
        return tr('%s от %s') % (txt, ('%s%%' % entry['min']) if unit == '%' else '+%s' % entry['min'])

    def req_note(level):
        req = int(level * (rule.get('heroLevel') or 0.8))
        return tr('потребует %d ур. героя (сейчас %d)') % (req, hero) if hero and req > hero else None

    def good(entry):
        """«К максимуму»: свойство, чьё нижнее значение не ниже 80% лучшего, что бывает на этом уровне предмета.
        (условие, порог) или (None, None), если стат здесь не бывает."""
        tops = [r[1] for m in page['normal'] if m['lvl'] <= ilvl
                for r in [game.span(m, entry['stat'])] if r and r[1] is not None]
        if not tops:
            return None, None
        bar = max(tops) * (rule.get('good') or 0.8)

        def pred(m):
            r = game.span(m, entry['stat'])
            return r is not None and r[0] is not None and r[0] >= bar
        return pred, bar

    def full(side):
        return tr('префиксы заняты') if side == 'P' else tr('суффиксы заняты')

    key = next((e for e in form if e['role'] == 'key'), form[0])
    key_side = side_of(key)
    key_here = present(key)
    key_ok = key_here is not None and (key.get('min') is None or game.gives(key_here, key['stat'], key['min']))
    need = min((m['lvl'] for m in page['normal'] if want(key)(m)), default=None)
    free = {s: (rule.get('slots') or {}).get(rarity, 0) - st['used'][s] for s in SIDES}

    def omen_to_add(kind, side):
        """Предзнаменование стороны, чтобы свойство встало на side: не нужно, когда другая сторона полна."""
        return side_omen(cat, kind, side, free.get(other_side(side), 0))

    def annul(side):
        """Чем снять свойство со стороны side: Сфера отмены, с предзнаменованием — только если на другой стороне
        есть что снять."""
        return [things.get('annul'), side_omen(cat, 'annul', side, st['loose'].get(other_side(side), 0))]

    # 0. ключ бывает только очернённым свойством «владыки» (фокус: «of Amanamu»): его вес не опубликован
    lich = [m for m in page['desecrated'] if want(key)(m)]
    if not key_ok and need is None and lich:
        lv, s = min(m['lvl'] for m in lich), lich[0]['side']
        names = ', '.join(sorted({m['name'] for m in lich if m.get('name')}))
        if ilvl < lv:
            return answer('small', [tr('база мала: «%s» здесь только очернением (%s), с ур. предмета %d')
                                    % (label(key), names, lv)], tree)
        if rarity != 'rare':
            word = tr('префикс') if s == 'P' else tr('суффикс')
            return answer('next', [tr('«%s» здесь только очернением (%s): сначала сделать жёлтым и оставить свободный %s')
                                   % (label(key), names, word)], tree)
        if st['desecrated']:
            return answer('next', [tr('очернённое место занято: %s, потом снова кость')
                                   % joined(game, [light_omen(cat, st), things.get('annul')])], tree)
        if free[s] <= 0:
            return answer('next', [tr('%s: сначала освободить один (%s)') % (full(s), joined(game, annul(s)))], tree)
        if not bone:
            return answer('none', [tr('нет весов для этого класса')], tree)
        omen = omen_to_add('bone', s)
        parts = [tr('дальше: %s (+ %s) → «%s» (%s) среди 3 — шанс неизвестен: веса очернённых свойств не опубликованы')
                 % (joined(game, [bone.get('preserved'), omen]), game.name(omens.get('echoes')), label(key), names)]
        if limits.get('gnawedMaxItem') and ilvl > limits['gnawedMaxItem']:
            parts.append(tr('%s не годится: только до ур. предмета %d') % (game.name(bone.get('gnawed')), limits['gnawedMaxItem']))
        return answer('next', parts, tree, {'act': 'lich', 'stat': key['stat'], 'role': key['role'], 'side': s, 'p': None,
                                            'uses': [bone.get('preserved'), omen],
                                            'echo': omens.get('echoes'), 'names': names})

    # 1. ключ на этом уровне предмета невозможен
    if not key_ok and (need is None or need > ilvl):
        if need is None:
            return answer('none', [tr('нет весов для этого класса')], tree)
        if rarity == 'normal':
            return answer('small', [tr('база мала: «%s» бывает с ур. предмета %s') % (label(key), need)], tree)
        return answer('ceiling', [tr('у потолка: «%s» здесь не будет — ур. предмета %d, нужно %s') % (label(key), ilvl, need),
                                  tr('не вкладывать, нужна новая база')], tree)

    # 2. белый: ловля ключа. Совершенные сферы — только среди вариантов: редкие, а цену валюты помощник не знает.
    if rarity == 'normal':
        rows = catch(cat, page, ilvl, want(key), key_side)
        for t_name, a_name, p_t, p_a, total, _other in rows:
            tree.append(tr('%s %s, легло на другую сторону — %s %s → %s на базу, %s')
                        % (game.name(t_name), pct(p_t), game.name(a_name), pct(p_a), pct(total), per_base(total)))
        if not rows:
            return answer('none', [tr('нет весов для этого класса')], tree)
        best = best_catch(rows)
        return answer('catch', [tr('ловля «%s»: %s (%s), легло на другую сторону — %s (%s)')
                                % (label(key), game.name(best[0]), pct(best[2]), game.name(best[1]), pct(best[3])),
                                tr('%s на базу, %s') % (pct(best[4]), per_base(best[4])),
                                tr('не выпало — на верстак 3 → 1')], tree,
                      {'act': 'catch', 'stat': key['stat'], 'role': key['role'], 'side': key_side, 'p': best[4],
                       'pt': best[2], 'pa': best[3], 'other': best[5], 'uses': [best[0], best[1]], 'label': label(key),
                       'mod': likely(pool(page, ilvl), want(key))})

    missing = [e for e in form if e is not key and present(e) is None]
    augment = (grades.get('augment') or [])[:2]

    # 3. синий
    if rarity == 'magic':
        if not key_ok:
            if key_side and free[key_side] > 0:
                rows = [(a, chance(pool(page, ilvl, key_side, st['taken'], lvl), want(key))) for a, lvl in augment]
                best = max(rows, key=lambda r: r[1])
                return answer('next', [tr('добрать ключ: %s → «%s» %s') % (game.name(best[0]), label(key), pct(best[1]))], tree,
                              {'act': 'augment', 'stat': key['stat'], 'role': key['role'], 'side': key_side, 'p': best[1],
                               'uses': [best[0]], 'label': label(key), 'miss': annul(key_side),
                               'mod': likely(pool(page, ilvl, key_side, st['taken']), want(key))})
            p_alc = alchemy(cat, page, ilvl, want(key))
            head = (tr('брак ловли: префикс занят не тем') if key_side == 'P' else
                    tr('брак ловли: суффикс занят не тем') if key_side == 'S' else tr('брак ловли: нужная сторона занята не тем'))
            return answer('waste', [head, tr('на верстак 3 → 1 (план Б: %s — ключ среди 4 свойств %s)')
                                    % (game.name(things.get('alchemy')), pct(p_alc))], tree)
        # ключ есть: сущность — её единственный момент
        for e in missing:
            ess = sorted((x for x in page['essence'] if not x['removes'] and game.gives(x, e['stat'])),
                         key=lambda x: -x['lvl'])
            if ess and not st['crafted']:
                top = ess[0]
                # запасная — ступенью ниже (три таких на верстаке дают одну старшую); у одной сущности бывает
                # несколько свойств (энергощит, броня, уклонение) — это не запасная, а та же самая
                spare = next((x['essence'] for x in ess[1:] if x['essence'] != top['essence']), None)
                return answer('next', [tr('дальше: %s → %s (наверняка)') % (game.name(top['essence']), game.text(top)),
                                       req_note(top['lvl']),
                                       tr('нет её — 3 × %s на верстаке') % game.name(spare) if spare else None],
                              tree,
                              {'act': 'essence', 'stat': e['stat'], 'role': e['role'], 'side': top['side'], 'p': 1.0,
                               'uses': [top['essence']], 'mod': top, 'how': 'crafted',
                               'req': int(top['lvl'] * (rule.get('heroLevel') or 0.8)), 'spare': spare})
        for e in missing:
            s = side_of(e)
            if s and free[s] > 0:
                rows = [(a, chance(pool(page, ilvl, s, st['taken'], lvl), want(e))) for a, lvl in augment]
                best = max(rows, key=lambda r: r[1])
                return answer('next', [tr('дальше: %s → «%s» %s') % (game.name(best[0]), label(e), pct(best[1]))], tree,
                              {'act': 'augment', 'stat': e['stat'], 'role': e['role'], 'side': s, 'p': best[1],
                               'uses': [best[0]], 'label': label(e), 'miss': annul(s),
                               'mod': likely(pool(page, ilvl, s, st['taken']), want(e))})
        # без сущности синий становится жёлтым случайным свойством: оно ляжет, вероятнее всего, на сторону, где в
        # наборе больше веса, — там путь и считает его место занятым
        rest = pool(page, ilvl, None, st['taken'])
        heavy = 'P' if sum(m['w'] for m in rest if m['side'] == 'P') >= sum(m['w'] for m in rest if m['side'] == 'S') else 'S'
        return answer('next', [tr('дальше: %s → жёлтый') % game.name(things.get('regal'))], tree,
                      {'act': 'regal', 'stat': None, 'role': None, 'side': heavy, 'p': None, 'uses': [things.get('regal')]})

    # 4. жёлтый
    if not key_ok:
        missing = [key] + missing
    blocked = []
    exalts = grades.get('exalt') or []
    # очернённое свойство, которое плану не нужно (промах кости): Предзнаменование света + Сфера отмены снимают именно
    # его, ничего другого не задев, — и место, и право на новое очернение снова свободны
    keeps = [e for e in form if e['role'] in ('key', 'max')]
    spare = next((m for m in st['mods'] if m['how'] == 'desecrated' and not any(
        game.gives(m, e['stat'], e.get('min') if e['role'] == 'key' else None) for e in keeps)), None) if bone else None

    def bone_rows(s, aim, any_pred, mods_now):
        """Очернение на сторону s предмета со свойствами mods_now (записи state): для Сохранившейся и Древней кости —
        (кость, шанс среди трёх, с отголосками, шанс любого свойства стата или None, предзнаменование стороны или None,
        чем снять промах, свойство при удаче)."""
        taken_now = frozenset(f for m in mods_now for f in m['fams'])
        room = (rule.get('slots') or {}).get(rarity, 0) - sum(1 for m in mods_now if m['side'] == other_side(s))
        omen = side_omen(cat, 'bone', s, room)
        undo_b = [light_omen(cat, {'mods': mods_now}), things.get('annul')]
        out = []
        for b_name, b_min in ((bone.get('preserved'), 0), (bone.get('ancient'), limits.get('ancientMinMod') or 0)):
            out.append((b_name, reveal(cat, page, ilvl, s, taken_now, aim, b_min, 0),
                        reveal(cat, page, ilvl, s, taken_now, aim, b_min, 1),
                        reveal(cat, page, ilvl, s, taken_now, any_pred, b_min, 0) if any_pred else None,
                        omen, undo_b, likely(pool(page, ilvl, s, taken_now, b_min), aim)))
        return out

    for e in missing:
        s = side_of(e)
        if s is None:
            continue
        # сторона полна, но на ней очернённый промах: сначала снять его, потом снова кость
        clear_first = free.get(s, 0) <= 0 and spare is not None and spare['side'] == s
        if free.get(s, 0) <= 0 and not clear_first:
            # наполнителю места не досталось — сказать нечего: о занятой стороне говорят только ключ и «к максимуму»
            if e['role'] != 'fill':
                blocked.append(tr('«%s»: %s##к') % (label(e), full(s)))
            continue
        # (шанс, способ, строка целиком, главная часть, что делать при промахе, тот же способ числами)
        options = []
        # «к максимуму» меряется лучшими ступенями этого уровня предмета, остальное — любым свойством стата
        top_pred, bar = good(e) if e['role'] == 'max' else (None, None)
        aim = want(e) if top_pred is None else top_pred
        ids = game.ids(e['stat'])
        # процент — когда так пишет свойство («27–32% увеличение духа») или сам стат билда в процентах (крит. урон
        # союзников: id свойства без знака процента, а в игре он «% увеличение»)
        unit = '%' if top_pred is not None and ((game.stats.get(e['stat']) or {}).get('unit') == '%' or any(
            sid.endswith('%') for m in page['normal'] if top_pred(m) for sid, _lo, _hi in m.get('st') or () if sid in ids)) else ''
        aim_word = label(e) if top_pred is None else tr('%s от %s') % (game.stat_name(e['stat']).lower(), '%d%s' % (bar, unit))
        # предзнаменования стороны — только когда другая сторона не полна (добавить) или на ней есть что снять (снять)
        omen_ex, undo = omen_to_add('exalt', s), annul(s)
        for n, (ex, lvl) in enumerate(exalts if not clear_first else ()):
            mods = pool(page, ilvl, s, st['taken'], lvl)
            p = chance(mods, aim)
            p_any = chance(mods, want(e)) if top_pred is not None else None
            how = joined(game, [ex, omen_ex]), aim_word, pct(p)
            text = (tr('%s → «%s» %s##к') % how if top_pred is None else
                    tr('%s → «%s» %s (любой: %s)') % (how + (pct(p_any),)))
            options.append((p, 'exalt-perfect' if n >= 2 else 'exalt', text, text, None,
                            {'act': 'exalt', 'p': p, 'any': p_any, 'uses': [ex, omen_ex], 'miss': undo,
                             'label': aim_word, 'mod': likely(mods, aim)}))
        if bone and not st['desecrated']:
            for b_name, p1, p2, p_any, omen_bone, undo_bone, got in bone_rows(
                    s, aim, want(e) if top_pred is not None else None, st['mods']):
                how = joined(game, [b_name, omen_bone]), aim_word, pct(p1)
                tail = game.name(omens.get('echoes')), pct(p2)
                main = (tr('%s → «%s» среди 3: %s; + %s: %s') % (how + tail) if top_pred is None else
                        tr('%s → «%s» среди 3: %s (любой: %s); + %s: %s')
                        % (how + (pct(p_any),) + tail))
                miss = tr('промах — %s') % joined(game, undo_bone)
                options.append((p1, 'bone', i18n.join(' · ', [main, miss]), main, miss,
                                {'act': 'bone', 'p': p1, 'p2': p2, 'any': p_any,
                                 'uses': [b_name, omen_bone], 'echo': omens.get('echoes'),
                                 'miss': undo_bone, 'label': aim_word, 'how': 'desecrated', 'mod': got}))
        elif spare is not None:
            # очернить снова можно, только сняв прошлый промах: снять наверняка, потом кость (шанс — у кости)
            gone = game.text(spare) if spare.get('lines') else (spare.get('text') or '?')
            tools = [light_omen(cat, st), things.get('annul')]
            for b_name, p1, p2, _any, omen_bone, _undo, _got in bone_rows(s, aim, None, [m for m in st['mods'] if m is not spare]):
                then = tr('%s → «%s» среди 3: %s; + %s: %s') % (joined(game, [b_name, omen_bone]), aim_word, pct(p1),
                                                               game.name(omens.get('echoes')), pct(p2))
                main = tr('%s — снять «%s», потом %s') % (joined(game, tools), gone, then)
                options.append((p1, 'clear', main, main, None,
                                {'act': 'clear', 'p': 1.0, 'uses': tools, 'label': tr('снять «%s»') % gone}))
        options.sort(key=lambda o: -o[0])
        tree += [o[2] for o in options]
        usable = [o for o in options if o[1] != 'exalt-perfect' and o[0] > 0]
        if usable:
            first = usable[0]
            other = next((o for o in usable if o[1] != first[1]), None)
            where = {'stat': e['stat'], 'role': e['role'], 'side': s}
            return answer('next', [tr('дальше: %s') % first[3], first[4],
                                   tr('план Б: %s') % other[2] if other else None], tree,
                          dict(first[5], alt=dict(other[5], **where) if other else None, **where))
    # всё на месте или мест нет: к максимуму
    gaps = []
    for e in form:
        here, top = present(e), ceiling(e)
        if e['role'] == 'max' and here and top and value(here, e['stat']) < value(top, e['stat']):
            gaps.append(tr('«%s», лучшее здесь «%s»') % (game.text(here), game.text(top)))
    if gaps or blocked:
        return answer('ceiling', [tr('у потолка мест: %s') % i18n.join('; ', gaps + blocked),
                                  tr('поднять — только удалив свойство (риск задеть нужное)')], tree)
    return answer('done', [tr('готово по форме')], tree)


# --- форма и предмет из копии ------------------------------------------------------------------------------------

def default_form(cat, at, slot, cls, floors=(), ahead=()):
    """Форма предмета по умолчанию — из статов этапа. at — билд на шаге (herostats.at_step), slot и cls — слот
    и класс предмета, floors — пороги автора для места слота (цели по стату: stat, min, goal), ahead — id целей,
    до которых надетый предмет ещё не дотянул.

    Берутся статы этапа, которые на предмете этого класса бывают. Редкие (их несут два-три слота билда) по порядку
    этапа — «ключ» и «к максимуму», прочие — «наполнитель». Ключ — первый редкий стат, у которого на этом слоте есть
    цель; нет такого — первый редкий. Порог ключа — порог его ближайшей недостигнутой цели (все достигнуты —
    старшей). У слота без редких статов ключа нет — формы нет: ловить на белой базе нечего.
    После ключа — статы, у которых на этом слоте есть цели автора (шлем «энергощит от 300»: сущность пойдёт на него,
    а не на сопротивление, которое в списке этапа стоит раньше), потом остальные — по порядку этапа."""
    table = herostats.carriers(cat, at)
    stats = [s['id'] for s in herostats.wanted(at) if herostats.may_carry(table, s['id'], slot, cls)]
    rare = [sid for sid in stats if herostats.is_rare(table, sid, slot)]
    if not rare:
        return []
    goals = {}
    for f in floors or ():
        goals.setdefault(f['stat'], []).append(f)
    key = next((sid for sid in rare if sid in goals), rare[0])
    form = [{'stat': key, 'role': 'key'}]
    mine = goals.get(key) or []
    if mine:
        near = [f for f in mine if f.get('goal') in ahead]
        form[0]['min'] = min(f['min'] for f in near) if near else max(f['min'] for f in mine)
    rest = [sid for sid in stats if sid != key]
    rest = [sid for sid in rest if sid in goals] + [sid for sid in rest if sid not in goals]
    form += [{'stat': sid, 'role': 'max' if sid in rare else 'fill'} for sid in rest]
    return form


def _tier(fam, mod, tags):
    """Ступень семейства, которая стоит на предмете: по диапазонам чисел из копии («28(27-32)»); у свойства с одним
    числом диапазона в копии нет («+3 к уровню…») — по самому числу; иначе по номеру «Уровень: N»."""
    tiers = gamedata.tiers(fam, tags) if tags else [dict(m, tier=None) for m in fam['mods']]
    spans = lambda t: sorted((float(v[0]), float(v[1])) for v in t.get('vals') or ()        # noqa: E731
                             if v[0] is not None and v[1] is not None)
    have = sorted((float(lo), float(hi)) for line in mod.get('ranges') or () for lo, hi in line)
    if not have:
        # числа без диапазонов: ступень, у которой каждое число одно и оно же стоит на предмете
        have = sorted((float(x), float(x)) for line in mod.get('values') or () for x in line)
    if have:
        same = [t for t in tiers if spans(t) == have]
        if len(same) == 1:
            return same[0]
    n = mod.get('tier')
    return next((t for t in tiers if n and t.get('tier') == n), None)


def copied_item(cat, item):
    """Предмет из копии (itemcopy.parse и identify) — в том виде, который читает plan. None — помощнику сказать
    нечего: предмет не опознан, уникален или его базы нет в данных игры."""
    if not item or not item.get('base_en') or not item.get('identified', True) or item.get('rarity') not in ('normal', 'magic', 'rare'):
        return None
    base = next((b for b in cat['bases'].values() if b['name'] == item['base_en']), None)
    page = page_of(cat, base)
    texts = ((cat.get('lang') or {}).get(item.get('lang')) or {}).get('stats') or {}
    mods = []
    for m in item.get('mods') or []:
        if m.get('kind') != 'explicit':
            continue
        side = 'P' if m.get('gen') == 'prefix' else 'S' if m.get('gen') == 'suffix' else None
        one = {'id': None, 'side': side, 'how': m.get('how'), 'text': ' / '.join(m.get('lines') or ())}
        fam = cat['mods'].get(m.get('fam')) if m.get('fam') else None
        tier = _tier(fam, m, item.get('tags')) if fam else None
        if tier:
            one['id'] = tier['id']
        elif page:
            # свойства сущности и очернённого в семействах каталога нет: ищем его на странице весов по строкам текста
            shapes = sorted(s.replace('+#', '#') for s in m.get('shapes') or ())
            for part in ('essence', 'perfect_essence', 'desecrated'):
                hit = next((r for r in page.get(part) or () if r.get('lines') and (side is None or r['side'] == side)
                            and len(r['lines']) == len(shapes)
                            and all(any(sh in texts.get(k, ()) for k in r['lines']) for sh in shapes)), None)
                if hit:
                    one['id'] = hit['id']
                    one['how'] = one['how'] or ('desecrated' if part == 'desecrated' else 'crafted')
                    break
        mods.append(one)
    return {'base': item['base_en'], 'ilvl': item.get('ilvl') or 0, 'rarity': item['rarity'],
            'corrupted': bool(item.get('corrupted')), 'mods': mods}


def wanted_rungs(row):
    """Ступени целей по стату, к которым ведёт форма предмета строки слота: в каждой лесенке — та, что план требует
    сейчас (plan: срок подошёл или прошёл — самая высокая из таких), иначе ближайшая недостигнутая. Без надетого
    скипетра на «Картах 6–10» это «+3», а не «+1», срок которого прошёл раньше."""
    return {(lad.get('plan') or lad.get('next'))['id'] for lad in row.get('parts') or ()
            if (lad.get('plan') or lad.get('next') or {}).get('id')}


def for_row(cat, at, view, row, item, hero=None, lang=i18n.SOURCE, here=None, levels=None, steps=()):
    """Крафт в карточке копии: карточка рецепта скопированного предмета (recipe) и где искать базу для слота строки
    (hunt). at — билд на шаге, где предмет строки носят; view — состояние забега; row — строка слота из сравнения
    копии (её st — сравнение с надетым: из него «попал — лучше надетого»); here, levels, steps — для hunt.
    Ответ: {kind — ответ plan для предмета или other (не та база), recipe, hunt}. None — сказать нечего."""
    if not (cat or {}).get('craft') or not item or not item.get('advanced', True) and item.get('rarity') != 'normal':
        return None
    thing = copied_item(cat, item)
    if thing is None:
        return None
    holder = None
    for r in view.get('holders') or []:
        if r.get('id') == row.get('row'):
            holder = r
    for stash in view.get('stash') or []:
        for r in stash.get('rows') or []:
            if r.get('id') == row.get('row'):
                holder = r
    ahead = wanted_rungs(holder) if holder else set()
    chain = ((holder or {}).get('base') or {}).get('chain') or ()
    floors = (at.get('floors') or {}).get(row.get('key')) or ()
    form = default_form(cat, at, row['slot'], item.get('cls_id'), floors, ahead)
    if not form:
        return None
    game = Game(cat, lang)
    wanted = wanted_of(floors, ahead, form)
    lines = [ln for ln in (row.get('st') or {}).get('lines') or ()
             if ln.get('id') and isinstance(ln.get('now'), (int, float)) and isinstance(ln.get('new'), (int, float))]
    vals = ({ln['id']: ln['now'] for ln in lines}, {ln['id']: ln['new'] for ln in lines}) if row.get('st') else None
    card = recipe(cat, thing, form, wanted, hero, vals, lang)
    if card is None:
        return None
    other = off_path(game, cat, at, row['slot'], chain, thing)
    if other:
        card = _as_other(card, other['line'])
    worn_val = next((ln.get('value') for ln in (((holder or {}).get('item') or {}).get('lines') or ())
                     if ln.get('id') == form[0]['stat']), 0) or 0
    return {'kind': card['kind'], 'recipe': card,
            'hunt': hunt(cat, at, row['slot'], chain, form, worn_val, here, levels, steps, lang)}


def _as_other(card, line):
    """Карточка предмета не на той базе, которой ведёт план: что на нём стоит — видно, шагов нет, вместо них — почему."""
    places = {side: [c if c['kind'] not in ('now', 'step') else {'kind': 'free'} for c in cells]
              for side, cells in card['places'].items()}
    return dict(card, kind='other', places=places, now={'kind': 'other', 'line': line, 'miss': None}, next=[])


# --- весь путь: от белой базы до готового предмета ------------------------------------------------------------------

def after(item, step):
    """Предмет после удачного шага: свойство, которое шаг ловил, — на месте. Сфера царей кладёт случайное свойство:
    путь считает занятым место на той стороне, куда оно вероятнее ляжет (step: side)."""
    mods, rarity, act = list(item.get('mods') or []), item.get('rarity'), step['act']
    if act == 'clear':
        # свет и отмена сняли очернённое свойство: на предмете оно одно
        return dict(item, mods=[m for m in mods if m.get('how') != 'desecrated'])
    if act == 'catch':
        rarity = 'magic'
    elif act in ('essence', 'regal'):
        rarity = 'rare'
    if step.get('mod'):
        mods.append({'id': step['mod']['id'], 'how': step.get('how')})
    elif act == 'regal':
        mods.append({'id': None, 'side': step.get('side') or 'P', 'how': None, 'text': '?'})
    return dict(item, rarity=rarity, mods=mods)


def span_text(lo, hi, open_end):
    """Окно уровня словами: «55–57», «65», «41+» (выше уровней на странице весов шанс уже не меняется)."""
    if open_end:
        return '%d+' % lo
    return '%d' % lo if lo == hi else '%d–%d' % (lo, hi)


def _period(cat, at, slot_id, chain=(), goals=()):
    """Что носят в слоте на шаге билда at: [(класс, род или None, базы-кандидаты, название цели или None)] — по
    странице весов на класс. chain — цели-базы периода (лесенка базы строки слота): если среди них есть названная
    («Гремящий скипетр (Rattling Sceptre)»), кандидаты — её базы (у общего названия — все базы с ним); иначе —
    все базы класса и рода периода. Награды (demigods) и сделанные из базы варианты (runeforged) не в счёт."""
    slot = next((s for s in at.get('slots') or [] if s.get('id') == slot_id), None)
    if slot is None:
        return []
    specs = [s for s in (slot.get('specs') or [slot.get('gear')]) if s]
    parts = [gamedata.spec_parts(s) for s in specs]
    classes = [c for c, _ in parts if c]
    by_id = {g.get('id'): g for g in goals or () if isinstance(g, dict)}
    named = [by_id[gid] for gid in chain or () if gid in by_id and not by_id[gid].get('any') and not by_id[gid].get('part')]
    for g in reversed(named):
        exact, bases = gamedata.named_bases(cat, g.get('title'), classes or None)
        if bases:
            cls = bases[0]['class']
            kind = next((k for c, k in parts if c == cls), None)
            return [(cls, kind, bases, None if exact else g.get('title'))]
    out = []
    for cls, kind in parts:
        bases = [b for b in cat['bases'].values() if b.get('class') == cls and b.get('name')
                 and (kind is None or kind in (b.get('tags') or ()))
                 and not {'demigods', 'runeforged'} & set(b.get('tags') or ())]
        if bases:
            out.append((cls, kind, bases, None))
    return out


def off_path(game, cat, at, slot_id, chain, thing):
    """Ответ «другая база», когда предмет не на той базе, которой ведёт путь крафта этого периода слота (_period: база,
    названная планом, иначе базы класса и рода периода): предмета пути из него не сделать — путь начинается с новой
    белой. None — база та или одинакова с ней по данным игры (gamedata.twins), или периоду слота сказать нечего."""
    bases = {b['name'] for cand in _period(cat, at, slot_id, chain, at.get('goals')) for b in cand[2]}
    if not bases or thing['base'] in bases or any(n in bases for n in gamedata.twins(cat, thing['base'])):
        return None
    return answer('other', [tr('другая база — %s: путь начинается с новой белой') % game.name(thing['base'])])


def _class_label(cat, cls, kind, lang):
    """Класс предмета словом клиента и, если назван, род базы: «Шлемы · Энергощит»."""
    import buildplan        # здесь, а не наверху: модуль страницы «Билд» тянет за собой много чего
    word = herostats.class_word(cat, cls, lang)
    return '%s · %s' % (word, buildplan.kind_label(cat, kind, lang)) if kind else word


def _base_what(game, cat, cand, lang):
    """Какая база: названная планом («Гремящий скипетр (Rattling Sceptre)»; с базами, одинаковыми с ней по данным игры, —
    «Тиара небес (Skycrown Tiara) или Тиара волшебника (Magus Tiara)»), общее название из плана или любая база класса
    и рода периода («любая — Шлемы · Энергощит»)."""
    cls, kind, bases, family = cand
    if family is None and len(bases) == 1:
        out = game.name(bases[0]['name'])
        for other in gamedata.twins(cat, bases[0]['name']):
            out = tr('%s или %s') % (out, game.name(other))
        return out
    return family if family else tr('любая — %s') % _class_label(cat, cls, kind, lang)


def _base_line(game, cat, cand, win, lang):
    return tr('база: %s, ур. предмета %s') % (_base_what(game, cat, cand, lang), win)


def best_bar(cat, game, page, sid, ilvl):
    """Порог «к максимуму» для стата на этом уровне предмета: нижнее значение свойства — не меньше 0,8 лучшего, что
    здесь бывает (правило good каталога), целым числом. None — стат на этом уровне не бывает."""
    tops = [r[1] for m in page['normal'] if m['lvl'] <= ilvl for r in [game.span(m, sid)] if r and r[1] is not None]
    if not tops:
        return None
    bar = max(tops) * (rules(cat).get('good') or 0.8)
    return int(bar) if bar == int(bar) else int(bar) + 1


def _key_of(game, page, form):
    """Ключ формы на этой странице весов: (запись формы, условие «даёт ключ», сторона или None, с какого уровня
    предмета бывает или None)."""
    form = fit_form(game, page, form)
    key = next((e for e in form if e['role'] == 'key'), form[0])
    pred = lambda m: game.gives(m, key['stat'], key.get('min'))        # noqa: E731
    sides = {m['side'] for m in page['normal'] if pred(m)}
    need = min((m['lvl'] for m in page['normal'] if pred(m)), default=None)
    return key, pred, (sides.pop() if len(sides) == 1 else None), need


# --- карточка рецепта: места предмета, шаг сейчас, шаги дальше; где искать базу ----------------------------------
#
# Рецепт — шаги plan подряд от самого предмета, будто каждый удался; в карточку идут только шаги, которые ловят то,
# что нужно плану: ключ слота и статы с целями автора (и переход в жёлтый, если за ним такой шаг есть). У каждого
# места предмета — цена: как часто такое свойство встаёт на белую базу (у шага — его шанс). Где искать базу — две
# следующие ступени ключа после надетой: с какого уровня предмета бывают, лучшее окно уровня, шанс на белую базу для
# трёх ступеней сфер и зоны маршрута с таким уровнем.

MAPS_FROM = 65                                           # с этого уровня зоны — карты (тир 1)


def one_in(p):
    """Шанс в штуках: «1 из 58»; наверняка — «наверняка». None — так не выпадет."""
    if p is None or p <= EPS:
        return None
    if p >= 1 - EPS:
        return tr('наверняка')
    return tr('1 из %d') % max(2, round(1 / p))


def _again(cat, game, page, ilvl, rec, sid):
    """Как часто свойство стата не слабее этого встаёт на белую базу того же уровня (превращение, легло на другую
    сторону — усиление; лучшая из обычных и Больших сфер). Свойство сущности — наверняка. None — так не ловится."""
    if rec.get('how') == 'crafted':
        return 1.0
    r = game.span(rec, sid)
    if not r or r[0] is None:
        return None
    got = best_catch(catch(cat, page, ilvl, lambda m: game.gives(m, sid, r[0]), rec.get('side')))
    return got[4] if got and got[4] > EPS else None


def _num(rec, x):
    """Число в виде свойства: «+3», «75–89%» — по формату строки свойства в игре."""
    fmt = str((rec.get('fmt') or [''])[0])
    return ('+' if fmt.startswith('+') else '') + x + ('%' if '%' in fmt else '')


def _aim(game, s):
    """На что шаг, коротко: «уровень умений приспешников от +3», «урон союзников в присутствии 75–89%»."""
    if s.get('label'):
        return s['label']
    mod, sid = s.get('mod'), s.get('stat')
    r = game.span(mod, sid) if mod and sid else None
    if r:
        lo, hi = r
        return '%s %s' % (game.stat_name(sid).lower(), _num(mod, str(lo) if lo == hi else '%s–%s' % (lo, hi)))
    return tr('случайное свойство')


def _tool(game, s):
    """Чем делают шаг — названиями игры."""
    uses = [x for x in s.get('uses') or () if x]
    if s['act'] == 'catch' and len(uses) > 1:
        return tr('%s, легло на другую сторону — %s') % (game.name(uses[0]), game.name(uses[1]))
    return i18n.join(' + ', [game.name(x) for x in uses])


def _odds(s):
    if s['act'] == 'regal':
        return None
    return one_in(1.0 if s['act'] == 'essence' else s.get('p'))


def _echo(game, s):
    """Совет к очернению: Предзнаменование отголосков Бездны — варианты можно перебросить один раз, это две попытки по
    три варианта; шанс с ним (у свойства «владыки» — без шанса: его вес не опубликован). Есть ли оно у игрока, помощник
    не знает — поэтому это совет рядом с шагом, а цена места остаётся без него. None — у шага такого совета нет."""
    if s['act'] not in ('bone', 'lich') or not s.get('echo'):
        return None
    odds = one_in(s.get('p2'))
    return (tr('%s: 2 попытки по 3 — %s') % (game.name(s['echo']), odds) if odds else
            tr('%s: 2 попытки по 3') % game.name(s['echo']))


def _miss(game, cat, s, keep):
    """Что делать при промахе шага. keep — как часто встаёт самое редкое из нужного, что на предмете уже есть (None —
    ничего). Снимать промах Сферой отмены с предзнаменованием стороны стоит, только если на предмете есть то, что реже
    самого шага; иначе предмет не жалко — на верстак. Чем снимать — miss шага: предзнаменование стороны или света в нём
    только тогда, когда без него Сфера отмены могла бы снять другое."""
    rule = rules(cat)
    things, omens = rule.get('items') or {}, rule.get('omens') or {}
    act = s['act']
    if act in ('essence', 'regal', 'lich', 'clear'):
        return None
    if act == 'bone':
        return tr('промах — %s, новая кость') % joined(game, s.get('miss') or [omens.get('light'), things.get('annul')])
    if act in ('augment', 'exalt') and keep is not None and s.get('p') and keep < s['p']:
        undo = s.get('miss') or [things.get('annul'), (omens.get('annul') or {}).get(s.get('side'))]
        return tr('промах — %s: снять и повторить') % joined(game, undo)
    return tr('промах — на верстак 3 → 1')


def _hit(game, s, form, vals):
    """«попал — лучше надетого: +3 против +2»: шаг поднимает редкий стат (ключ или «к максимуму») выше, чем у надетого.
    vals — (надетый, этот предмет): стат → число. None — сравнивать не с чем, свойство меняет саму вещь (local), или
    шаг надетого не обгоняет."""
    mod, sid = s.get('mod'), s.get('stat')
    if not vals or not mod or not sid:
        return None
    if next((e['role'] for e in form if e['stat'] == sid), None) not in ('key', 'max'):
        return None
    r = next(((x, lo) for x, lo, _hi in mod.get('st') or () if x in game.ids(sid)), None)
    if r is None or r[1] is None or r[0].startswith('local_'):
        return None
    worn, now = vals
    new, old = (now.get(sid) or 0) + r[1], worn.get(sid) or 0
    if new <= old:
        return None
    return tr('попал — лучше надетого: %s против %s') % (_num(mod, '%g' % new), _num(mod, '%g' % old))


def wanted_of(floors, ahead, form):
    """Что план ловит на слоте: стат → порог цели автора (ближайшая недостигнутая цель; все достигнуты — старшая) или
    None. Ключ формы — всегда, даже без цели."""
    out = {}
    for f in floors or ():
        out.setdefault(f['stat'], []).append(f)
    for sid, mine in list(out.items()):
        near = [f['min'] for f in mine if f.get('goal') in (ahead or ()) and f.get('min') is not None]
        every = [f['min'] for f in mine if f.get('min') is not None]
        out[sid] = min(near) if near else (max(every) if every else None)
    if form:
        out.setdefault(form[0]['stat'], form[0].get('min'))
    return out


def _rarity(r):
    return {'normal': tr('белый##редкость'), 'magic': tr('синий##редкость'), 'rare': tr('жёлтый##редкость')}.get(r, '')


def recipe(cat, item, form, wanted, hero=None, vals=None, lang=i18n.SOURCE):
    """Карточка рецепта предмета. item — предмет в виде copied_item; form — форма (default_form); wanted — статы,
    которые план ловит на этом слоте (ключ и статы с целями автора); vals — для строки «попал — лучше надетого»
    (надетый, этот предмет: стат → число), None — сравнивать не с чем.

    Ответ: {base, ilvl, rarity, kind — ответ plan для самого предмета, places — {P, S}: по три места [{kind: have —
    нужное есть, low — ключ ниже цели, other — не нужное, now — шаг сейчас, step — шаг дальше, free — свободно; n —
    номер шага; text; price — «1 из N» или «наверняка»}], now — шаг сейчас {n, tool, aim, odds, echo — совет переброса
    вариантов у очернения, hit, miss} или почему
    шага нет {kind, line, miss}, next — шаги дальше [{n, tool, aim, odds}]}. None — сказать нечего."""
    game = Game(cat, lang)
    page = page_of(cat, game.base(item.get('base')))
    if page is None or not form:
        return None
    if not isinstance(wanted, dict):
        wanted = dict.fromkeys(wanted)
    first = plan(cat, item, form, hero, lang)
    if first['kind'] == 'none':
        return None
    form = fit_form(game, page, form)
    raw, cur = [], item
    for _ in range(MAX_STEPS):
        s = plan(cat, cur, form, hero, lang).get('step')
        if not s:
            break
        raw.append(s)
        if not s.get('mod') and s['act'] not in ('regal', 'clear'):
            break
        cur = after(cur, s)
    goal = lambda s: s.get('stat') in wanted        # noqa: E731
    steps = [s for i, s in enumerate(raw)
             if goal(s) or (s['act'] in ('regal', 'essence', 'clear') and any(goal(x) for x in raw[i + 1:]))]
    ilvl = item.get('ilvl') or 0
    key = next((e for e in form if e['role'] == 'key'), None)
    places, keep = {'P': [], 'S': []}, None
    # шаг «снять очернённый промах»: его места в карточке нет — там уже то, что встанет следующей костью
    clearing = any(s['act'] == 'clear' for s in steps)
    for m in state(game, item, page)['mods']:
        if clearing and m['how'] == 'desecrated':
            continue
        sid = next((e['stat'] for e in form if e['stat'] in wanted and game.gives(m, e['stat'])), None)
        cell = {'kind': 'other', 'text': game.text(m) if m.get('lines') else (m.get('text') or '?')}
        if sid:
            # ниже цели автора — не зелёное; цель про сумму на предмете («дух от 120») одним свойством не меряется
            bar = key.get('min') if key is not None and sid == key['stat'] else wanted.get(sid)
            low = (bar is not None and any(game.gives(x, sid, bar) for x in page['normal'])
                   and not game.gives(m, sid, bar))
            p = _again(cat, game, page, ilvl, m, sid)
            cell.update(kind='low' if low else 'have', price=one_in(p))
            if not low and p is not None:
                keep = p if keep is None else min(keep, p)
        places['S' if m['side'] == 'S' else 'P'].append(cell)
    for n, s in enumerate(steps, 1):
        s['n'] = n
        if s['act'] not in ('regal', 'clear'):
            places['S' if s.get('side') == 'S' else 'P'].append(
                {'kind': 'now' if n == 1 else 'step', 'n': n, 'text': _aim(game, s), 'price': _odds(s)})
    for side in places:
        places[side] = (places[side] + [{'kind': 'free'}] * 3)[:3]
    def need(s):
        # свойство сущности требует уровня героя: шаг сделать можно, надеть предмет — нет
        return tr('потребует %d ур. героя (сейчас %d)') % (s['req'], hero) if hero and s.get('req') and s['req'] > hero else None
    if steps:
        s = steps[0]
        # у шага без места в карточке (снять очернённое) — что он делает, прямо в строке шага: как в строках «Дальше»
        tool = i18n.join(' — ', [_tool(game, s), _aim(game, s)]) if s['act'] == 'clear' else _tool(game, s)
        now = {'n': 1, 'tool': tool, 'aim': _aim(game, s), 'odds': _odds(s), 'need': need(s),
               'echo': _echo(game, s), 'hit': _hit(game, s, form, vals), 'miss': _miss(game, cat, s, keep)}
    else:
        # шаг у plan есть, но не к тому, что нужно плану: всё нужное уже на предмете
        kind = 'done' if first.get('step') or first['kind'] == 'done' else first['kind']
        line = tr('готово по плану') if kind == 'done' else (first['parts'][0] if first['parts'] else '')
        now = {'kind': kind, 'line': line, 'miss': None}
        if kind == 'waste':
            # ключ не на месте: его сторону занял не тот. Снять его — только если на предмете есть то, что реже
            # самой ловли ключа; иначе — на верстак
            key_side = next((m['side'] for m in page['normal'] if game.gives(m, key['stat'], key.get('min'))), None) if key else None
            st = state(game, item, page)
            rest = [m for m, s2 in zip(item.get('mods') or [], st['mods']) if s2['side'] != key_side or
                    any(game.gives(s2, e['stat']) for e in form if e['stat'] in wanted)]
            again = plan(cat, dict(item, mods=rest), form, hero, lang).get('step') or {}
            # снимают не то со стороны ключа: предзнаменование стороны — только если на другой стороне есть что снять
            undo = [(rules(cat).get('items') or {}).get('annul'),
                    side_omen(cat, 'annul', key_side, st['loose'].get(other_side(key_side), 0)) if key_side else None]
            now['miss'] = _miss(game, cat, dict(again, act='augment', side=key_side, miss=undo), keep) if again.get('p') else \
                tr('промах — на верстак 3 → 1')
    return {'base': game.name(item['base']), 'ilvl': ilvl, 'rarity': _rarity(item.get('rarity')),
            'kind': now.get('kind') or first['kind'], 'places': places, 'now': now,
            'next': [{'n': s['n'], 'tool': _tool(game, s), 'aim': _aim(game, s), 'odds': _odds(s), 'need': need(s)}
                     for s in steps[1:]]}


def _tier_of(cat, level):
    """Тир путевого камня, зона которого этого уровня (или ближайший ниже). None — уровень ниже карт."""
    tiers = sorted(((int(t), x.get('area') or 0) for t, x in ((cat.get('waystones') or {}).get('tiers') or {}).items()),
                   key=lambda t: t[1])
    hit = [t for t, area in tiers if area <= level]
    return hit[-1] if hit and level >= MAPS_FROM else None


def _where(cat, lo, hi, levels, steps, lang):
    """Где падают предметы уровня lo–hi (hi None — и выше): на картах — тиры («T14+», «T6–T8»), в кампании — зоны
    маршрута такого уровня (настоящий уровень из лога, иначе данные игры). Зона — на языке страницы: по-русски — как
    шаг назван в плане (название из игры), на другом языке — название зоны из данных игры."""
    if lo >= MAPS_FROM:
        a, b = _tier_of(cat, lo), _tier_of(cat, hi) if hi is not None else None
        return 'T%d+' % a if b is None else ('T%d' % a if a == b else 'T%d–T%d' % (a, b))
    areas = cat.get('areas') or {}
    names, seen = [], set()
    for s in steps or ():
        code = s.get('zone')
        lv = (levels or {}).get(code) or (areas.get(code) or {}).get('level') or s.get('level')
        if not lv or lv >= MAPS_FROM or lv < lo or (hi is not None and lv > hi):
            continue
        english = str((areas.get(code) or {}).get('name') or '').strip()
        name = (s.get('name') or english or code) if lang == i18n.SOURCE or not english else english
        if name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        return tr('ур. %d+') % lo if hi is None else span_text(lo, hi, False)
    more = len(names) - 3
    shown = i18n.join(', ', names[:3])
    return tr('%s и ещё %d') % (shown, more) if more > 0 else shown


def hunt(cat, at, slot_id, chain, form, worn_val, here, levels, steps, lang=i18n.SOURCE):
    """«Где искать базу» для слота. Две следующие ступени ключа после надетого (не ниже цели, которую план требует
    сейчас): с какого уровня предмета бывают, лучшее окно уровня белой базы, шанс на базу для обычных, Больших и
    Совершенных сфер, зоны маршрута с таким уровнем; где герой сейчас; готовый ответ («Выбивать +3 сейчас — +4 только
    с T14»). worn_val — число ключа на надетом; here — уровень зоны героя (что сейчас падает); levels — код зоны →
    уровень по логу; steps — шаги плана. None — у слота нет ключа или весов."""
    key = next((e for e in form or () if e['role'] == 'key'), None)
    cands = _period(cat, at, slot_id, chain, at.get('goals'))
    if not key or not cands:
        return None
    game = Game(cat, lang)
    cls, kind, bases, family = cands[0]
    page = page_of(cat, bases[0])
    if page is None:
        return None
    key = fit_form(game, page, [key])[0]
    sid = key['stat']
    tiers = {}
    for m in page['normal']:
        r = game.span(m, sid)
        if r and r[0] is not None:
            tiers.setdefault(r[0], m)
    floor = max(worn_val or 0, (key.get('min') or 0) - EPS) if key.get('min') else (worn_val or 0)
    values = [v for v in sorted(tiers) if v > floor][:2]
    sides = {m['side'] for m in page['normal'] if game.gives(m, sid)}
    side = sides.pop() if len(sides) == 1 else None
    low = min(b.get('level') or 1 for b in bases)
    # выше последнего тира карт предметы на маршруте не падают — лучшее окно ищется до него
    cap = max(((x.get('area') or 0) for x in ((cat.get('waystones') or {}).get('tiers') or {}).values()), default=0) or None
    grades = [tr('обычные'), tr('Большие'), tr('Совершенные')]     # ступени сфер по порядку правил
    marks = []
    for v in values:
        pred = lambda m, v=v: game.gives(m, sid, v)        # noqa: E731
        start = min(m['lvl'] for m in page['normal'] if pred(m))
        win = window(cat, page, pred, side, max(start, low), cap)
        if win is None:
            continue
        lo, hi, p, open_end = win
        rows = catch(cat, page, lo, pred, side)
        best_now = best_catch(catch(cat, page, here, pred, side)) if here and here >= start else None
        marks.append({'value': _num(tiers[v], '%g' % v), 'from': start, 'lo': lo, 'hi': None if open_end else hi,
                      'base': tr('белая база: %s, ур. %s') % (_base_what(game, cat, cands[0], lang), span_text(lo, hi, open_end)),
                      'where': _where(cat, lo, None if open_end else hi, levels, steps, lang),
                      'odds': [{'grade': g, 'odds': one_in(r[4])} for g, r in zip(grades, rows[:3])],
                      'now': one_in(best_now[4]) if best_now else None})
    if not marks:
        return None

    def at_text(level):
        t = _tier_of(cat, level)
        return 'T%d' % t if t else tr('ур. %d') % level
    m0, m1 = marks[0], (marks[1] if len(marks) > 1 else None)
    if here and here >= m0['from']:
        answer = tr('Выбивать %s сейчас') % m0['value']
        if m1:
            answer = (tr('%s — %s уже падает') % (answer, m1['value']) if here >= m1['from'] else
                      tr('%s — %s только с %s') % (answer, m1['value'], at_text(m1['from'])))
    else:
        answer = tr('%s — только с %s') % (m0['value'], at_text(m0['from']))
    # полоса: кампания (если окно ступени или герой ниже карт) и тиры карт по шагам плана
    groups = []
    camp = next((m for m in marks if m['lo'] < MAPS_FROM), None)
    if camp or (here or 0) < MAPS_FROM:
        groups.append({'name': tr('Кампания'), 'cells': [{'label': tr('ур. %d+') % camp['lo'] if camp else '',
                                                           'here': bool(here) and here < MAPS_FROM,
                                                           'mark': camp['value'] if camp else None}]})
    tiers_area = sorted(((int(t), x.get('area') or 0) for t, x in ((cat.get('waystones') or {}).get('tiers') or {}).items()))
    maps = sorted((s for s in steps or () if (s.get('level') or 0) >= MAPS_FROM), key=lambda s: s['level'])
    here_t = _tier_of(cat, here) if here else None
    for i, s in enumerate(maps):
        top = maps[i + 1]['level'] - 1 if i + 1 < len(maps) else max(a for _t, a in tiers_area)
        cells = [{'label': str(t), 'here': t == here_t,
                  'mark': next((m['value'] for m in marks if m['lo'] >= MAPS_FROM and _tier_of(cat, m['lo']) == t), None)}
                 for t, area in tiers_area if s['level'] <= area <= top]
        if cells:
            groups.append({'name': s.get('name') or '', 'cells': cells})
    return {'answer': answer, 'groups': groups, 'marks': marks}


def slot_card(cat, at, row, worn_item=None, hero=None, drop=None, levels=None, steps=(), lang=i18n.SOURCE):
    """«Как сделать» в карточке слота: рецепт надетого предмета (ничего не надето — белой базы в лучшем окне уровня)
    и где искать базу. at — билд на шаге, где предмет строки носят; row — строка слота (core: holders, stash);
    worn_item — запомненный предмет; drop — уровень зоны героя; levels, steps — для зон маршрута (hunt).
    Ключ без цели автора (у сапог — скорость) рецепт ведёт к лучшей ступени того, что падает сейчас.
    None — сказать нечего: нет весов или у слота нет формы."""
    if not (cat or {}).get('craft') or not row or not row.get('slot'):
        return None
    chain = (row.get('base') or {}).get('chain') or ()
    floors = (at.get('floors') or {}).get(row.get('wornKey') or herostats.hero_keys(at).get(row['slot'])) or ()
    cands = [(c, page_of(cat, c[2][0])) for c in _period(cat, at, row['slot'], chain, at.get('goals'))]
    cand, page = next(((c, p) for c, p in cands if p), (None, None))
    if not cand:
        return None
    form = default_form(cat, at, row['slot'], cand[0], floors, wanted_rungs(row))
    if not form:
        return None
    game = Game(cat, lang)
    if form[0].get('min') is None and drop:
        bar = best_bar(cat, game, page, form[0]['stat'], max(drop, min(b.get('level') or 1 for b in cand[2])))
        if bar:
            form = [dict(form[0], min=bar)] + list(form[1:])
    wanted = wanted_of(floors, wanted_rungs(row), form)
    worn_val = next((ln.get('value') for ln in ((row.get('item') or {}).get('lines') or ())
                     if ln.get('id') == form[0]['stat']), 0) or 0
    thing = copied_item(cat, worn_item) if worn_item else None
    if thing is None:
        k, pred, side, need = _key_of(game, page, form)
        low = min(b.get('level') or 1 for b in cand[2])
        win = window(cat, page, pred, side, max(need, low)) if need is not None else None
        lo = win[0] if win else max(low, drop or 1)
        base = min((b for b in cand[2] if (b.get('level') or 1) <= lo), key=lambda b: -(b.get('level') or 1),
                   default=cand[2][0])
        thing = {'base': base['name'], 'ilvl': lo, 'rarity': 'normal', 'mods': []}
    card = recipe(cat, thing, form, wanted, hero, None, lang)
    other = off_path(game, cat, at, row['slot'], chain, thing) if worn_item else None
    if card and other:
        card = _as_other(card, other['line'])
    card = dict(card, worn=bool(worn_item)) if card else None
    found = hunt(cat, at, row['slot'], chain, form, worn_val, drop, levels, steps, lang)
    if not card and not found:
        return None
    return {'recipe': card, 'hunt': found}


# --- срок на удачу ---------------------------------------------------------------------------------------------------

def odds(cat, at, goal):
    """Сколько в среднем стоит порог цели по стату, когда его берут случайным броском: ловля на белой базе в лучшем
    окне уровня (window) — шанс на базу, сколько баз и сфер. at — билд на шаге срока цели (herostats.at_step).
    None — сказать нечего: порог не про одно свойство (сумма на предмете: «дух от 120»), его наверняка даёт
    сущность, у класса нет весов или стат на нём не бывает. Из нескольких классов периода берётся самый дешёвый."""
    if not (cat or {}).get('craft') or not goal.get('slot') or not goal.get('stat') or not isinstance(goal.get('min'), (int, float)):
        return None
    game = Game(cat)
    line = goal.get('use')
    chain = [g['id'] for g in at.get('goals') or () if isinstance(g, dict) and g.get('slot') == goal['slot']
             and not g.get('part') and not g.get('any') and g.get('use') == line]
    best = None
    for cand in _period(cat, at, goal['slot'], chain, at.get('goals')):
        cls, kind, bases, family = cand
        page = page_of(cat, bases[0])
        if page is None:
            continue
        entry = fit_form(game, page, [{'stat': goal['stat'], 'role': 'key', 'min': goal['min']}])[0]
        if entry.get('min') is None:
            return None                     # порог про сумму на предмете: одним свойством его не взять
        if any(game.gives(x, entry['stat'], entry['min']) for x in page['essence']):
            return None                     # сущность даёт его наверняка
        _k, pred, side, need = _key_of(game, page, [entry])
        if need is None:
            continue
        low = min(b.get('level') or 1 for b in bases)
        win = window(cat, page, pred, side, max(need, low))
        if win is None:
            continue
        lo, hi, p, open_end = win
        got = best_catch(catch(cat, page, lo, pred, side))
        n = round(1 / p)
        res = {'p': p, 'bases': n, 'transmute': got[0], 'augment': got[1], 'augments': round(n * got[5]),
               'lo': lo, 'hi': hi, 'open': open_end, 'cand': cand}
        if best is None or res['bases'] < best['bases']:
            best = res
    return best


def luck_text(cat, res, lang=i18n.SOURCE):
    """Замечание «срок на удачу» словами: (текст, подробности)."""
    game = Game(cat, lang)
    n = res['bases']
    text = tr('Срок на удачу: в среднем ≈%d %s и ≈%d × %s') % (n, i18n.plural(n, 'база|базы|баз'), n, game.name(res['transmute']))
    detail = i18n.join(' · ', [tr('%s на базу') % pct(res['p']),
                               _base_line(game, cat, res['cand'], span_text(res['lo'], res['hi'], res['open']), lang),
                               tr('%s, легло на другую сторону — %s') % (game.name(res['transmute']), game.name(res['augment'])),
                               tr('на удачу — больше %d баз в среднем') % LUCK])
    return text, detail
