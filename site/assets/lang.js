/* Язык страницы. Стоит в <head> и выполняется до показа страницы.
   У каждой страницы есть общий адрес — английская страница («/», «/safety/»…) — и по адресу на каждый другой язык
   сайта («/ru/», «/de/safety/»…).
   - Адрес языка и общий адрес с «?lang=en» — прямые ссылки на язык: не перенаправляются никогда.
   - Общий адрес без параметра: если язык уже выбран в шапке — он; иначе первый из языков браузера (по порядку его
     списка), который есть на сайте; такого нет или это английский — остаёмся.
   Какие языки есть и где их страницы, общая страница называет сама (<html data-langs="ru de …" data-root data-page>).
   Выбор в шапке запоминает site.js (localStorage, ключ runbook-lang) — больше страница в браузере ничего не хранит. */
(function () {
  var doc = document.documentElement;
  doc.className += ' js';
  var langs = (doc.getAttribute('data-langs') || '').split(' ').filter(Boolean);
  if (!langs.length) return;                                     // страница языка, или язык на сайте один
  var saved = null, asked = false;
  try { saved = localStorage.getItem('runbook-lang'); } catch (e) { /* памяти браузера нет — решает язык браузера */ }
  try { asked = new URLSearchParams(location.search).get('lang') === 'en'; } catch (e) { asked = /[?&]lang=en(&|$)/.test(location.search); }
  if (asked) {
    // пришли из списка языков (выбор запомнен) — убираем параметр из адреса; пришли по прямой ссылке — оставляем как есть
    if (saved === 'en' && history.replaceState) history.replaceState(null, '', location.pathname + location.hash);
    return;
  }
  var want = saved === 'en' || langs.indexOf(saved) >= 0 ? saved : null;
  if (!want) {
    var list = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ''];
    for (var i = 0; i < list.length && !want; i++) {
      var code = String(list[i]).toLowerCase().split(/[-_;]/)[0].trim();   // «pt-BR» -> «pt», «de-AT» -> «de»
      if (code === 'en' || langs.indexOf(code) >= 0) want = code;
    }
  }
  if (!want || want === 'en') return;
  // страницу открыли файлом с диска (двойным щелчком): там папка сама свою страницу не открывает
  location.replace((doc.getAttribute('data-root') || '') + want + '/' + (doc.getAttribute('data-page') || '') +
    (location.protocol === 'file:' ? 'index.html' : '') + location.hash);
})();
