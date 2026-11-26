/* PoE2 Runbook — сайт. Что делает этот файл:
   1. «Скачать»: читает update/latest.json рядом с сайтом. Сборка есть — кнопки «Скачать» на всех страницах ведут
      прямо к установщику, под нижней кнопкой главной встаёт строка «Версия … · для игры … · … МБ», на странице
      установки — блок целиком. Файла нет или он не того вида — кнопки ведут на страницу установки, там состояние
      «скоро», а на главной — «Первая сборка ещё не опубликована»;
   2. «Готовые планы» на главной: читает plans/index.json рядом с сайтом; файла нет, он не того вида или пуст —
      раздела нет;
   3. применяет настройки из config.js: адрес репозитория и контакт для связи;
   4. запоминает язык, выбранный в списке шапки; кнопки «Скопировать» и «Раскрыть всё».
   Запросы — только к самому сайту (update/latest.json, а на главной ещё plans/index.json). Всё, что пришло из этих
   файлов, ложится на страницу только текстом (textContent), никогда разметкой. Текстов для показа здесь нет: все
   слова — в самой странице (атрибуты data-t-…, заготовка строки плана <template>), перевод правится в одном месте. */
(function () {
  'use strict';
  var cfg = window.RUNBOOK_SITE || {};
  var doc = document.documentElement;
  var lang = (doc.lang || 'en').toLowerCase().split('-')[0];     // код языка страницы, как у программы: «pt-BR» -> «pt»
  var locale = doc.getAttribute('data-locale') || 'en-GB';       // числа и дата — как в самой программе (locale её языкового файла)
  var root = new URL('..', document.currentScript.src);          // папка сайта: на уровень выше assets/
  var $ = function (id) { return document.getElementById(id); };
  var all = function (selector, each) { Array.prototype.forEach.call(document.querySelectorAll(selector), each); };
  var show = function (el, on) { if (el) el.hidden = !on; };
  var https = function (s) { return typeof s === 'string' && /^https:\/\/[^\s<>"']+$/.test(s); };
  var bare = function (url) { return url.replace(/^https?:\/\//, '').replace(/\/$/, ''); };     // адрес, как его пишут в тексте
  var num = function (n, opts) { try { return n.toLocaleString(locale, opts); } catch (e) { return String(n); } };
  var fill = function (template, values) {
    return (template || '').replace(/\{(\w+)\}/g, function (m, k) { return k in values ? values[k] : m; });
  };
  var day = function (s) {                                       // 'ГГГГ-ММ-ДД' -> дата словами на языке страницы; не дата — ''
    var m = /^(\d{4})-(\d\d)-(\d\d)$/.exec(typeof s === 'string' ? s : '');
    if (!m) return '';
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    try { return d.toLocaleDateString(locale, {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'}); }
    catch (e) { return m[0]; }
  };
  var read = function (path) {                                   // файл данных рядом с сайтом: JSON или null
    if (!window.fetch) return Promise.resolve(null);
    return fetch(new URL(path, root), {cache: 'no-store'})
      .then(function (res) { return res.ok ? res.json() : null; })
      .catch(function () { return null; });
  };

  // --- страницу открыли файлом с диска: там папка сама свою страницу не открывает ---------------------------------
  if (location.protocol === 'file:') {
    all('a[href]', function (a) {
      var h = a.getAttribute('href');
      if (/^(https?:|mailto:|#)/.test(h)) return;
      var m = /^([^?#]*)([?#].*)?$/.exec(h);
      if (m && (m[1] === '' || /\/$/.test(m[1]))) a.setAttribute('href', m[1] + 'index.html' + (m[2] || ''));
    });
  }

  // --- настройки (config.js) ---------------------------------------------------------------------------------
  if (https(cfg.repo)) {
    all('[data-repo]', function (a) {
      a.href = cfg.repo;
      if (a.hasAttribute('data-repo-text')) a.textContent = bare(cfg.repo);      // в тексте назван сам адрес репозитория
    });
    all('[data-repo-row]', function (el) { show(el, true); });
  }
  if (https(cfg.issues)) {                                       // раздел задач открытого репозитория
    all('[data-issues]', function (a) { a.href = cfg.issues; });
    all('[data-issues-row]', function (el) { show(el, true); });
  }
  if (typeof cfg.contact === 'string' && cfg.contact.trim()) {
    var to = cfg.contact.trim();
    var mail = /^[^\s@<>"'?&]+@[^\s@<>"'?&]+\.[^\s@<>"'?&]+$/.test(to);
    var subject = typeof cfg.contactSubject === 'string' ? cfg.contactSubject.trim() : '';
    if (mail || https(to)) {
      all('[data-contact]', function (a) {
        a.href = mail ? 'mailto:' + to + (subject ? '?subject=' + encodeURIComponent(subject) : '') : to;
        if (!a.hasAttribute('data-contact-keep')) a.textContent = mail ? to : bare(to);       // у ссылки свои слова — остаются
      });
      all('[data-contact-row]', function (el) { show(el, true); });
    }
  }

  // --- английскую страницу открыли по ссылке с «?lang=en», а язык не выбран: ссылки на другие страницы несут ту же
  //     пометку, иначе русский браузер на следующей же странице увёл бы на русскую ---------------------------------
  var saved = null;
  try { saved = localStorage.getItem('runbook-lang'); } catch (e) { /* памяти браузера нет */ }
  if (lang === 'en' && saved !== 'en' && /[?&]lang=en(&|$)/.test(location.search)) {
    all('a[href]', function (a) {
      var h = a.getAttribute('href');
      if (a.hasAttribute('data-lang') || /^(https?:|mailto:|#)/.test(h)) return;
      var m = /^([^?#]*)(#.*)?$/.exec(h);
      if (m && (m[1] === '' || /(\/|index\.html)$/.test(m[1]))) a.setAttribute('href', m[1] + '?lang=en' + (m[2] || ''));
    });
  }

  // --- язык: выбор запоминается; место на странице при смене языка остаётся тем же --------------------------------
  all('a[data-lang]', function (a) {
    a.addEventListener('click', function () {
      try { localStorage.setItem('runbook-lang', a.getAttribute('data-lang')); } catch (e) { /* без памяти браузера — по ссылке */ }
      if (location.hash) a.href = a.href.split('#')[0] + location.hash;
    });
  });
  // шапка в узком окне: если название языка не помещается между именем программы и кнопкой — вместо него код языка
  var bar = document.querySelector('.bar');
  var fitBar = function () {
    var brand = bar.querySelector('.brand'), nav = bar.querySelector('.bar-nav');
    bar.classList.remove('tight');
    if (brand && nav && nav.getBoundingClientRect().left - brand.getBoundingClientRect().right < 16) bar.classList.add('tight');
  };
  if (bar) { fitBar(); window.addEventListener('resize', fitBar); }
  // список языков в шапке закрывается нажатием мимо него и клавишей Esc (открывается и без скрипта: это <details>)
  all('details.langs', function (menu) {
    document.addEventListener('click', function (e) { if (menu.open && !menu.contains(e.target)) menu.open = false; });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && menu.open) { menu.open = false; menu.querySelector('summary').focus(); } });
  });

  // --- «Скопировать» ---------------------------------------------------------------------------------------------
  all('button[data-copy]', function (b) {
    if (!navigator.clipboard || !navigator.clipboard.writeText) return;
    show(b, true);
    var word = b.textContent;
    b.addEventListener('click', function () {
      var src = $(b.getAttribute('data-copy'));
      if (!src) return;
      navigator.clipboard.writeText(src.textContent.trim()).then(function () {
        b.textContent = b.getAttribute('data-done') || word;
        b.classList.add('done');
        setTimeout(function () { b.textContent = word; b.classList.remove('done'); }, 1600);
      }, function () { /* браузер не дал записать — текст можно выделить и скопировать рукой */ });
    });
  });

  // --- пояснения под раскрытием: «Раскрыть всё»; ссылка на место внутри закрытого пояснения открывает его ---------
  all('button[data-open-all]', function (b) {
    var open = false, words = [b.textContent, b.getAttribute('data-on') || b.textContent];
    show(b, true);
    b.addEventListener('click', function () {
      open = !open;
      all('main details', function (d) { d.open = open; });
      b.textContent = words[open ? 1 : 0];
    });
  });
  var reveal = function () {
    var el = location.hash.length > 1 ? $(decodeURIComponent(location.hash.slice(1))) : null;
    for (var p = el; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
  };
  try { reveal(); } catch (e) { /* адрес с кривым %-кодом — раскрывать нечего */ }
  window.addEventListener('hashchange', function () { try { reveal(); } catch (e) { /* то же */ } });

  // --- «Планы» ---------------------------------------------------------------------------------------------------
  /* Каталог одобренных планов: {"format": "poe2-runbook-plans", "v": 1, "updated", "plans": [{"uid", "version",
     "title": {"ru", "en"}, "author": {"name", "url"}, "game", "class", "ascendancy", "tags", "langs",
     "summary": {"ru", "en"}, "changed", "published": "ГГГГ-ММ-ДД", "file": {…}}]}. Показывается: название, автор
     (ссылкой — только адрес http(s)), версия игры, версия плана и дата, одно предложение описания. Ставится план из
     самой программы — ссылки на файл плана на странице нет. */
  var line = function (v, max) {                                 // значение из файла одной строкой текста; не текст и не число — ''
    if (typeof v === 'number' && isFinite(v)) v = String(v);
    if (typeof v !== 'string') return '';
    v = v.replace(/[\u0000-\u001f\u007f-\u009f‎‏‪-‮⁦-⁩]+/g, ' ').replace(/\s+/g, ' ').trim();
    return v.length > max ? v.slice(0, max - 1).trim() + '…' : v;
  };
  var words = function (texts, max) {                            // {код языка: текст}: на языке страницы, иначе английский, иначе русский
    if (!texts || typeof texts !== 'object') return '';
    return line(texts[lang], max) || line(texts.en, max) || line(texts.ru, max);
  };
  function catalogue(d) {
    if (!d || d.format !== 'poe2-runbook-plans' || d.v !== 1 || !Array.isArray(d.plans)) return [];
    var out = [];
    d.plans.slice(0, 200).forEach(function (p) {
      if (!p || typeof p !== 'object') return;
      var title = words(p.title, 120) || line(p.uid, 40);
      if (!title) return;
      var who = p.author && typeof p.author === 'object' ? p.author : {};
      out.push({
        title: title, author: line(who.name, 80),
        url: typeof who.url === 'string' && /^https?:\/\/[^\s<>"']+$/.test(who.url) ? who.url : '',
        game: line(p.game, 20), version: line(p.version, 20), date: day(p.published), summary: words(p.summary, 300)
      });
    });
    return out;
  }
  function plans(list) {
    var tpl = $('plan-tpl'), box = $('plans-list');
    if (!list.length || !tpl || !box || !tpl.content) return;
    list.forEach(function (p) {
      var row = tpl.content.firstElementChild.cloneNode(true);
      var part = function (name) { return row.querySelector('[data-p="' + name + '"]'); };
      var put = function (name, text, holder) {                  // пустое значение — его кусок строки убирается целиком
        var el = part(name), wrap = holder ? part(holder) : el;
        if (text) el.textContent = text; else if (wrap) wrap.remove();
      };
      put('title', p.title);
      put('game', p.game, 'game-row');
      put('version', p.version, 'version-row');
      put('date', p.date);
      put('summary', p.summary);
      if (p.author && p.url) {                                   // автор со своей страницей — ссылкой; чужой адрес не «рекомендуется»
        var a = document.createElement('a');
        a.href = p.url; a.rel = 'noopener noreferrer nofollow'; a.textContent = p.author;
        part('author').appendChild(a);
      } else {
        put('author', p.author, 'author-row');
      }
      // между оставшимися кусками строки — точка настоящим текстом: так строка и читается вслух, и копируется
      var meta = row.querySelector('.pm');
      Array.prototype.slice.call(meta.children, 1).forEach(function (el) { meta.insertBefore(document.createTextNode(' · '), el); });
      if (!meta.children.length) meta.remove();
      box.appendChild(row);
    });
    all('[data-plans-row]', function (el) { show(el, true); });
  }
  if ($('plans-list')) read('plans/index.json').then(function (d) { plans(catalogue(d)); });

  // --- «Скачать» ---------------------------------------------------------------------------------------------------
  /* Файл выпуска: {"format": "poe2-runbook-update", "v": 1, "version", "game", "published": "ГГГГ-ММ-ДД",
     "installer": {"url", "size", "sha256"}, "notes": {"ru", "en"}}; незнакомые поля пропускаются. Что-то не так —
     выпуска для страницы нет. Тот же файл читает сама программа (и проверяет его подпись). */
  function release(d) {
    var i = d && d.installer;
    if (!d || d.format !== 'poe2-runbook-update' || d.v !== 1 || !i) return null;
    if (!/^\d+(\.\d+){1,4}$/.test(d.version) || !/^\d+(\.\d+){1,3}$/.test(d.game)) return null;
    if (!https(i.url) || !/^[0-9a-f]{64}$/i.test(i.sha256) || typeof i.size !== 'number' || !(i.size > 0)) return null;
    var file = decodeURIComponent(i.url.split(/[?#]/)[0].split('/').pop() || '');
    return {
      version: d.version, game: d.game, url: i.url, size: Math.round(i.size), sha: i.sha256.toLowerCase(),
      date: day(d.published), file: /^[\w.() -]{1,120}\.exe$/i.test(file) ? file : '',
      notes: d.notes && typeof d.notes[lang] === 'string' ? d.notes[lang].trim() : ''
    };
  }

  var box = document.querySelector('[data-dl-panel]');           // блок «Скачать» страницы установки
  var get = $('get');                                            // строка под кнопкой первого экрана главной
  var rel = document.querySelector('.release');                  // блок выпуска главной: название с версией и строка сведений
  // как в свойствах файла у Windows: мегабайт — 1024 × 1024 байт; на главной — целым числом, на «Установке» — с десятой
  var megabytes = function (el, r, digits) {
    return fill(el.getAttribute('data-t-mb'), {n: num(r.size / 1048576, {minimumFractionDigits: digits, maximumFractionDigits: digits})});
  };

  function ready(r) {
    all('[data-dl-link]', function (a) { a.href = r.url; });     // один щелчок до установщика с любой страницы
    if (get) $('dl-line').textContent = fill(get.getAttribute('data-t-line'), {version: r.version, game: r.game});
    if (rel) {
      var when = r.date.replace(/\s*г\.$/, '');                  // «26 ноября 2026» — как в строке выпуска, без «г.»
      $('rel-name').textContent = fill(rel.getAttribute('data-t-name'), {version: r.version});
      $('rel-before').textContent = fill(rel.getAttribute('data-t-before'), {date: when, game: r.game}).replace(/^ · /, '');
      $('rel-after').textContent = fill(rel.getAttribute('data-t-after'), {size: megabytes(rel, r, 0)});
      show($('rel-before'), true); show($('rel-after'), true);
    }
    if (!box) return;
    var a = $('dl-link');
    a.href = r.url;
    a.textContent = fill(box.getAttribute('data-t-button'), {version: r.version});
    $('dl-version').textContent = r.version;
    $('dl-game').textContent = r.game;
    $('dl-size').textContent = megabytes(box, r, 1);             // рядом — точное число байт
    $('dl-bytes').textContent = fill(box.getAttribute('data-t-bytes'), {n: num(r.size)});
    $('dl-date').textContent = r.date || '—';
    $('dl-sha').textContent = r.sha;
    if (r.file) {
      $('dl-file').textContent = r.file;
      all('[data-file]', function (el) { el.textContent = r.file; });
    }
    if (r.notes) { $('dl-notes-text').textContent = r.notes; show($('dl-notes'), true); }
    show($('dl-wait'), false); show($('dl-soon'), false); show($('dl-ready'), true);
  }
  function soon() {
    if (get) { show($('dl-line'), false); show($('dl-none'), true); }
    show($('rel-none'), true);
    if (!box) return;
    show($('dl-wait'), false); show($('dl-ready'), false); show($('dl-soon'), true);
  }

  read('update/latest.json').then(function (d) {
    var r = release(d);
    if (r) ready(r); else soon();
    doc.className += ' dl-done';                                 // состояние блока «Скачать» известно (для проверок страницы)
  });
})();
