/* Язык страницы. Стоит в <head> и выполняется до показа страницы.
   «/» — английская страница, «/ru/» — русская.
   - «/ru/» и «/?lang=en» — прямые ссылки на язык: не перенаправляются никогда.
   - «/» без параметра: если язык уже выбран переключателем — он; иначе язык браузера (первый в его списке):
     русский — на «/ru/», любой другой — остаёмся.
   Выбор переключателя запоминает site.js (localStorage, ключ runbook-lang) — больше страница в браузере ничего не хранит. */
(function () {
  var doc = document.documentElement;
  doc.className += ' js';
  if (doc.lang !== 'en') return;
  var saved = null, asked = false;
  try { saved = localStorage.getItem('runbook-lang'); } catch (e) { /* памяти браузера нет — решает язык браузера */ }
  try { asked = new URLSearchParams(location.search).get('lang') === 'en'; } catch (e) { asked = /[?&]lang=en(&|$)/.test(location.search); }
  if (asked) {
    // пришли по переключателю (выбор запомнен) — убираем параметр из адреса; пришли по прямой ссылке — оставляем как есть
    if (saved === 'en' && history.replaceState) history.replaceState(null, '', location.pathname + location.hash);
    return;
  }
  var want = saved === 'en' || saved === 'ru' ? saved : null;
  if (!want) {
    var list = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ''];
    want = /^ru(-|$)/i.test(String(list[0])) ? 'ru' : 'en';
  }
  // страницу открыли файлом с диска (двойным щелчком): там папка сама свою страницу не открывает
  if (want === 'ru') location.replace((location.protocol === 'file:' ? 'ru/index.html' : 'ru/') + location.hash);
})();
