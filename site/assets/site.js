/* PoE2 Runbook — сайт. Что делает этот файл:
   1. блок «Скачать»: читает update/latest.json рядом с сайтом; файла нет или он не того вида — состояние «скоро»;
   2. раздел «Планы»: читает plans/index.json рядом с сайтом; файла нет, он не того вида или пуст — раздела нет;
   3. применяет настройки из config.js: адрес репозитория и контакт для связи;
   4. запоминает язык, выбранный переключателем; кнопки «Скопировать».
   Запросы — только к самому сайту (два: update/latest.json и plans/index.json). Всё, что пришло из этих файлов, ложится
   на страницу только текстом (textContent), никогда разметкой. Текстов для показа здесь нет: все слова — в самой
   странице (атрибуты data-t-… блока «Скачать», заготовка строки плана <template>), перевод правится в одном месте. */
(function () {
  'use strict';
  var cfg = window.RUNBOOK_SITE || {};
  var doc = document.documentElement;
  var lang = doc.lang === 'ru' ? 'ru' : 'en';
  var locale = lang === 'ru' ? 'ru-RU' : 'en-GB';                // числа и дата — как в самой программе (её lang/en.json: en-GB)
  var root = new URL('..', document.currentScript.src);          // папка сайта: на уровень выше assets/
  var $ = function (id) { return document.getElementById(id); };
  var all = function (selector, each) { Array.prototype.forEach.call(document.querySelectorAll(selector), each); };
  var show = function (el, on) { if (el) el.hidden = !on; };
  var https = function (s) { return typeof s === 'string' && /^https:\/\/[^\s<>"']+$/.test(s); };
  var bare = function (url) { return url.replace(/^https?:\/\//, '').replace(/\/$/, ''); };     // адрес, как его пишут в тексте
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

  // --- настройки (config.js) ---------------------------------------------------------------------------------
  if (https(cfg.repo)) {
    all('[data-repo]', function (a) {
      a.href = cfg.repo;
      if (a.hasAttribute('data-repo-text')) a.textContent = bare(cfg.repo);      // в тексте назван сам адрес репозитория
    });
    all('[data-repo-row]', function (el) { show(el, true); });
  }
  if (typeof cfg.contact === 'string' && cfg.contact.trim()) {
    var to = cfg.contact.trim();
    var mail = /^[^\s@<>"'?&]+@[^\s@<>"'?&]+\.[^\s@<>"'?&]+$/.test(to);
    var subject = typeof cfg.contactSubject === 'string' ? cfg.contactSubject.trim() : '';
    if (mail || https(to)) {
      all('[data-contact]', function (a) {
        a.href = mail ? 'mailto:' + to + (subject ? '?subject=' + encodeURIComponent(subject) : '') : to;
        a.textContent = mail ? to : bare(to);
      });
      all('[data-contact-row]', function (el) { show(el, true); });
    }
  }

  // --- язык: выбор переключателя запоминается; раздел страницы при смене языка остаётся тем же -----------------
  all('a[data-lang]', function (a) {
    if (location.protocol === 'file:') a.href = a.getAttribute('href').replace(/\/(\?|$)/, '/index.html$1');
    a.addEventListener('click', function () {
      try { localStorage.setItem('runbook-lang', a.getAttribute('data-lang')); } catch (e) { /* без памяти браузера — по ссылке */ }
      if (location.hash) a.href = a.href.split('#')[0] + location.hash;
    });
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
  var words = function (texts, max) {                            // {язык: текст}: на языке страницы, иначе английский, иначе русский
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
  var box = $('download');
  if (!box) return;
  var soon = function () { show($('dl-wait'), false); show($('dl-ready'), false); show($('dl-soon'), true); };
  var text = function (key, values) {
    return (box.getAttribute('data-t-' + key) || '').replace(/\{(\w+)\}/g, function (m, k) { return k in values ? values[k] : m; });
  };

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

  function ready(r) {
    var num = function (n, opts) { try { return n.toLocaleString(locale, opts); } catch (e) { return String(n); } };
    var a = $('dl-link');
    a.href = r.url;
    a.textContent = text('button', {version: r.version});
    $('dl-version').textContent = r.version;
    $('dl-game').textContent = r.game;
    // как в свойствах файла у Windows: мегабайт — 1024 × 1024 байт; рядом точное число байт
    $('dl-size').textContent = text('mb', {n: num(r.size / 1048576, {minimumFractionDigits: 1, maximumFractionDigits: 1})});
    $('dl-bytes').textContent = text('bytes', {n: num(r.size)});
    $('dl-date').textContent = r.date || '—';
    $('dl-sha').textContent = r.sha;
    if (r.file) {
      $('dl-file').textContent = r.file;
      all('[data-file]', function (el) { el.textContent = r.file; });
    }
    if (r.notes) { $('dl-notes-text').textContent = r.notes; show($('dl-notes'), true); }
    show($('dl-wait'), false); show($('dl-soon'), false); show($('dl-ready'), true);
  }

  read('update/latest.json').then(function (d) { var r = release(d); if (r) ready(r); else soon(); });
})();
