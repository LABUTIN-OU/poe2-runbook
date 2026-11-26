/* PoE2 Runbook — сайт. Что делает этот файл:
   1. блок «Скачать»: читает update/latest.json рядом с сайтом; файла нет или он не того вида — состояние «скоро»;
   2. применяет настройки из config.js: ссылка на исходный код, блок «Связь», строка о проверке обновлений;
   3. запоминает язык, выбранный переключателем; кнопки «Скопировать».
   Запросы — только к самому сайту (один: update/latest.json). Текстов для показа здесь нет: все слова — в самой
   странице (атрибуты data-t-… блока «Скачать»), поэтому перевод правится в одном месте — в HTML. */
(function () {
  'use strict';
  var cfg = window.RUNBOOK_SITE || {};
  var doc = document.documentElement;
  var lang = doc.lang === 'ru' ? 'ru' : 'en';
  var locale = lang === 'ru' ? 'ru-RU' : 'en-GB';                // числа и дата — как в самой программе (её lang/en.json: en-GB)
  var root = new URL('..', document.currentScript.src);          // папка сайта: на уровень выше assets/
  var $ = function (id) { return document.getElementById(id); };
  var show = function (el, on) { if (el) el.hidden = !on; };

  // --- настройки (config.js) ---------------------------------------------------------------------------------
  var https = function (s) { return typeof s === 'string' && /^https:\/\/[^\s<>"']+$/.test(s); };
  var bare = function (url) { return url.replace(/^https:\/\//, '').replace(/\/$/, ''); };      // адрес, как его пишут в тексте
  if (https(cfg.repo)) {
    Array.prototype.forEach.call(document.querySelectorAll('[data-repo]'), function (a) {
      a.href = cfg.repo;
      if (a.hasAttribute('data-repo-text')) a.textContent = bare(cfg.repo);      // в тексте назван сам адрес репозитория
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-repo-row]'), function (el) { show(el, true); });
  }
  if (typeof cfg.contact === 'string' && cfg.contact.trim()) {
    var to = cfg.contact.trim(), link = $('contact-link');
    var mail = /^[^\s@<>"'?&]+@[^\s@<>"'?&]+\.[^\s@<>"'?&]+$/.test(to);
    var subject = typeof cfg.contactSubject === 'string' ? cfg.contactSubject.trim() : '';
    if (link && (mail || https(to))) {
      link.href = mail ? 'mailto:' + to + (subject ? '?subject=' + encodeURIComponent(subject) : '') : to;
      link.textContent = mail ? to : bare(to);
      show($('contact'), true);
    }
  }
  show($('net-update'), cfg.updateCheck === true);
  show($('net-none'), cfg.updateCheck !== true);

  // --- язык: выбор переключателя запоминается; раздел страницы при смене языка остаётся тем же -----------------
  Array.prototype.forEach.call(document.querySelectorAll('a[data-lang]'), function (a) {
    if (location.protocol === 'file:') a.href = a.getAttribute('href').replace(/\/(\?|$)/, '/index.html$1');
    a.addEventListener('click', function () {
      try { localStorage.setItem('runbook-lang', a.getAttribute('data-lang')); } catch (e) { /* без памяти браузера — по ссылке */ }
      if (location.hash) a.href = a.href.split('#')[0] + location.hash;
    });
  });

  // --- «Скопировать» ---------------------------------------------------------------------------------------------
  Array.prototype.forEach.call(document.querySelectorAll('button[data-copy]'), function (b) {
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

  // --- «Скачать» ---------------------------------------------------------------------------------------------------
  var box = $('download');
  if (!box) return;
  var soon = function () { show($('dl-wait'), false); show($('dl-ready'), false); show($('dl-soon'), true); };
  var text = function (key, values) {
    return (box.getAttribute('data-t-' + key) || '').replace(/\{(\w+)\}/g, function (m, k) { return k in values ? values[k] : m; });
  };

  /* Файл выпуска: {"format": "poe2-runbook-update", "v": 1, "version", "game", "published": "ГГГГ-ММ-ДД",
     "installer": {"url", "size", "sha256"}, "notes": {"ru", "en"}}. Что-то не так — выпуска для страницы нет. */
  function release(d) {
    var i = d && d.installer;
    if (!d || d.format !== 'poe2-runbook-update' || d.v !== 1 || !i) return null;
    if (!/^\d+(\.\d+){1,4}$/.test(d.version) || !/^\d+(\.\d+){1,3}$/.test(d.game)) return null;
    if (!https(i.url) || !/^[0-9a-f]{64}$/i.test(i.sha256) || typeof i.size !== 'number' || !(i.size > 0)) return null;
    var day = /^(\d{4})-(\d\d)-(\d\d)$/.exec(d.published || '');
    var file = decodeURIComponent(i.url.split(/[?#]/)[0].split('/').pop() || '');
    return {
      version: d.version, game: d.game, url: i.url, size: Math.round(i.size), sha: i.sha256.toLowerCase(),
      date: day ? new Date(Date.UTC(+day[1], +day[2] - 1, +day[3])) : null,
      file: /^[\w.() -]{1,120}\.exe$/i.test(file) ? file : '',
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
    if (r.date) {
      try {
        $('dl-date').textContent = r.date.toLocaleDateString(locale, {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'});
      } catch (e) { $('dl-date').textContent = r.date.toISOString().slice(0, 10); }
    } else {
      $('dl-date').textContent = '—';
    }
    $('dl-sha').textContent = r.sha;
    if (r.file) {
      $('dl-file').textContent = r.file;
      Array.prototype.forEach.call(document.querySelectorAll('[data-file]'), function (el) { el.textContent = r.file; });
    }
    if (r.notes) { $('dl-notes-text').textContent = r.notes; show($('dl-notes'), true); }
    show($('dl-wait'), false); show($('dl-soon'), false); show($('dl-ready'), true);
  }

  if (!window.fetch) { soon(); return; }
  fetch(new URL('update/latest.json', root), {cache: 'no-store'})
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (d) { var r = release(d); if (r) ready(r); else soon(); })
    .catch(soon);
})();
